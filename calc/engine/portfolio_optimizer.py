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
         "search_paths": 100000, "max_paths": null,
         1.3.0 (Portfolio_Optimizer_Specification v1.1, партия 12, §16/§19): "limits": {..., "theme_policy": {"policy_id": "AI_THEME_NOT_INCREASE_V1",
         "aggregate_id": "AI_TOTAL", "shares": {tk: revenue_share_AI_TOTAL}, "baseline_value": T_baseline, "tolerance": 1e-6, "baseline_status":
         "MATERIALIZED" | "PENDING_HOST_COMPUTE"}} — owner structural constraint T(w) = Σ w_i·share_i ≤ baseline + tolerance (доли — Theme Look-through
         по выручке; fixed/хедж — доля 0, если не задана); жёсткое только при MATERIALIZED, иначе отчётный показатель. Выход по §19: contract_version,
         positions_count, cardinality_variant (из inputs), theme_lookthrough / theme_constraint_status, scenario_concentration_warning /
         scenario_concentration_hard_status.
         1.2.0 (DR-2026-10-02-01/В1, решение владельца 03.10.2026): "limits": {..., "cardinality": {"positions_min": 6, "positions_max": 8,
         "min_position_weight": 0.03, "excludes": ["GLD", "UFO"]}} — число оптимизируемых бумаг с весом > 0 в [min, max] (исключения, fixed и
         dry powder вне счёта), вес позиции либо 0, либо ≥ min_position_weight. Жёсткие структурные ограничения владельца; в поиске —
         дополнительные ходы «закрыть позицию» (весь вес → другой бумаге или dry powder) и «открыть позицию на min_position_weight»,
         потому что покоординатные шаги не могут пересечь запретную зону (0, min). Выход: cardinality {positions_count, min_position_weight,
         zeroed, binding}.
         1.1.0 (DR-2026-09-27-01, решение владельца 30.09.2026; заказ слоя действий v1.2 п. 2.3), 1.1.1 — сверка с Optimizer contract v1.1
         (партия 10: S_cond требует B_s > 0; выход scenario_constraints.gated_at_optimum, contract_version):
         "scenario_constraints": {"p_min": 0.10, "es5_min": -0.40, "p_loss_gt_30_max": 0.25, "scenario_concentration_max": 0.60,
                                  "thresholds": {sid: {"es5_min", "p_loss_gt_30_max"}} (необязательно, поимённо — вариант V3),
                                  "scenarios": [{"id", "probability", "paths_files": {tk: .npz}}] (adverse-сценарии, пути на общих path_id),
                                  "base_paths_files": {tk: .npz} (нужны для ScenarioConcentration: B_s = p_s·max(0, ES5_BASE − ES5_s))},
         "hedge_instruments": {tk: {"max_weight": 0.10, "return_annual": 0.0}} — разрешённые владельцем инструменты хеджа (кэш и GLD, В1/V1):
                              переменная оптимизации с ПЛОСКОЙ доходностью (1+r)^h без калибровки и без отклика на сценарий
                              (model_assumption: движок видит хедж только как не-акционерный балласт, рост золота под шоком не смоделирован);
                              тикер берётся из weights_current (не из fixed_weights).}
         1.4.0 — ГЛОБАЛЬНЫЙ ПОИСК (03.10.2026, после трёх случаев застревания покоординатного подъёма: два бассейна NBIS 23 / CRWV 10.5, оптимум с
         лимитом числа бумаг лучше оптимума без лимита): "search": {"random_starts": 8, "basin_kicks": 6, "exploration_paths": 50000,
         "polish_top": 3}. Фазы: (1) стандартные старты current/equal/empty/given — как раньше, на search_paths; (2) random_starts
         случайных стартов (поддержка 4…8 бумаг или [positions_min, positions_max], веса Дирихле в потолках, dp в [min, preferred]) — локальный
         поиск на первых exploration_paths путях; (3) basin hopping: от лучшей точки basin_kicks «толчков» (перенос случайной доли позиции в
         другую бумагу/dp, закрытие/открытие позиции) + локальный поиск, принимается при улучшении; (4) polish_top лучших различных локальных
         оптимумов дошлифовываются на search_paths, итог — на всех путях. Случайность — только из seed запроса (детерминирована); ходы
         «закрыть/открыть позицию» включены всегда (не только при cardinality). Выход search {distinct_local_optima, candidates, best_source,
         improvement_vs_standard_pp}. random_starts = 0 и basin_kicks = 0 → поведение 1.3.0.
outputs: proposed_weights, dry_powder_weight, feasible_weight_bands, portfolio_return_distribution (3/5/8Y), portfolio_downside,
  sector/common_cause/top3 concentrations, binding_constraints, constraint_gaps_vs_current, marginal_curves (MPC-сетка по бумаге),
  evaluations, infeasible (+ minimum_relaxations), scenario_constraints (метрики портфеля под каждым сценарием на оптимуме и на текущих
  весах, ScenarioConcentration по варианту «а»), hedge_instruments, search, decision: none. Детерминирован при фиксированном seed (1.4.0: seed —
  генератор случайных стартов и толчков).
