"""Портфельный оптимизатор v1.0 — стадия A (Portfolio_Optimizer_Specification_v1.0 §1–7, §12–13): непрерывные целевые веса
по совместным MC-путям, лексикографическая цель без единого балла, жёсткие ограничения без тихого ослабления.

Цель: max медианный CAGR 5Y портфеля; среди решений в пределах objective_tolerance (0.5 п.п.) — лучший ES5 (5Y), затем меньшая
Scenario Concentration (при единственном сценарии BASE — не определена, пропускается), затем меньший оборот от текущего.
Портфель на пути: PV_h = Σ w_i·r_i,h + w_dp·(1+r_dp)^h + w_fixed·1.0 (позиции вне оптимизации держатся на текущих весах с
ПЛОСКОЙ доходностью — явное допущение первой валидации: у них нет калибровок; их веса участвуют в лимитах сектора/топ-3/
общей причины, но не в распределении доходности). Оптимизация по standalone-медианам запрещена (§7) — только совместные пути.

inputs: {"paths_files": {tk: .npz}, "weights_current": {tk: w} (все позиции, доли NAV), "fixed_weights": {tk: w} (вне оптимизации),
         "dry_powder_current": w, "dry_powder_return_annual": r, "regime": "Normal|Stress|Shock",
         "limits": {"sector_max", "top3_aggregate_max", "common_cause_effective_max", "roles": {"Challenger_max_per_name",
                    "Challenger_aggregate_max"}, "dry_powder": {regime: {"min","preferred_max","hard_max"}},
                    "risk_5y": {"p_loss_gt_30_max","p_loss_gt_50_max","es5_min"}},
         "per_name_caps": {tk: cap} (target_cap из Conviction Overlay), "roles": {tk: "Core|Challenger|Watch"|None},
         "sectors": {tk: sector_id}, "common_cause": {cause: {tk: severity_factor}},
         "mpc_range": {"min_weight": 0, "max_weight": 0.2, "grid_step": 0.01, "local_refinement_step": 0.005},
         "objective_tolerance_pp": 0.5, "starts": ["current","equal","empty"] (+ "given": start_weights/start_dry_powder),
         "search_paths": 100000, "max_paths": null}
outputs: proposed_weights, dry_powder_weight, feasible_weight_bands, portfolio_return_distribution (3/5/8Y), portfolio_downside,
  sector/common_cause/top3 concentrations, binding_constraints, constraint_gaps_vs_current, marginal_curves (MPC-сетка по бумаге),
  evaluations, infeasible (+ minimum_relaxations), decision: none. Детерминирован (перебор без случайности; seed не используется).
"""
from __future__ import annotations

import math

import numpy as np

from engine import portfolio_paths

VERSION = "1.0.2"
HORIZONS = (("Y3", "r3", 3), ("Y5", "r5", 5), ("Y8", "r8", 8))


def _metrics(pv: np.ndarray, years: int) -> dict:
    cagr = np.power(np.clip(pv, 1e-12, None), 1.0 / years) - 1.0
    ret = pv - 1.0
    k = max(1, int(math.ceil(0.05 * len(ret))))
    return {"median_CAGR": float(np.median(cagr)), "P_2x": float((pv >= 2).mean()), "P_loss_gt_30pct": float((pv < 0.7).mean()),
            "P_loss_gt_50pct": float((pv < 0.5).mean()), "expected_shortfall_5pct": float(np.partition(ret, k - 1)[:k].mean()),
            "CAGR_quantiles": {str(q): float(np.quantile(cagr, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}}


def _fast_metrics(pv: np.ndarray, years: int) -> dict:
    """Метрики поиска без сортировки квантилей: медиана CAGR и ES5 из ОДНОЙ partition (порядковые статистики k−1, n//2−1, n//2), P(loss)."""
    n = len(pv); k = max(1, int(math.ceil(0.05 * n))); mid = n // 2
    part = np.partition(pv, [k - 1, mid - 1, mid] if n % 2 == 0 else [k - 1, mid])
    med = float(0.5 * (part[mid - 1] + part[mid])) if n % 2 == 0 else float(part[mid])
    return {"median_CAGR": float(np.power(max(med, 1e-12), 1.0 / years) - 1.0), "P_2x": float((pv >= 2).mean()), "P_loss_gt_30pct": float((pv < 0.7).mean()),
            "P_loss_gt_50pct": float((pv < 0.5).mean()), "expected_shortfall_5pct": float(part[:k].mean() - 1.0)}


class _Problem:
    def __init__(self, inputs: dict, data: dict | None = None):
        """data — уже загруженные пути {ticker: load_paths(...)} (Stability Test подаёт возмущённые копии без записи на диск);
        inputs.max_paths — усечение числа путей (первые N совместных path_id; для серий возмущений)."""
        files = inputs.get("paths_files") or {}
        self.tick = sorted(data) if data is not None else sorted(files)
        if not self.tick:
            raise ValueError("paths_files пуст")
        if data is None:
            data = {t: portfolio_paths.load_paths(files[t]) for t in self.tick}
        ref = data[self.tick[0]]["meta"]
        for t, d in data.items():
            m = d["meta"]
            if (m.get("global_seed"), m.get("chunk"), m.get("paths")) != (ref.get("global_seed"), ref.get("chunk"), ref.get("paths")) or not m.get("joint"):
                raise ValueError(f"пути {t} не выровнены с {self.tick[0]} или без Joint Layer — совместный портфель не считается")
        n = min(len(d["r5"]) for d in data.values())
        if inputs.get("max_paths"):
            n = min(n, int(inputs["max_paths"]))
        self.n = n
        self.R = {key: np.stack([data[t][key][:n].astype(np.float64) for t in self.tick], axis=1) for _, key, _ in HORIZONS}
        # поиск — на первых search_paths совместных путях (те же path_id у всех компаний), итог и проверка допустимости — на всех
        self.n_search = int(min(n, int(inputs.get("search_paths", 100_000))))
        self.R5s = self.R["r5"][: self.n_search]
        self.meta = {t: data[t]["meta"] for t in self.tick}
        cur = {k: float(v) for k, v in (inputs.get("weights_current") or {}).items()}
        self.fixed = {k: float(v) for k, v in (inputs.get("fixed_weights") or {}).items()}
        self.cur = np.array([cur.get(t, 0.0) for t in self.tick])
        self.dp_cur = float(inputs.get("dry_powder_current", 0.0))
        self.rdp = float(inputs.get("dry_powder_return_annual", 0.0))
        self.fixed_total = float(sum(self.fixed.values()))
        self.budget = 1.0 - self.fixed_total                       # Σ оптимизируемых + dry powder
        if self.budget <= 0:
            raise ValueError("нет бюджета для оптимизации: fixed_weights ≥ 1")
        L = inputs.get("limits") or {}
        self.regime = inputs.get("regime") or "Normal"
        dp = (L.get("dry_powder") or {}).get(self.regime) or {"min": 0.05, "preferred_max": 0.10, "hard_max": 0.15}
        self.dp_min, self.dp_pref, self.dp_max = float(dp["min"]), float(dp.get("preferred_max", dp["hard_max"])), float(dp["hard_max"])
        self.sector_max = L.get("sector_max"); self.top3_max = L.get("top3_aggregate_max"); self.cc_max = L.get("common_cause_effective_max")
        roles_lim = L.get("roles") or {}
        self.ch_name = roles_lim.get("Challenger_max_per_name"); self.ch_agg = roles_lim.get("Challenger_aggregate_max")
        risk = L.get("risk_5y") or {}
        self.p30_max, self.p50_max, self.es5_min = risk.get("p_loss_gt_30_max"), risk.get("p_loss_gt_50_max"), risk.get("es5_min")
        caps = inputs.get("per_name_caps") or {}
        rng = inputs.get("mpc_range") or {}
        self.wmax_default = float(rng.get("max_weight", 0.20)); self.step = float(rng.get("grid_step", 0.01)); self.fine = float(rng.get("local_refinement_step", 0.005))
        self.roles = inputs.get("roles") or {}
        # потолок бумаги: явный (target_cap Conviction Overlay, может быть выше 20 % для conviction-тега) либо верх MPC-диапазона 0–20 %;
        # Challenger — дополнительно роль-лимит
        self.cap = np.array([min(float(caps[t]) if caps.get(t) is not None else self.wmax_default,
                                 float(self.ch_name) if (self.roles.get(t) == "Challenger" and self.ch_name is not None) else 9.0) for t in self.tick])
        self.cap = np.array([0.0 if self.roles.get(t) == "Watch" else c for t, c in zip(self.tick, self.cap)])
        self.sectors = inputs.get("sectors") or {}
        self.cc = inputs.get("common_cause") or {}
        # матричная форма концентраций (1.0.2): секторы, общие причины, Challenger — без словарных циклов на каждую оценку
        kk = len(self.tick); sec_of = lambda t: self.sectors.get(t, "UNMAPPED")  # noqa: E731
        self._sec_ids = sorted({sec_of(t) for t in list(self.tick) + list(self.fixed)})
        self._S = np.zeros((len(self._sec_ids), kk))
        for i, t in enumerate(self.tick):
            self._S[self._sec_ids.index(sec_of(t)), i] = 1.0
        self._sec_fixed = np.array([sum(float(x) for t, x in self.fixed.items() if sec_of(t) == sct) for sct in self._sec_ids])
        self._cc_ids = list(self.cc)
        self._CC = np.array([[float(m.get(t, 0.0)) for t in self.tick] for m in self.cc.values()]).reshape(len(self._cc_ids), kk)
        self._cc_fixed = np.array([sum(float(self.fixed.get(t, 0.0)) * float(f) for t, f in m.items() if t in self.fixed) for m in self.cc.values()])
        self._chal = np.array([1.0 if self.roles.get(t) == "Challenger" else 0.0 for t in self.tick])
        self._chal_fixed = float(sum(float(x) for t, x in self.fixed.items() if self.roles.get(t) == "Challenger"))
        self._fixed_vals = np.array([float(x) for x in self.fixed.values()])
        self.tol = float(inputs.get("objective_tolerance_pp", 0.5)) / 100.0
        self._cache: dict = {}

    # ---------------------------------------------------------------- оценка портфеля
    def evaluate(self, w: np.ndarray, wdp: float, full: bool = False) -> dict:
        """full=False — только Y5 без квантилей (поиск: медиана/ES5/P(loss) на 500k путях ≈ мс); full=True — все горизонты и квантили."""
        key = (tuple(np.round(w, 6)), round(wdp, 6), self.n_search)
        hit = self._cache.get(key)
        if hit is not None and (hit.get("_full") or not full):
            return hit
        out = {}
        for h, rkey, yrs in HORIZONS:
            if not full and h != "Y5":
                continue
            Rm = self.R[rkey] if full else self.R5s
            pv = Rm @ w + wdp * (1.0 + self.rdp) ** yrs + self.fixed_total
            out[h] = _metrics(pv, yrs) if full else _fast_metrics(pv, yrs)
        res = {"horizons": out, "turnover": float(0.5 * (np.abs(w - self.cur).sum() + abs(wdp - self.dp_cur))), "scenario_concentration": None, "_full": full}
        self._cache[key] = res
        return res

    def concentrations(self, w: np.ndarray, wdp: float) -> dict:
        w = np.asarray(w, dtype=float)
        sec = dict(zip(self._sec_ids, (self._S @ w + self._sec_fixed).tolist()))
        allw = np.concatenate([w, self._fixed_vals]) if len(self._fixed_vals) else w
        top3 = float(np.sort(allw)[-3:].sum())
        cc = dict(zip(self._cc_ids, (self._CC @ w + self._cc_fixed).tolist())) if self._cc_ids else {}
        chal = float(self._chal @ w + self._chal_fixed)
        return {"sector": sec, "top3": top3, "common_cause": cc, "challenger_aggregate": chal, "dry_powder": wdp}

    def violations(self, w: np.ndarray, wdp: float, ev: dict | None = None) -> list[dict]:
        """Список нарушений жёстких ограничений: {constraint, value, bound, excess}."""
        V = []
        for t, x, c in zip(self.tick, w, self.cap):
            if x > c + 1e-9:
                V.append({"constraint": f"per_name_cap:{t}", "value": float(x), "bound": float(c), "excess": float(x - c)})
        con = self.concentrations(w, wdp)
        if self.sector_max is not None:
            for s, x in con["sector"].items():
                if x > float(self.sector_max) + 1e-9:
                    V.append({"constraint": f"sector_max:{s}", "value": x, "bound": float(self.sector_max), "excess": x - float(self.sector_max)})
        if self.top3_max is not None and con["top3"] > float(self.top3_max) + 1e-9:
            V.append({"constraint": "top3_aggregate_max", "value": con["top3"], "bound": float(self.top3_max), "excess": con["top3"] - float(self.top3_max)})
        if self.cc_max is not None:
            for c, x in con["common_cause"].items():
                if x > float(self.cc_max) + 1e-9:
                    V.append({"constraint": f"common_cause_max:{c}", "value": x, "bound": float(self.cc_max), "excess": x - float(self.cc_max)})
        if self.ch_agg is not None and con["challenger_aggregate"] > float(self.ch_agg) + 1e-9:
            V.append({"constraint": "Challenger_aggregate_max", "value": con["challenger_aggregate"], "bound": float(self.ch_agg), "excess": con["challenger_aggregate"] - float(self.ch_agg)})
        if wdp < self.dp_min - 1e-9:
            V.append({"constraint": f"dry_powder_min:{self.regime}", "value": float(wdp), "bound": self.dp_min, "excess": float(self.dp_min - wdp)})
        if wdp > self.dp_max + 1e-9:
            V.append({"constraint": f"dry_powder_hard_max:{self.regime}", "value": float(wdp), "bound": self.dp_max, "excess": float(wdp - self.dp_max)})
        ev = ev or self.evaluate(w, wdp); y5 = ev["horizons"]["Y5"]
        if self.p30_max is not None and y5["P_loss_gt_30pct"] > float(self.p30_max) + 1e-9:
            V.append({"constraint": "risk_5y:p_loss_gt_30_max", "value": y5["P_loss_gt_30pct"], "bound": float(self.p30_max), "excess": y5["P_loss_gt_30pct"] - float(self.p30_max)})
        if self.p50_max is not None and y5["P_loss_gt_50pct"] > float(self.p50_max) + 1e-9:
            V.append({"constraint": "risk_5y:p_loss_gt_50_max", "value": y5["P_loss_gt_50pct"], "bound": float(self.p50_max), "excess": y5["P_loss_gt_50pct"] - float(self.p50_max)})
        if self.es5_min is not None and y5["expected_shortfall_5pct"] < float(self.es5_min) - 1e-9:
            V.append({"constraint": "risk_5y:es5_min", "value": y5["expected_shortfall_5pct"], "bound": float(self.es5_min), "excess": float(self.es5_min) - y5["expected_shortfall_5pct"]})
        return V

    def better(self, a: dict, b: dict) -> bool:
        """Лексикографически: a лучше b? (медиана CAGR 5Y с допуском → ES5 → [концентрация сценария] → оборот)."""
        ma, mb = a["horizons"]["Y5"]["median_CAGR"], b["horizons"]["Y5"]["median_CAGR"]
        if ma > mb + self.tol:
            return True
        if mb > ma + self.tol:
            return False
        ea, eb = a["horizons"]["Y5"]["expected_shortfall_5pct"], b["horizons"]["Y5"]["expected_shortfall_5pct"]
        if abs(ea - eb) > 1e-4:
            return ea > eb
        if abs(a["turnover"] - b["turnover"]) > 1e-6:
            return a["turnover"] < b["turnover"]
        return ma > mb


def _snap(x: float, step: float) -> float:
    return round(round(x / step) * step, 6)


def _search(P: _Problem, w0: np.ndarray, wdp0: float, step: float, max_iter: int = 60) -> tuple[np.ndarray, float, int]:
    """Покоординатный подъём переносами веса между парами (бумага↔бумага, бумага↔dry powder) на сетке step."""
    k = len(P.tick)
    w = np.array([_snap(min(max(x, 0.0), P.cap[i]), step) for i, x in enumerate(w0)])
    # нормировка на бюджет: веса бумаг на сетке, dry powder — непрерывный остаток (Σw + dp = budget точно)
    wdp = round(P.budget - w.sum(), 9)
    if wdp < P.dp_min or wdp > P.dp_max:
        target = min(max(wdp, P.dp_min), P.dp_max)
        w = np.array([_snap(x, step) for x in w * (P.budget - target) / max(w.sum(), 1e-12)]) if w.sum() > 0 else w
        wdp = round(P.budget - w.sum(), 9)
    evals = 0

    def feasible(wv, dv):
        return not P.violations(wv, dv)

    best_ev = P.evaluate(w, wdp); best_feas = feasible(w, wdp); evals += 1
    for _ in range(max_iter):
        improved = False
        slots = list(range(k)) + [k]  # k = dry powder
        for i in slots:
            for j in slots:
                if i == j:
                    continue
                for mult in (1, 2, 4):
                    d = step * mult
                    w2, dp2 = w.copy(), wdp
                    if i < k:
                        if w2[i] - d < -1e-9:
                            continue
                        w2[i] = _snap(w2[i] - d, step)
                    else:
                        if dp2 - d < P.dp_min - 1e-9:
                            continue
                        dp2 = round(dp2 - d, 9)
                    if j < k:
                        if w2[j] + d > P.cap[j] + 1e-9:
                            continue
                        w2[j] = _snap(w2[j] + d, step)
                    else:
                        if dp2 + d > P.dp_max + 1e-9:
                            continue
                        dp2 = round(dp2 + d, 9)
                    ev2 = P.evaluate(w2, dp2); evals += 1
                    f2 = feasible(w2, dp2)
                    take = (f2 and not best_feas) or (f2 == best_feas and P.better(ev2, best_ev)) if (f2 or not best_feas) else False
                    if not f2 and not best_feas:  # оба недопустимы — уменьшаем суммарное нарушение
                        take = sum(v["excess"] for v in P.violations(w2, dp2, ev2)) < sum(v["excess"] for v in P.violations(w, wdp, best_ev)) - 1e-9
                    if take:
                        w, wdp, best_ev, best_feas = w2, dp2, ev2, f2; improved = True
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            break
    return w, wdp, evals


def run(inputs: dict, seed: int, data: dict | None = None) -> dict:
    P = _Problem(inputs, data)
    k = len(P.tick)
    starts = inputs.get("starts") or ["current", "equal", "empty"]
    cands = []
    for s in starts:
        if s == "current":
            w0, dp0 = P.cur.copy(), P.dp_cur
        elif s == "given":                                             # тёплый старт от заданных весов (Stability Test: центральное решение)
            gw = inputs.get("start_weights") or {}
            w0, dp0 = np.array([float(gw.get(t, 0.0)) for t in P.tick]), float(inputs.get("start_dry_powder", P.dp_cur))
        elif s == "equal":
            w0, dp0 = np.full(k, (P.budget - P.dp_min) / k), P.dp_min
        else:
            w0, dp0 = np.zeros(k), P.budget
        w, wdp, ne = _search(P, w0, dp0, P.step)
        w, wdp, nf = _search(P, w, wdp, P.fine, max_iter=30)          # локальное уточнение ±0.5 п.п. (§6)
        ev = P.evaluate(w, wdp, full=True); V = P.violations(w, wdp, ev)
        if V and P.n_search < P.n and not any(v["constraint"].startswith(("per_name", "sector", "top3", "common", "Challenger", "dry")) for v in V):
            # риск-ограничения нарушены только на полном наборе путей — досчитать поиск на всех путях
            P.R5s = P.R["r5"]; P.n_search = P.n
            w, wdp, nf2 = _search(P, w, wdp, P.fine, max_iter=30); nf += nf2
            ev = P.evaluate(w, wdp, full=True); V = P.violations(w, wdp, ev)
        cands.append({"start": s, "w": w, "wdp": wdp, "ev": ev, "feasible": not V, "violations": V, "evals": ne + nf})
    feas = [c for c in cands if c["feasible"]]
    if feas:
        best = feas[0]
        for c in feas[1:]:
            if P.better(c["ev"], best["ev"]):
                best = c
    else:
        best = min(cands, key=lambda c: sum(v["excess"] for v in c["violations"]))
    w, wdp, ev = best["w"], best["wdp"], best["ev"]
    con = P.concentrations(w, wdp)
    # допустимые полосы: все допустимые оценённые точки в пределах допуска по медиане от оптимума
    bands = {t: [float(w[i]), float(w[i])] for i, t in enumerate(P.tick)}
    if best["feasible"]:
        m0 = ev["horizons"]["Y5"]["median_CAGR"]
        for key, e in P._cache.items():
            wv = np.array(key[0]); dv = key[1]
            if abs(wv.sum() + dv - P.budget) > 1e-6 or e["horizons"]["Y5"]["median_CAGR"] < m0 - P.tol or (e["horizons"]["Y5"]["median_CAGR"] > m0 + P.tol and e.get("_full")):
                continue
            if P.violations(wv, dv, e):
                continue
            for i, t in enumerate(P.tick):
                bands[t][0] = min(bands[t][0], float(wv[i])); bands[t][1] = max(bands[t][1], float(wv[i]))
    # связывающие ограничения (в пределах 0.5 п.п. от границы)
    binding = []
    for i, t in enumerate(P.tick):
        if P.cap[i] - w[i] <= 0.005 + 1e-9:
            binding.append(f"per_name_cap:{t}")
    if P.sector_max is not None:
        binding += [f"sector_max:{s}" for s, x in con["sector"].items() if float(P.sector_max) - x <= 0.005 + 1e-9]
    if P.top3_max is not None and float(P.top3_max) - con["top3"] <= 0.005 + 1e-9:
        binding.append("top3_aggregate_max")
    if P.cc_max is not None:
        binding += [f"common_cause_max:{c}" for c, x in con["common_cause"].items() if float(P.cc_max) - x <= 0.005 + 1e-9]
    if wdp - P.dp_min <= 0.005 + 1e-9:
        binding.append(f"dry_powder_min:{P.regime}")
    y5 = ev["horizons"]["Y5"]
    if P.p30_max is not None and float(P.p30_max) - y5["P_loss_gt_30pct"] <= 0.01:
        binding.append("risk_5y:p_loss_gt_30_max")
    if P.es5_min is not None and y5["expected_shortfall_5pct"] - float(P.es5_min) <= 0.01:
        binding.append("risk_5y:es5_min")
    # маргинальные кривые по бумаге (MPC-сетка §6): вес бумаги 0..cap шагом grid, остальные — пропорционально, dp фикс.
    curves = {}
    for i, t in enumerate(P.tick):
        pts = []
        others = np.delete(w, i); osum = others.sum()
        for x in np.arange(0.0, P.cap[i] + 1e-9, P.step):
            rest = P.budget - wdp - x
            if rest < -1e-9:
                break
            wv = w.copy(); wv[i] = x
            scale = rest / osum if osum > 0 else 0.0
            wv[np.arange(k) != i] = others * scale
            e = P.evaluate(wv, wdp)
            pts.append({"weight": round(float(x), 4), "median_CAGR_5Y": e["horizons"]["Y5"]["median_CAGR"], "ES5": e["horizons"]["Y5"]["expected_shortfall_5pct"], "feasible": not P.violations(wv, wdp, e)})
        curves[t] = pts
    cur_ev = P.evaluate(P.cur, P.dp_cur, full=True); cur_V = P.violations(P.cur, P.dp_cur, cur_ev)
    proposed = {t: round(float(w[i]), 4) for i, t in enumerate(P.tick)}
    return {"model_version": VERSION, "stage": "A_continuous_target", "paths": P.n, "search_paths": P.n_search, "companies": P.tick, "regime": P.regime,
            "fixed_positions": {"weights": P.fixed, "total": P.fixed_total, "return_assumption": "flat (относительная стоимость 1.0): без калибровок; участвуют в лимитах, не в распределении доходности"},
            "budget_optimizable_plus_dry_powder": P.budget, "objective": {"primary": "median_CAGR_5Y", "tolerance": P.tol, "secondary": ["ES5_5Y", "scenario_concentration (BASE only: n/a)", "turnover"]},
            "feasible": best["feasible"], "start_used": best["start"], "violations_at_optimum": best["violations"],
            "minimum_relaxations": ({v["constraint"]: round(v["excess"], 4) for v in best["violations"]} if not best["feasible"] else {}),
            "proposed_weights": proposed, "dry_powder_weight": round(float(wdp), 4), "dry_powder_preferred_max": P.dp_pref, "dry_powder_above_preferred": bool(wdp > P.dp_pref + 1e-9),
            "per_name_caps": {t: float(c) for t, c in zip(P.tick, P.cap)}, "feasible_weight_bands": {t: [round(b[0], 4), round(b[1], 4)] for t, b in bands.items()},
            "portfolio_return_distribution": {h: {kk: vv for kk, vv in ev["horizons"][h].items() if kk in ("median_CAGR", "P_2x", "CAGR_quantiles")} for h in ("Y3", "Y5", "Y8")},
            "portfolio_downside": {h: {kk: vv for kk, vv in ev["horizons"][h].items() if kk in ("P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct")} for h in ("Y3", "Y5", "Y8")},
            "turnover_from_current": round(ev["turnover"], 4), "scenario_concentration": None,
            "concentrations": con, "binding_constraints": sorted(set(binding)),
            "current_portfolio": {"weights": {t: float(P.cur[i]) for i, t in enumerate(P.tick)}, "dry_powder": P.dp_cur,
                                  "return_distribution_Y5": {kk: vv for kk, vv in cur_ev["horizons"]["Y5"].items() if kk not in ("CAGR_quantiles",)}, "violations": cur_V},
            "constraint_gaps_vs_current": [{**v, "note": "разрыв, не приказ продавать (§3.1)"} for v in cur_V],
            "marginal_curves": curves, "candidates": [{"start": c["start"], "feasible": c["feasible"], "median_CAGR_5Y": c["ev"]["horizons"]["Y5"]["median_CAGR"], "ES5": c["ev"]["horizons"]["Y5"]["expected_shortfall_5pct"], "evals": c["evals"]} for c in cands],
            "execution_projection_by_account": None, "ex_post_initial_hypothesis_comparison": None, "stability_test_ref": None,
            "assumptions": ["позиции без калибровок фиксированы на текущих весах с плоской доходностью", "единственный сценарий BASE — Scenario Concentration не определена",
                            "оборот = Σ|Δw|/2 по оптимизируемым бумагам и dry powder", "стадия B (проекция на счета, лоты, издержки) не выполняется"],
            "decision": "none"}