Сценарно-условные ограничения (1.1.0): для каждого adverse-сценария s с owner-вероятностью p_s ≥ p_min — ES5_5Y(портфель | s) ≥ es5_min и
P(loss>30 %)_5Y(портфель | s) ≤ p_loss_gt_30_max (пороги — owner_judgment); ScenarioConcentration ≤ scenario_concentration_max только при
|A| ≥ 2 (вариант «а» IMMA). Жёсткие, в той же лексикографической схеме §3 (без тихого ослабления); в цели — как тай-брейк после ES5 (§3:
меньшая концентрация), когда она определена. Stability Test при сценарных ограничениях подаёт возмущённые BASE-пути, сценарные пути
берутся из файлов без возмущения (допущение).
"""
from __future__ import annotations

import math

import numpy as np

from engine import portfolio_paths

VERSION = "1.4.0"
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
        self.fixed = {k: float(v) for k, v in (inputs.get("fixed_weights") or {}).items()}
        # инструменты хеджа (1.1.0): переменные с плоской доходностью (1+r)^h — синтетическая константная колонка путей
        self.hedge = {k: {"max_weight": float(v.get("max_weight", 0.0)), "return_annual": float(v.get("return_annual", 0.0))} for k, v in (inputs.get("hedge_instruments") or {}).items()}
        for h_tk in self.hedge:
            if h_tk in self.fixed:
                raise ValueError(f"инструмент хеджа {h_tk} одновременно в fixed_weights — уберите из fixed")
            if h_tk in data:
                raise ValueError(f"инструмент хеджа {h_tk} имеет собственные пути — задайте его как обычную бумагу")
        self.data_tick = list(self.tick)                                # бумаги с путями (без хеджа)
        self.tick = sorted(set(self.tick) | set(self.hedge))
        self.R = {key: np.stack([(data[t][key][:n].astype(np.float64) if t in data else np.full(n, (1.0 + self.hedge[t]["return_annual"]) ** yrs)) for t in self.tick], axis=1) for _, key, yrs in HORIZONS}
        # поиск — на первых search_paths совместных путях (те же path_id у всех компаний), итог и проверка допустимости — на всех
        self.n_search = int(min(n, int(inputs.get("search_paths", 100_000))))
        self.R5s = self.R["r5"][: self.n_search]
        self.meta = {t: data[t]["meta"] for t in self.data_tick}
        cur = {k: float(v) for k, v in (inputs.get("weights_current") or {}).items()}
        # сценарно-условные ограничения (1.1.0): пути adverse-сценариев на общих path_id (Y5), BASE — для бремени B_s / концентрации
        sc_in = inputs.get("scenario_constraints") or {}
        self.sc_cfg = None; self.SR = {}; self.SRs = {}; self.sc_probs = {}; self.sc_applied = []; self.sc_skipped = []; self.BR = None
        if sc_in.get("scenarios"):
            p_min = float(sc_in.get("p_min", 0.0)); thr = sc_in.get("thresholds") or {}
            self.sc_cfg = {"p_min": p_min, "es5_min": sc_in.get("es5_min"), "p_loss_gt_30_max": sc_in.get("p_loss_gt_30_max"),
                           "scenario_concentration_max": sc_in.get("scenario_concentration_max"), "thresholds": {}}
            ref_ids = data[self.data_tick[0]]["path_id"][:n]
            for sc in sc_in["scenarios"]:
                sid = str(sc["id"]); p_s = float(sc["probability"]); sfiles = sc.get("paths_files") or {}
                if sid == "BASE":
                    raise ValueError("scenario_constraints.scenarios: BASE задаётся в base_paths_files")
                self.sc_probs[sid] = p_s
                cols = []
                for t in self.tick:
                    if t in self.hedge:
                        cols.append(np.full(n, (1.0 + self.hedge[t]["return_annual"]) ** 5)); continue
                    if t not in sfiles:
                        raise ValueError(f"сценарий {sid}: нет файла путей для {t}")
                    d = portfolio_paths.load_paths(sfiles[t])
                    if d["meta"].get("global_seed") != ref.get("global_seed") or not np.array_equal(d["path_id"][:n], ref_ids):
                        raise ValueError(f"сценарий {sid}, {t}: пути не выровнены по path_id с базовыми — условное ограничение не считается")
                    cols.append(d["r5"][:n].astype(np.float64))
                self.SR[sid] = np.stack(cols, axis=1); self.SRs[sid] = self.SR[sid][: self.n_search]
                th = thr.get(sid) or {}
                self.sc_cfg["thresholds"][sid] = {"es5_min": th.get("es5_min", self.sc_cfg["es5_min"]), "p_loss_gt_30_max": th.get("p_loss_gt_30_max", self.sc_cfg["p_loss_gt_30_max"])}
                (self.sc_applied if p_s >= p_min - 1e-12 else self.sc_skipped).append(sid)
            bfiles = sc_in.get("base_paths_files") or {}
            self.BR = None
            if bfiles:
                cols = []
                for t in self.tick:
                    if t in self.hedge:
                        cols.append(np.full(n, (1.0 + self.hedge[t]["return_annual"]) ** 5)); continue
                    d = portfolio_paths.load_paths(bfiles[t])
                    if not np.array_equal(d["path_id"][:n], ref_ids):
                        raise ValueError(f"BASE, {t}: пути не выровнены по path_id")
                    cols.append(d["r5"][:n].astype(np.float64))
                self.BR = np.stack(cols, axis=1); self.BRs = self.BR[: self.n_search]
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
        card = L.get("cardinality") or {}                                   # 1.2.0: число бумаг и минимальный вес позиции (owner_judgment)
        self.card_min = int(card["positions_min"]) if card.get("positions_min") is not None else None
        self.card_max = int(card["positions_max"]) if card.get("positions_max") is not None else None
        self.min_pos = float(card["min_position_weight"]) if card.get("min_position_weight") is not None else None
        self.card_excl = set(card.get("excludes") or [])
        self.card_on = any(x is not None for x in (self.card_min, self.card_max, self.min_pos))
        tp = L.get("theme_policy") or {}                                     # 1.3.0: тематическое ограничение владельца (look-through)
        self.theme = None
        if tp.get("shares"):
            self.theme = {"policy_id": tp.get("policy_id"), "aggregate_id": tp.get("aggregate_id"), "shares": {k: float(v) for k, v in tp["shares"].items()},
                          "baseline": (float(tp["baseline_value"]) if tp.get("baseline_value") is not None else None), "tolerance": float(tp.get("tolerance", 1e-6)),
                          "status": str(tp.get("baseline_status") or ("MATERIALIZED" if tp.get("baseline_value") is not None else "PENDING_HOST_COMPUTE"))}
            self.theme["hard"] = self.theme["status"] == "MATERIALIZED" and self.theme["baseline"] is not None
        caps = inputs.get("per_name_caps") or {}
        rng = inputs.get("mpc_range") or {}
        self.wmax_default = float(rng.get("max_weight", 0.20)); self.step = float(rng.get("grid_step", 0.01)); self.fine = float(rng.get("local_refinement_step", 0.005))
        self.roles = inputs.get("roles") or {}
        # потолок бумаги: явный (target_cap Conviction Overlay, может быть выше 20 % для conviction-тега) либо верх MPC-диапазона 0–20 %;
        # Challenger — дополнительно роль-лимит
        self.cap = np.array([min(float(caps[t]) if caps.get(t) is not None else self.wmax_default,
                                 float(self.ch_name) if (self.roles.get(t) == "Challenger" and self.ch_name is not None) else 9.0) for t in self.tick])
        self.cap = np.array([0.0 if self.roles.get(t) == "Watch" else c for t, c in zip(self.tick, self.cap)])
        self.cap = np.array([self.hedge[t]["max_weight"] if t in self.hedge else c for t, c in zip(self.tick, self.cap)])   # потолок хеджа — лимит владельца
        self._card_mask = np.array([t not in self.card_excl and t not in self.hedge for t in self.tick])   # бумаги, идущие в счёт числа позиций
        self._theme_vec = np.array([float((self.theme or {}).get("shares", {}).get(t, 0.0)) for t in self.tick]) if self.theme else None
        self._theme_fixed = float(sum(float(x) * float(self.theme["shares"].get(t, 0.0)) for t, x in self.fixed.items())) if self.theme else 0.0
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
        if self.sc_cfg is not None:
            dp_term = wdp * (1.0 + self.rdp) ** 5 + self.fixed_total
            scen = {}
            for sid in self.SR:
                Rm = self.SR[sid] if full else self.SRs[sid]
                scen[sid] = _fast_metrics(Rm @ w + dp_term, 5)
            res["scenarios"] = scen
            if self.BR is not None:
                base = _fast_metrics((self.BR if full else self.BRs) @ w + dp_term, 5)
                res["base"] = base
                burdens = {sid: self.sc_probs[sid] * max(0.0, base["expected_shortfall_5pct"] - m["expected_shortfall_5pct"]) for sid, m in scen.items()}
                res["scenario_burdens"] = burdens
                res["scenario_concentration"] = portfolio_paths.scenario_concentration(burdens)
        self._cache[key] = res
        return res

    def use_full_paths(self) -> None:
        """Переключить поиск на все совместные пути (после нарушения риск-ограничений только на полном наборе)."""
        self.set_search_paths(self.n)

    def set_search_paths(self, n: int) -> None:
        """1.4.0: поиск на первых n совместных путях (разведка — exploration_paths, шлифовка — search_paths, итог — все)."""
        n = int(min(max(n, 1), self.n)); self.n_search = n
        self.R5s = self.R["r5"][:n]
        self.SRs = {sid: m[:n] for sid, m in self.SR.items()}
        if self.sc_cfg is not None and self.BR is not None:
            self.BRs = self.BR[:n]

    def concentrations(self, w: np.ndarray, wdp: float) -> dict:
        w = np.asarray(w, dtype=float)
        sec = dict(zip(self._sec_ids, (self._S @ w + self._sec_fixed).tolist()))
        allw = np.concatenate([w, self._fixed_vals]) if len(self._fixed_vals) else w
        top3 = float(np.sort(allw)[-3:].sum())
        cc = dict(zip(self._cc_ids, (self._CC @ w + self._cc_fixed).tolist())) if self._cc_ids else {}
        chal = float(self._chal @ w + self._chal_fixed)
        return {"sector": sec, "top3": top3, "common_cause": cc, "challenger_aggregate": chal, "dry_powder": wdp}

    def cardinality(self, w: np.ndarray) -> dict:
        """1.2.0: число счётных бумаг с весом > 0, позиции ниже минимального веса, обнулённые."""
        wm = np.where(self._card_mask, w, 0.0)
        pos = wm > 1e-9
        below = [t for t, x, m in zip(self.tick, w, self._card_mask) if m and 1e-9 < x < (self.min_pos or 0.0) - 1e-9]
        return {"positions_count": int(pos.sum()), "positions_min": self.card_min, "positions_max": self.card_max, "min_position_weight": self.min_pos,
                "below_min": below, "zeroed": [t for t, x, m in zip(self.tick, w, self._card_mask) if m and x <= 1e-9], "excluded_from_count": sorted(self.card_excl | set(self.hedge))}

    def theme_value(self, w: np.ndarray) -> float | None:
        """1.3.0: T_theme(w) = Σ w_i·share_i (+ фиксированные позиции с заданной долей)."""
        if self.theme is None:
            return None
        return float(np.dot(self._theme_vec, w) + self._theme_fixed)

    def violations(self, w: np.ndarray, wdp: float, ev: dict | None = None) -> list[dict]:
        """Список нарушений жёстких ограничений: {constraint, value, bound, excess}."""
        V = []
        if self.theme is not None and self.theme["hard"]:
            tv = self.theme_value(w); bound = self.theme["baseline"] + self.theme["tolerance"]
            if tv > bound + 1e-12:
                V.append({"constraint": f"theme_policy:{self.theme['aggregate_id']}", "value": tv, "bound": bound, "excess": float(tv - bound)})
        if self.card_on:                                                 # 1.2.0: избыток — в единицах веса, чтобы поиск в недопустимой зоне имел градиент
            cd = self.cardinality(w); n = cd["positions_count"]
            wm = np.sort(np.where(self._card_mask, w, 0.0)[np.where(self._card_mask, w, 0.0) > 1e-9])
            if self.card_max is not None and n > self.card_max:
                V.append({"constraint": "cardinality:positions_max", "value": n, "bound": self.card_max, "excess": float(wm[: n - self.card_max].sum())})
            if self.card_min is not None and n < self.card_min:
                V.append({"constraint": "cardinality:positions_min", "value": n, "bound": self.card_min, "excess": float((self.card_min - n) * (self.min_pos or 0.01))})
            for t in cd["below_min"]:
                x = float(w[self.tick.index(t)])
                V.append({"constraint": f"min_position_weight:{t}", "value": x, "bound": self.min_pos, "excess": float(self.min_pos - x)})
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
        # сценарно-условные (1.1.0): только сценарии с p_s ≥ p_min; концентрация — только при |A| ≥ 2 (вариант «а»);
        # 1.1.1 (Optimizer contract v1.1, партия 10): S_cond дополнительно требует B_s > 0 — сценарий, не ухудшающий ES5 портфеля
        # против BASE, гейтом не является (проверяется на каждой точке; без base_paths_files — гейт для всех p_s ≥ p_min, консервативно)
        if self.sc_cfg is not None:
            for sid in self.sc_applied:
                m = ev["scenarios"][sid]; th = self.sc_cfg["thresholds"][sid]
                if ev.get("base") is not None and m["expected_shortfall_5pct"] >= ev["base"]["expected_shortfall_5pct"] - 1e-12:
                    continue                                                    # B_s = 0 → не adverse для этого портфеля
                if th["es5_min"] is not None and m["expected_shortfall_5pct"] < float(th["es5_min"]) - 1e-9:
                    V.append({"constraint": f"scenario:{sid}:es5_min", "value": m["expected_shortfall_5pct"], "bound": float(th["es5_min"]), "excess": float(th["es5_min"]) - m["expected_shortfall_5pct"]})
                if th["p_loss_gt_30_max"] is not None and m["P_loss_gt_30pct"] > float(th["p_loss_gt_30_max"]) + 1e-9:
                    V.append({"constraint": f"scenario:{sid}:p_loss_gt_30_max", "value": m["P_loss_gt_30pct"], "bound": float(th["p_loss_gt_30_max"]), "excess": m["P_loss_gt_30pct"] - float(th["p_loss_gt_30_max"])})
            cmax = self.sc_cfg["scenario_concentration_max"]; sc = ev.get("scenario_concentration")
            if cmax is not None and sc and sc.get("applicable") and sc["value"] > float(cmax) + 1e-9:
                V.append({"constraint": "scenario_concentration_max", "value": sc["value"], "bound": float(cmax), "excess": sc["value"] - float(cmax)})
        return V

    def better(self, a: dict, b: dict) -> bool:
        """Лексикографически: a лучше b? (медиана CAGR 5Y с допуском → ES5 → [концентрация сценария, если определена] → оборот)."""
        ma, mb = a["horizons"]["Y5"]["median_CAGR"], b["horizons"]["Y5"]["median_CAGR"]
        if ma > mb + self.tol:
            return True
        if mb > ma + self.tol:
            return False
        ea, eb = a["horizons"]["Y5"]["expected_shortfall_5pct"], b["horizons"]["Y5"]["expected_shortfall_5pct"]
        if abs(ea - eb) > 1e-4:
            return ea > eb
        ca, cb = a.get("scenario_concentration") or {}, b.get("scenario_concentration") or {}
        if ca.get("applicable") and cb.get("applicable") and abs(ca["value"] - cb["value"]) > 1e-4:
            return ca["value"] < cb["value"]
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
        w = np.minimum(w, P.cap)                                     # масштабирование не должно выводить бумагу за потолок (1.1.0)
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
            # 1.2.0: ходы через запретную зону (0, min_position_weight): закрыть позицию целиком / открыть на минимальном весе;
            # 1.4.0: включены всегда (без лимита числа бумаг min = шаг сетки) — покоординатные шаги не закрывают символические позиции
            cand_moves = []
            for i in range(k):
                if P.card_on and not P._card_mask[i]:
                    continue
                if w[i] > 1e-9:
                    for j in slots:
                        if j == i:
                            continue
                        w2, dp2 = w.copy(), wdp; amt = w2[i]; w2[i] = 0.0
                        if j < k:
                            if w2[j] + amt > P.cap[j] + 1e-9:
                                continue
                            w2[j] = _snap(w2[j] + amt, step)
                        else:
                            if dp2 + amt > P.dp_max + 1e-9:
                                continue
                            dp2 = round(dp2 + amt, 9)
                        cand_moves.append((w2, round(P.budget - w2.sum(), 9) if j < k else dp2))
                else:
                    open_w = P.min_pos if P.min_pos is not None else max(step, 0.01)
                    if P.cap[i] < open_w - 1e-9:
                        continue
                    for j in slots:
                        if j == i:
                            continue
                        w2, dp2 = w.copy(), wdp; w2[i] = _snap(open_w, step)
                        if j < k:
                            if w2[j] - open_w < -1e-9 or (P.min_pos is not None and P._card_mask[j] and 1e-9 < w2[j] - open_w < P.min_pos - 1e-9):
                                continue
                            w2[j] = _snap(w2[j] - open_w, step)
                        else:
                            if dp2 - open_w < P.dp_min - 1e-9:
                                continue
                            dp2 = round(dp2 - open_w, 9)
                        cand_moves.append((w2, round(P.budget - w2.sum(), 9) if j < k else dp2))
            for w2, dp2 in cand_moves:
                if abs(w2.sum() + dp2 - P.budget) > 1e-6 or dp2 < P.dp_min - 1e-9 or dp2 > P.dp_max + 1e-9:
                    continue
                ev2 = P.evaluate(w2, dp2); evals += 1
                f2 = feasible(w2, dp2)
                take = (f2 and not best_feas) or (f2 == best_feas and P.better(ev2, best_ev)) if (f2 or not best_feas) else False
                if not f2 and not best_feas:
                    take = sum(v["excess"] for v in P.violations(w2, dp2, ev2)) < sum(v["excess"] for v in P.violations(w, wdp, best_ev)) - 1e-9
                if take:
                    w, wdp, best_ev, best_feas = w2, dp2, ev2, f2; improved = True
                    break
        if not improved:
            break
    return w, wdp, evals


def run(inputs: dict, seed: int, data: dict | None = None) -> dict:
    P = _Problem(inputs, data)
    k = len(P.tick)
    starts = inputs.get("starts") or ["current", "equal", "empty"]
    scfg = {"random_starts": 8, "basin_kicks": 6, "exploration_paths": 50_000, "polish_top": 3, **(inputs.get("search") or {})}
    rng = np.random.default_rng(np.random.SeedSequence([int(seed) & 0xFFFFFFFF, 0x5EA7C4]))
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
            # риск-ограничения (в т. ч. сценарные) нарушены только на полном наборе путей — досчитать поиск на всех путях
            P.use_full_paths()
            w, wdp, nf2 = _search(P, w, wdp, P.fine, max_iter=30); nf += nf2
            ev = P.evaluate(w, wdp, full=True); V = P.violations(w, wdp, ev)
        cands.append({"start": s, "w": w, "wdp": wdp, "ev": ev, "feasible": not V, "violations": V, "evals": ne + nf})
    n_std = len(cands)
    # --- 1.4.0: глобальный поиск — случайные старты и basin hopping на разведочной выборке, шлифовка лучших на search_paths
    n_rand, n_kick = int(scfg["random_starts"]), int(scfg["basin_kicks"])
    search_block = {"random_starts": n_rand, "basin_kicks": n_kick, "exploration_paths": None, "polish_top": int(scfg["polish_top"]), "standard_starts": list(starts)}
    if n_rand > 0 or n_kick > 0:
        n_full_search = P.n_search
        n_expl = int(min(P.n_search, int(scfg["exploration_paths"])))
        search_block["exploration_paths"] = n_expl
        P.set_search_paths(n_expl)

        def local(w0, dp0):
            w1, dp1, e1 = _search(P, w0, dp0, P.step); w1, dp1, e2 = _search(P, w1, dp1, P.fine, max_iter=30)
            ev1 = P.evaluate(w1, dp1); V1 = P.violations(w1, dp1, ev1)
            return {"w": w1, "wdp": dp1, "ev": ev1, "feasible": not V1, "violations": V1, "evals": e1 + e2}

        def key_of(c):
            return (tuple(np.round(c["w"], 3)), round(c["wdp"], 3))

        def is_better(a, b):
            if a["feasible"] != b["feasible"]:
                return a["feasible"]
            if not a["feasible"]:
                return sum(v["excess"] for v in a["violations"]) < sum(v["excess"] for v in b["violations"]) - 1e-9
            return P.better(a["ev"], b["ev"])

        expl = []
        lo = P.card_min if P.card_min is not None else min(4, k); hi = P.card_max if P.card_max is not None else min(8, k)
        lo, hi = max(1, min(lo, k)), max(1, min(hi, k)); lo = min(lo, hi)
        idx_all = [i for i in range(k) if P.cap[i] > 1e-9 and (not P.card_on or P._card_mask[i])]
        for r in range(n_rand):
            m = int(rng.integers(lo, hi + 1)); m = min(m, len(idx_all))
            probs = np.array([P.cap[i] for i in idx_all]); probs = probs / probs.sum()
            sup = rng.choice(idx_all, size=m, replace=False, p=probs) if m < len(idx_all) else np.array(idx_all)
            dp0 = float(rng.uniform(P.dp_min, max(P.dp_min, P.dp_pref)))
            w0 = np.zeros(k); raw = rng.dirichlet(np.ones(m)) * (P.budget - dp0)
            w0[sup] = np.minimum(raw, P.cap[sup])
            if P.min_pos is not None:
                w0[sup] = np.maximum(w0[sup], P.min_pos)
            c = local(w0, dp0); c["start"] = f"random:{r}"; expl.append(c)
        pool = cands + expl
        best_e = pool[0]
        for c in pool[1:]:
            if is_better(c, best_e):
                best_e = c
        for kk in range(n_kick):
            w0, dp0 = best_e["w"].copy(), best_e["wdp"]
            held = [i for i in range(k) if w0[i] > 1e-9]
            if not held:
                break
            mode = rng.integers(0, 3)
            i = int(rng.choice(held))
            if mode == 0:                                                      # перенос случайной доли позиции в другую бумагу
                j = int(rng.choice([x for x in idx_all if x != i])) if len(idx_all) > 1 else i
                amt = float(w0[i] * rng.uniform(0.25, 1.0)); amt = min(amt, max(0.0, P.cap[j] - w0[j]))
                w0[i] -= amt; w0[j] += amt
            elif mode == 1:                                                    # закрыть позицию в dry powder / открыть другую
                amt = float(w0[i]); w0[i] = 0.0
                room = max(0.0, P.dp_max - dp0); to_dp = min(amt, room); dp0 += to_dp; rest = amt - to_dp
                if rest > 1e-9:
                    cands_j = [x for x in idx_all if x != i and P.cap[x] - w0[x] > 1e-9]
                    if cands_j:
                        j = int(rng.choice(cands_j)); w0[j] += min(rest, P.cap[j] - w0[j])
            else:                                                              # открыть незанятую бумагу за счёт держателя
                free = [x for x in idx_all if w0[x] <= 1e-9]
                if free:
                    j = int(rng.choice(free)); amt = float(min(w0[i] * rng.uniform(0.3, 0.7), P.cap[j]))
                    w0[i] -= amt; w0[j] += amt
            dp0 = round(P.budget - w0.sum(), 9)
            c = local(w0, dp0); c["start"] = f"kick:{kk}"; expl.append(c)
            if is_better(c, best_e):
                best_e = c
        # шлифовка лучших различных локальных оптимумов на полной поисковой выборке
        P.set_search_paths(n_full_search)
        seen = set(); ranked = sorted(pool + expl, key=lambda c: (not c["feasible"], -(c["ev"]["horizons"]["Y5"]["median_CAGR"]) if c["feasible"] else sum(v["excess"] for v in c["violations"])))
        polished = []
        for c in ranked:
            kk_ = key_of(c)
            if kk_ in seen:
                continue
            seen.add(kk_)
            if c["start"] in starts:
                continue                                                       # стандартные старты уже посчитаны на search_paths
            w1, dp1, e2 = _search(P, c["w"], c["wdp"], P.fine, max_iter=30)
            ev1 = P.evaluate(w1, dp1, full=True); V1 = P.violations(w1, dp1, ev1)
            polished.append({"start": c["start"], "w": w1, "wdp": dp1, "ev": ev1, "feasible": not V1, "violations": V1, "evals": c["evals"] + e2})
            if len(polished) >= int(scfg["polish_top"]):
                break
        cands += polished
        search_block["distinct_local_optima"] = len({key_of(c) for c in pool + expl})
        search_block["exploration_candidates"] = [{"start": c["start"], "feasible": c["feasible"], "median_CAGR_5Y": c["ev"]["horizons"]["Y5"]["median_CAGR"], "ES5": c["ev"]["horizons"]["Y5"]["expected_shortfall_5pct"]} for c in expl]
    feas = [c for c in cands if c["feasible"]]
    if feas:
        best = feas[0]
        for c in feas[1:]:
            if P.better(c["ev"], best["ev"]):
                best = c
    else:
        best = min(cands, key=lambda c: sum(v["excess"] for v in c["violations"]))
    w, wdp, ev = best["w"], best["wdp"], best["ev"]
    std_best = None
    for c in cands[:n_std]:
        if c["feasible"] and (std_best is None or P.better(c["ev"], std_best["ev"])):
            std_best = c
    search_block["best_source"] = best["start"]
    search_block["improvement_vs_standard_pp"] = (round(100 * (ev["horizons"]["Y5"]["median_CAGR"] - std_best["ev"]["horizons"]["Y5"]["median_CAGR"]), 3) if std_best and best["feasible"] else None)
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
    card_block = None
    if P.card_on:
        card_block = P.cardinality(w)
        if P.card_max is not None and card_block["positions_count"] >= P.card_max:
            binding.append("cardinality:positions_max")
        if P.card_min is not None and card_block["positions_count"] <= P.card_min:
            binding.append("cardinality:positions_min")
        if P.min_pos is not None:
            binding += [f"min_position_weight:{t}" for t, x, m in zip(P.tick, w, P._card_mask) if m and abs(x - P.min_pos) <= 0.005 + 1e-9]
        card_block["binding"] = sorted(b for b in binding if b.startswith(("cardinality", "min_position_weight")))
    theme_block = None
    if P.theme is not None:
        tv = P.theme_value(w); tc = P.theme_value(P.cur); bound = (P.theme["baseline"] + P.theme["tolerance"]) if P.theme["baseline"] is not None else None
        if P.theme["hard"] and bound is not None and bound - tv <= 0.005 + 1e-9:
            binding.append(f"theme_policy:{P.theme['aggregate_id']}")
        theme_block = {"policy_id": P.theme["policy_id"], "aggregate_id": P.theme["aggregate_id"], "binding_basis": "revenue", "value_at_optimum": tv, "value_at_current": tc,
                       "baseline_value": P.theme["baseline"], "baseline_status": P.theme["status"], "tolerance": P.theme["tolerance"],
                       "status": ("not_enforced_pending_baseline" if not P.theme["hard"] else ("pass" if tv <= bound + 1e-12 else "violated")),
                       "binding": f"theme_policy:{P.theme['aggregate_id']}" in binding}
    y5 = ev["horizons"]["Y5"]
    if P.p30_max is not None and float(P.p30_max) - y5["P_loss_gt_30pct"] <= 0.01:
        binding.append("risk_5y:p_loss_gt_30_max")
    if P.es5_min is not None and y5["expected_shortfall_5pct"] - float(P.es5_min) <= 0.01:
        binding.append("risk_5y:es5_min")
    sc_block = None
    if P.sc_cfg is not None:
        for sid in P.sc_applied:
            m = ev["scenarios"][sid]; th = P.sc_cfg["thresholds"][sid]
            if ev.get("base") is not None and m["expected_shortfall_5pct"] >= ev["base"]["expected_shortfall_5pct"] - 1e-12:
                continue
            if th["es5_min"] is not None and m["expected_shortfall_5pct"] - float(th["es5_min"]) <= 0.01:
                binding.append(f"scenario:{sid}:es5_min")
            if th["p_loss_gt_30_max"] is not None and float(th["p_loss_gt_30_max"]) - m["P_loss_gt_30pct"] <= 0.01:
                binding.append(f"scenario:{sid}:p_loss_gt_30_max")
        scc = ev.get("scenario_concentration")
        if scc and scc.get("applicable") and P.sc_cfg["scenario_concentration_max"] is not None and float(P.sc_cfg["scenario_concentration_max"]) - scc["value"] <= 0.01:
            binding.append("scenario_concentration_max")
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
    if P.sc_cfg is not None:
        pick = lambda m: {kk: m[kk] for kk in ("median_CAGR", "P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct")}  # noqa: E731
        sc_block = {"rule": "Optimizer contract v1.1 (партия 10): S_cond = {s ≠ BASE | p_s ≥ p_min, B_s > 0}; для s ∈ S_cond: ES5_5Y(портфель | s) ≥ es5_min и P(loss>30 %)_5Y(портфель | s) ≤ p_loss_gt_30_max; ScenarioConcentration ≤ max только при ≥ 2 положительных бременах (в бремя входят все non-BASE с известной вероятностью, в т. ч. p_s < p_min); пороги — owner_judgment (DR-2026-09-27-01)", "contract_version": "1.1",
                    "gated_at_optimum": [sid for sid in sorted(P.sc_applied) if ev.get("base") is None or ev["scenarios"][sid]["expected_shortfall_5pct"] < ev["base"]["expected_shortfall_5pct"] - 1e-12],
                    "config": {**P.sc_cfg, "probabilities": P.sc_probs}, "applied_scenarios": sorted(P.sc_applied), "skipped_below_p_min": sorted(P.sc_skipped),
                    "at_optimum": {"by_scenario": {sid: pick(m) for sid, m in ev["scenarios"].items()}, "base": (pick(ev["base"]) if ev.get("base") else None),
                                   "burdens_B": ev.get("scenario_burdens"), "scenario_concentration": ev.get("scenario_concentration")},
                    "at_current": {"by_scenario": {sid: pick(m) for sid, m in cur_ev["scenarios"].items()}, "base": (pick(cur_ev["base"]) if cur_ev.get("base") else None),
                                   "burdens_B": cur_ev.get("scenario_burdens"), "scenario_concentration": cur_ev.get("scenario_concentration")},
                    "note": "метрики под сценарием — на scenario-specific путях с общими path_id (probability = 1 для сценария, §21 v1.1); хедж и fixed — плоская доходность"}
    hedge_block = ({t: {**cfg, "current_weight": float(P.cur[P.tick.index(t)]), "proposed_weight": proposed[t],
                        "return_assumption": "flat (1+r)^h, без калибровки и без отклика на сценарий — model_assumption"} for t, cfg in P.hedge.items()} if P.hedge else None)
    return {"model_version": VERSION, "stage": "A_continuous_target", "paths": P.n, "search_paths": P.n_search, "companies": P.tick, "regime": P.regime,
            "scenario_constraints": sc_block, "hedge_instruments": hedge_block, "cardinality": card_block, "search": search_block,
            "contract_version": "1.1", "positions_count": (card_block or {}).get("positions_count", int(sum(1 for i, t in enumerate(P.tick) if w[i] > 1e-9 and t not in P.hedge))),
            "cardinality_variant": inputs.get("cardinality_variant"), "min_position_weight": P.min_pos,
            "theme_lookthrough": theme_block, "theme_constraint_status": (theme_block or {}).get("status"),
            "scenario_conditional_gates": (sc_block or {}).get("gated_at_optimum"),
            "scenario_concentration_warning": bool(((ev.get("scenario_concentration") or {}).get("value") or 0.0) >= float(((inputs.get("scenario_constraints") or {}).get("scenario_concentration_warning") or 0.60))) if ev.get("scenario_concentration") and (ev.get("scenario_concentration") or {}).get("applicable") else None,
            "scenario_concentration_hard_status": (("breach" if (P.sc_cfg or {}).get("scenario_concentration_max") is not None and ((ev.get("scenario_concentration") or {}).get("value") or 0.0) > float(P.sc_cfg["scenario_concentration_max"]) else "pass") if ev.get("scenario_concentration") and (ev.get("scenario_concentration") or {}).get("applicable") else "not_applicable"),
            "fixed_positions": {"weights": P.fixed, "total": P.fixed_total, "return_assumption": "flat (относительная стоимость 1.0): без калибровок; участвуют в лимитах, не в распределении доходности"},
            "budget_optimizable_plus_dry_powder": P.budget, "objective": {"primary": "median_CAGR_5Y", "tolerance": P.tol, "secondary": ["ES5_5Y", ("scenario_concentration (вариант «а», при |A| ≥ 2)" if P.sc_cfg is not None and P.BR is not None else "scenario_concentration (BASE only: n/a)"), "turnover"]},
            "feasible": best["feasible"], "start_used": best["start"], "violations_at_optimum": best["violations"],
            "minimum_relaxations": ({v["constraint"]: round(v["excess"], 4) for v in best["violations"]} if not best["feasible"] else {}),
            "proposed_weights": proposed, "dry_powder_weight": round(float(wdp), 4), "dry_powder_preferred_max": P.dp_pref, "dry_powder_above_preferred": bool(wdp > P.dp_pref + 1e-9),
            "per_name_caps": {t: float(c) for t, c in zip(P.tick, P.cap)}, "feasible_weight_bands": {t: [round(b[0], 4), round(b[1], 4)] for t, b in bands.items()},
            "portfolio_return_distribution": {h: {kk: vv for kk, vv in ev["horizons"][h].items() if kk in ("median_CAGR", "P_2x", "CAGR_quantiles")} for h in ("Y3", "Y5", "Y8")},
            "portfolio_downside": {h: {kk: vv for kk, vv in ev["horizons"][h].items() if kk in ("P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct")} for h in ("Y3", "Y5", "Y8")},
            "turnover_from_current": round(ev["turnover"], 4), "scenario_concentration": ev.get("scenario_concentration"),
            "concentrations": con, "binding_constraints": sorted(set(binding)),
            "current_portfolio": {"weights": {t: float(P.cur[i]) for i, t in enumerate(P.tick)}, "dry_powder": P.dp_cur,
                                  "return_distribution_Y5": {kk: vv for kk, vv in cur_ev["horizons"]["Y5"].items() if kk not in ("CAGR_quantiles",)}, "violations": cur_V},
            "constraint_gaps_vs_current": [{**v, "note": "разрыв, не приказ продавать (§3.1)"} for v in cur_V],
            "marginal_curves": curves, "candidates": [{"start": c["start"], "feasible": c["feasible"], "median_CAGR_5Y": c["ev"]["horizons"]["Y5"]["median_CAGR"], "ES5": c["ev"]["horizons"]["Y5"]["expected_shortfall_5pct"], "evals": c["evals"]} for c in cands],
            "execution_projection_by_account": None, "ex_post_initial_hypothesis_comparison": None, "stability_test_ref": None,
            "assumptions": ["позиции без калибровок фиксированы на текущих весах с плоской доходностью", ("сценарные ограничения на scenario-specific путях; хедж — плоская доходность без отклика на сценарий" if P.sc_cfg is not None else "единственный сценарий BASE — Scenario Concentration не определена"),
                            "оборот = Σ|Δw|/2 по оптимизируемым бумагам и dry powder", "стадия B (проекция на счета, лоты, издержки) не выполняется"],
            "decision": "none"}
