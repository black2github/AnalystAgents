"""Обобщённый условный Монте-Карло компании v2: архетипы mature_positive_margin и capital_intensive_transition, сегменты и
форма маржи из калибровки, латентные факторы вместо общего ранга, кусочная оценка с fallback и valuation_basis, gap-метрики
RV↔MC, robustness v1.1 (срез 1); Joint Simulation Layer + driver_parameter_mapping, knockout / adverse_driver_stress (срез 2).
См. calc/docs/company_mc_v2_design.md.

inputs: {"calibration": <dict v2 | SPCX v1.0 (авто-адаптер)>, "equity_value_0": float, "paths": int|None, "chunk": 50000,
         "convergence_check": bool, "robustness": bool, "robustness_paths": int,
         "joint_layer_spec": <dict Joint_Simulation_Layer_Schema> (нужен при driver_parameter_mapping),
         "global_seed": int (общий для всех компаний в совместном прогоне; по умолчанию = seed калибровки),
         "scenario": {"id", "driver_overrides": {DRIVER: {"mean_shift_sigma", "volatility_multiplier"}}} (BASE, если нет),
         "knockout": [driver_id], "adverse_driver_stress": [driver_id],
         "store_paths": bool — записать относительные стоимости по путям в <_runs_dir>/<_run_id>-paths.npz (срез 4; для
         portfolio_paths / MPC / Optimizer); "_run_id", "_runs_dir" подставляет сайдкар}
Интерпретация движка (срез 2): эффект драйвера на параметр — сглаженный шок (lag + half-life, в сигмах); для роста —
по кварталам, для узлов маржи/мультипликаторов — значение сглаженного шока в квартале горизонта (Y3→q12, Y5→q20, Y8→q32).
Целевые пути mapping, которых движок не знает (например capacity_model.*), попадают в mapping_warnings и не применяются.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np
from scipy.special import ndtr
from scipy.stats import beta as _beta, norm as _norm

from engine import joint_layer, milestone_mc

VERSION = "2.3.0"
SPEC_VERSION = "MC_Calibration_Archetypes_v1.0+Rules_v1.1+Joint_Simulation_Layer_v1.0"
QUARTERS = 32
ARCHETYPES = ("mature_positive_margin", "capital_intensive_transition", "pre_service_or_milestone_driven")
FACTORS = ("growth", "margin", "valuation")
HORIZON_Q = {"Y3": 11, "Y5": 19, "Y8": 31}


# ---------------------------------------------------------------- распределения (ppf от u∈[0,1])
def dist_ppf(u, d: dict, shift: float = 0.0, scale: float = 1.0):
    """Квантиль распределения из калибровки. shift — аддитивный сдвиг параметров положения, scale — множитель."""
    kind = (d.get("distribution") or "triangular").lower()
    u = np.clip(u, 1e-9, 1 - 1e-9)
    if kind == "deterministic":
        return np.full_like(u, float(d["value"]) * scale + shift, dtype=float)
    if kind == "triangular":
        lo, mode, hi = (float(d["min"]) * scale + shift, float(d["mode"]) * scale + shift, float(d["max"]) * scale + shift)
        if not (lo <= mode <= hi):
            raise ValueError(f"triangular: требуется min <= mode <= max, получено {lo}, {mode}, {hi}")
        if hi == lo:
            return np.full_like(u, lo, dtype=float)
        fc = (mode - lo) / (hi - lo)
        left = lo + np.sqrt(u * (hi - lo) * (mode - lo))
        right = hi - np.sqrt((1 - u) * (hi - lo) * (hi - mode))
        return np.where(u < fc, left, right)
    if kind in ("pert", "beta_pert"):
        lo, mode, hi = (float(d["min"]) * scale + shift, float(d["mode"]) * scale + shift, float(d["max"]) * scale + shift)
        lam = float(d.get("lambda", 4.0))
        if hi == lo:
            return np.full_like(u, lo, dtype=float)
        a = 1 + lam * (mode - lo) / (hi - lo); b = 1 + lam * (hi - mode) / (hi - lo)
        return lo + (hi - lo) * _beta.ppf(u, a, b)
    if kind == "truncated_normal":
        mu, sd = float(d["mean"]) * scale + shift, float(d["sd"]) * scale
        lo = float(d.get("min", -np.inf)); hi = float(d.get("max", np.inf))
        lo = lo * scale + shift if np.isfinite(lo) else lo; hi = hi * scale + shift if np.isfinite(hi) else hi
        a, b = _norm.cdf(lo, mu, sd), _norm.cdf(hi, mu, sd)
        return _norm.ppf(a + u * (b - a), mu, sd)
    if kind == "lognormal":
        return float(d["median"]) * scale * np.exp(float(d["sigma"]) * _norm.ppf(u)) + shift
    raise ValueError(f"неизвестное распределение: {kind}")


# ---------------------------------------------------------------- адаптер SPCX v1.0 → v2
def from_spcx_v1(cal: dict) -> dict:
    """Калибровка SPCX_Conditional_Monte_Carlo_Calibration_v1.0 → схема v2 (архетип B, direct_fcf_nodes)."""
    facts = cal["source_facts"]["q2_2026"]
    segs = {}
    for name, seg in cal["revenue_model"]["segments"].items():
        segs[name] = {"base_revenue_quarterly": float(facts[f"{name}_revenue_b"]["value"]) * 1e9,
                      "initial_growth": seg["annual_growth_initial"], "long_run_growth_y8": seg["long_run_growth_y8"],
                      "growth_half_life_years": seg["mean_reversion_half_life_years"]}
    mm = cal["margin_model"]["nodes"]; tm = cal["terminal_multiple"]
    rc = (cal.get("dependencies") or {}).get("rank_correlations") or {}
    def rho(k):
        v = rc.get(k); return float(v["rho"] if isinstance(v, dict) else (v or 0.0))
    gm = float(np.mean([rho("AI_growth__margin_improvement"), rho("Connectivity_growth__margin_improvement"), rho("Space_growth__margin_improvement")]))
    return {
        "ticker": cal.get("ticker"), "archetype": "capital_intensive_transition", "adapted_from": "SPCX_Conditional_Monte_Carlo_Calibration_v1.0",
        "state_vector": cal.get("state_vector"), "simulation": cal["simulation"],
        "revenue_model": {"segments": segs},
        "margin_model": {"method": "direct_fcf_nodes", "monotonic": True,
                         "nodes": {"Y1": mm["Y1"], "Y2": mm["Y2"], "Y3": mm["Y3"], "Y4_terminal_fraction": mm["Y4_terminal_fraction"],
                                   "Y5_terminal_margin": mm["Y5_terminal_margin"],
                                   "Y8_terminal_margin": {"rule": "y5_plus_normal", "sigma": 0.03, "min": 0.15, "max": 0.40}}},
        "valuation": {"Y3": {"basis": "revenue_bridge", "multiple": tm["Y3"]}, "Y5": {"basis": "FCF_multiple", "multiple": tm["Y5"]},
                      "Y8": {"basis": "FCF_multiple", "multiple": tm["Y8"]}, "negative_fcf_fallback": {"basis": "revenue_bridge", "multiple": tm["Y3"]}},
        "dependencies": {"latent_factors": list(FACTORS), "default_loading": 0.7,
                         "factor_correlations": {"growth__margin": gm, "growth__valuation": 0.0, "margin__valuation": rho("terminal_margin__terminal_multiple")}},
        "market_path_model": cal.get("market_path_model") or {}, "robustness_tests": cal.get("robustness_tests") or {},
        "reverse_valuation_ref": cal.get("reverse_valuation_ref"),
        "joint_simulation": cal.get("joint_simulation"), "driver_parameter_mapping": cal.get("driver_parameter_mapping"),
    }


def _normalize(cal: dict) -> dict:
    if "archetype" not in cal and "terminal_multiple" in cal and "source_facts" in cal:
        return from_spcx_v1(cal)
    if cal.get("archetype") not in ARCHETYPES:
        raise ValueError(f"archetype должен быть одним из {ARCHETYPES}")
    if cal["archetype"] == "pre_service_or_milestone_driven":
        for k in ("milestone_model", "cash_model", "valuation"):
            if k not in cal:
                raise ValueError(f"архетип C: нужна секция {k}")
        if "service_onset_milestone" not in cal["milestone_model"]:
            raise ValueError("архетип C: milestone_model.service_onset_milestone обязателен")
    return cal


# ---------------------------------------------------------------- латентные факторы
def _factor_corr(dep: dict, rho_shift: float = 0.0):
    fc = dep.get("factor_correlations") or {}
    C = np.eye(3)
    for key, val in fc.items():
        a, b = key.split("__")
        if a in FACTORS and b in FACTORS:
            r = float(val["rho"] if isinstance(val, dict) else val); r = max(-0.95, min(0.95, r + rho_shift))
            C[FACTORS.index(a), FACTORS.index(b)] = C[FACTORS.index(b), FACTORS.index(a)] = r
    w, V = np.linalg.eigh(C); fixed = False
    if w.min() < -1e-10:
        w = np.clip(w, 1e-8, None); C = V @ np.diag(w) @ V.T; d = np.sqrt(np.diag(C)); C = C / np.outer(d, d); fixed = True
    return C, fixed


class _Draw:
    """Параметр = loading × общий фактор + sqrt(1−loading²) × собственный шок → u = Φ(z)."""

    def __init__(self, rng, n, F, default_loading):
        self.rng, self.n, self.F, self.l0 = rng, n, F, float(default_loading)

    def u(self, factor: str, loading=None):
        l = self.l0 if loading is None else float(loading); l = max(0.0, min(0.999, l))
        z = l * self.F[:, FACTORS.index(factor)] + math.sqrt(1 - l * l) * self.rng.standard_normal(self.n)
        return ndtr(z)


# ---------------------------------------------------------------- driver_parameter_mapping (срез 2)
def _apply_knockout(cal: dict, knockout: list[str]) -> list[str]:
    """Снятие structural_support: сдвиг целевых распределений на delta из stability.knockout.shifts (или −contribution)."""
    applied = []
    for m in cal.get("driver_parameter_mapping") or []:
        if m.get("driver_id") not in knockout:
            continue
        ko = ((m.get("stability") or {}).get("knockout") or {})
        if ko.get("mode") == "not_applicable":
            applied.append(f"{m['driver_id']}: knockout not_applicable"); continue
        shifts = ko.get("shifts") or [{"path": s["path"], "delta": -float(s["contribution"])} for s in (m.get("structural_support") or [])]
        for sh in shifts:
            _shift_path(cal, sh["path"], float(sh["delta"])); applied.append(f"{m['driver_id']}: {sh['path']} {sh['delta']:+}")
    return applied


def _shift_path(cal: dict, path: str, delta: float):
    """Сдвиг параметра калибровки по пути вида revenue_model.segments.AI.initial_growth[.mode]. Распределение — сдвиг всех положений."""
    parts = path.split("."); node = cal
    for p in parts[:-1]:
        if isinstance(node, list):
            node = next((m for m in node if isinstance(m, dict) and m.get("id") == p), None)
            if node is None:
                raise KeyError(f"путь {path}: нет вехи {p}")
            continue
        if p not in node:
            raise KeyError(f"путь {path}: нет ключа {p}")
        node = node[p]
    last = parts[-1]
    tgt = node.get(last)
    if isinstance(tgt, dict) and "distribution" in tgt or (isinstance(tgt, dict) and {"min", "mode", "max"} <= set(tgt)):
        for k in ("min", "mode", "max", "mean", "value", "median"):
            if k in tgt: tgt[k] = float(tgt[k]) + delta
    elif isinstance(tgt, (int, float)):
        node[last] = float(tgt) + delta
    elif last in ("mode", "min", "max", "mean", "value") and isinstance(node, dict):
        node[last] = float(node.get(last, 0.0)) + delta
    else:
        raise KeyError(f"путь {path}: неподдерживаемая цель для сдвига")


def _driver_effects(cal: dict, shocks: dict | None, n: int):
    """Из driver_parameter_mapping и шоков → корректировки: growth_add[seg](n,32), growth_mul[seg](n,32), margin_add[key](n,), mult_mul[Yh](n,)."""
    eff = {"growth_add": {}, "growth_mul": {}, "margin_add": {}, "mult_mul": {}, "milestone_prob_logit": {}, "milestone_timing": {}, "warnings": []}
    if not shocks:
        return eff
    for m in cal.get("driver_parameter_mapping") or []:
        d = m.get("driver_id")
        if d not in shocks:
            eff["warnings"].append(f"{d}: нет шока (не в active_drivers)"); continue
        for t in m.get("stochastic_targets") or []:
            x = joint_layer.effective_shock(shocks[d], int(t.get("lag_quarters", 0)), t.get("decay_half_life_quarters"))
            e = float(t["effect_per_plus_1sigma"]); tr = t.get("transform", "additive_pp"); path = t["path"]
            parts = path.split(".")
            if parts[0] == "revenue_model" and parts[1] in ("segments", "existing_segments", "service_segments") and len(parts) >= 4 and parts[3] in ("initial_growth", "post_service_growth"):
                seg = parts[2]
                if tr == "additive_pp":
                    eff["growth_add"][seg] = eff["growth_add"].get(seg, 0) + e * x
                elif tr in ("multiplicative_pct", "log_multiplier"):
                    f = (1 + e * x) if tr == "multiplicative_pct" else np.exp(e * x)
                    eff["growth_mul"][seg] = eff["growth_mul"].get(seg, 1) * f
                else:
                    eff["warnings"].append(f"{d}: transform {tr} для {path} не поддерживается")
            elif parts[0] == "milestone_model" and len(parts) >= 4 and parts[1] == "milestones":
                mid, what = parts[2], parts[3]
                ms_ = next((m for m in (cal["milestone_model"]["milestones"]) if m["id"] == mid), None)
                qm = int(min(31, max(0, round(float(((ms_ or {}).get("timing") or {}).get("mode", 4))))))
                if what == "probability" and tr == "probability_logit_shift":
                    eff["milestone_prob_logit"][mid] = eff["milestone_prob_logit"].get(mid, 0) + e * x[:, qm]
                elif what == "timing" and tr == "timing_quarters_shift":
                    eff["milestone_timing"][mid] = eff["milestone_timing"].get(mid, 0) + e * x[:, qm]
                else:
                    eff["warnings"].append(f"{d}: {tr} для {path} не поддерживается (нужны probability_logit_shift / timing_quarters_shift)")
            elif parts[0] in ("margin_model", "cash_model"):
                key = parts[-1] if parts[-1] not in ("mode",) else parts[-2]
                q = HORIZON_Q["Y3"] if "Y3" in key else (HORIZON_Q["Y8"] if "Y8" in key else HORIZON_Q["Y5"])
                if tr != "additive_pp":
                    eff["warnings"].append(f"{d}: для узлов маржи поддерживается только additive_pp ({path})"); continue
                eff["margin_add"][key] = eff["margin_add"].get(key, 0) + e * x[:, q]
            elif parts[0] == "valuation":
                h = next((hh for hh in ("Y3", "Y5", "Y8") if hh in path), None)
                if h is None:
                    eff["warnings"].append(f"{d}: не определён горизонт мультипликатора ({path})"); continue
                xs = x[:, HORIZON_Q[h]]
                f = (1 + e * xs) if tr == "multiplicative_pct" else (np.exp(e * xs) if tr == "log_multiplier" else None)
                if f is None:
                    eff["warnings"].append(f"{d}: transform {tr} для {path} не поддерживается"); continue
                eff["mult_mul"][h] = eff["mult_mul"].get(h, 1) * np.clip(f, 0.05, None)
            else:
                eff["warnings"].append(f"{d}: цель {path} движку неизвестна (not_testable)")
    return eff


# ---------------------------------------------------------------- блоки модели
def _revenue(draw: _Draw, cal: dict, P: dict, eff: dict):
    segs = cal["revenue_model"]["segments"]; n = draw.n
    total_q = np.zeros((n, QUARTERS)); t = (np.arange(1, QUARTERS + 1) / 4.0)[None, :]
    for name, seg in segs.items():
        ll = (seg.get("latent_loading") or {}).get("growth")
        g0 = dist_ppf(draw.u("growth", ll), seg["initial_growth"], shift=P["growth_shift"])
        g8 = dist_ppf(draw.u("growth", ll), seg["long_run_growth_y8"], shift=P["growth_shift"])
        g = g8[:, None] + (g0 - g8)[:, None] * np.power(2.0, -t / float(seg["growth_half_life_years"]))
        if name in eff["growth_add"]:
            g = g + eff["growth_add"][name]
        if name in eff["growth_mul"]:
            g = g * eff["growth_mul"][name]
        g = np.maximum(g, -0.95)
        total_q += float(seg["base_revenue_quarterly"]) * np.cumprod(np.power(1.0 + g, 0.25), axis=1)
    rev_y = total_q.reshape(n, 8, 4).sum(axis=2)
    return rev_y, 4.0 * sum(float(s["base_revenue_quarterly"]) for s in segs.values())


def _y8_from_rule(rule: dict, y5, rng):
    if rule.get("rule") == "y5_plus_normal":
        return np.clip(y5 + rng.normal(0.0, float(rule.get("sigma", 0.03)), len(y5)), float(rule.get("min", -1.0)), float(rule.get("max", 1.0)))
    raise ValueError(f"неизвестное правило Y8: {rule}")


def _margins(draw: _Draw, cal: dict, P: dict, eff: dict):
    mm = cal["margin_model"]; method = mm.get("method"); n = draw.n; rng = draw.rng; ms = P["margin_shift"]
    ll = (mm.get("latent_loading") or {}).get("margin"); madd = eff["margin_add"]
    def add(key, arr):
        return arr + madd[key] if key in madd else arr
    if method == "mean_reverting_positive_margin":
        m0 = float(mm["current_margin"]) + ms
        y5 = add("terminal_margin_Y5", dist_ppf(draw.u("margin", ll), mm["terminal_margin_Y5"], shift=ms))
        t8 = mm["terminal_margin_Y8"]
        y8 = add("terminal_margin_Y8", _y8_from_rule(t8, y5, rng) if "rule" in t8 else dist_ppf(draw.u("margin", ll), t8, shift=ms))
        hl = float(mm["half_life_years"]); sig = float(mm.get("shock_sigma", 0.0)); phi = float(mm.get("shock_persistence", 0.0))
        lo, hi = float(mm.get("lower_bound", -1.0)), float(mm.get("upper_bound", 1.0))
        t = np.arange(1, 9, dtype=float)
        term = np.where(t[None, :] <= 5, y5[:, None], y5[:, None] + (y8 - y5)[:, None] * (t[None, :] - 5) / 3.0)
        path = term + (m0 - y5)[:, None] * np.power(2.0, -t[None, :] / hl)
        eps = np.zeros((n, 8)); e = np.zeros(n)
        for k in range(8):
            e = phi * e + sig * rng.standard_normal(n); eps[:, k] = e
        return np.clip(path + eps, lo, hi)
    if method == "direct_fcf_nodes":
        nd = mm["nodes"]
        y1 = add("Y1", dist_ppf(draw.u("margin", ll), nd["Y1"], shift=ms)); y2 = add("Y2", dist_ppf(draw.u("margin", ll), nd["Y2"], shift=ms))
        y3 = add("Y3", dist_ppf(draw.u("margin", ll), nd["Y3"], shift=ms)); y5 = add("Y5_terminal_margin", dist_ppf(draw.u("margin", ll), nd["Y5_terminal_margin"], shift=ms))
        f4 = dist_ppf(rng.random(n), nd["Y4_terminal_fraction"]); t8 = nd["Y8_terminal_margin"]
        y8 = _y8_from_rule(t8, y5, rng) if "rule" in t8 else dist_ppf(draw.u("margin", ll), t8, shift=ms)
        if mm.get("monotonic", True):
            y2 = np.maximum(y2, y1); y3 = np.maximum(y3, y2)
        y4 = f4 * y5; y5 = np.maximum(y5, y4)
        y6 = y5 + (y8 - y5) / 3.0; y7 = y5 + 2.0 * (y8 - y5) / 3.0
        return np.stack([y1, y2, y3, y4, y5, y6, y7, y8], axis=1)
    if method == "ocf_capex_decomposition":
        def nodes(spec, factor_shift, prefix):
            ys = {k: add(prefix + k, dist_ppf(draw.u("margin", ll), spec[k], shift=factor_shift)) for k in ("Y1", "Y2", "Y3", "Y4", "Y5")}
            t8 = spec["Y8"]; y8 = _y8_from_rule(t8, ys["Y5"], rng) if "rule" in t8 else dist_ppf(draw.u("margin", ll), t8, shift=factor_shift)
            y6 = ys["Y5"] + (y8 - ys["Y5"]) / 3.0; y7 = ys["Y5"] + 2.0 * (y8 - ys["Y5"]) / 3.0
            return np.stack([ys["Y1"], ys["Y2"], ys["Y3"], ys["Y4"], ys["Y5"], y6, y7, y8], axis=1)
        return nodes(mm["ocf_margin_nodes"], ms, "ocf_") - nodes(mm["capex_revenue_nodes"], 0.0, "capex_")
    raise ValueError(f"неизвестный margin_model.method: {method}")


def _value_at(draw: _Draw, cal: dict, P: dict, horizon: str, rev, fcf, eff: dict):
    v = cal["valuation"]; spec = v[horizon]; basis = spec["basis"]; n = draw.n
    ll = (v.get("latent_loading") or {}).get("valuation")
    mult = dist_ppf(draw.u("valuation", ll), spec["multiple"], scale=P["mult_factor"])
    if horizon in eff["mult_mul"]:
        mult = mult * eff["mult_mul"][horizon]
    if basis == "revenue_bridge":
        return rev * mult, np.ones(n, dtype=int)
    if basis == "EBITDA_multiple":
        metric = rev * (fcf / np.where(rev != 0, rev, 1.0) + float(v.get("ebitda_margin_over_fcf", 0.0)))
    elif basis == "FCF_multiple":
        metric = fcf
    else:
        raise ValueError(f"неизвестный valuation basis: {basis}")
    E = metric * mult; fb = v.get("negative_fcf_fallback"); neg = metric <= 0; code = np.zeros(n, dtype=int)
    if neg.any():
        if not fb:
            raise ValueError(f"{horizon}: отрицательная метрика без negative_fcf_fallback (Archetypes §4.4)")
        fmult = dist_ppf(draw.u("valuation", ll), fb["multiple"], scale=P["mult_factor"])
        E = np.where(neg, rev * fmult, E); code = np.where(neg, 2, 0)
    return E, code


def _max_drawdown(rng, n, cal, E0, E3, E5, E8):
    mp = cal.get("market_path_model") or {}
    sigma = float((mp.get("quarterly_log_price_noise") or {}).get("annualized_sigma", 0.55)); hl = float(mp.get("valuation_mean_reversion_half_life_years", 2.0))
    kappa = math.log(2) / hl; dt = 0.25; a = math.exp(-kappa * dt); s = sigma * math.sqrt((1 - math.exp(-2 * kappa * dt)) / (2 * kappa))
    xq = np.array([0, 12, 20, 32]); yrows = np.log(np.stack([np.full(n, E0), E3, E5, E8], axis=1).clip(min=1.0))
    q = np.arange(0, 21); log_fund = np.empty((n, 21))
    for j, qq in enumerate(q):
        i = min(max(np.searchsorted(xq, qq, side="right") - 1, 0), 2); w = (qq - xq[i]) / (xq[i + 1] - xq[i])
        log_fund[:, j] = yrows[:, i] * (1 - w) + yrows[:, i + 1] * w
    x = np.zeros((n, 21)); eps = rng.standard_normal((n, 20))
    for k in range(1, 21):
        x[:, k] = x[:, k - 1] * a + s * eps[:, k - 1]
    price = np.exp(log_fund + x)
    return (price / np.maximum.accumulate(price, axis=1) - 1.0).min(axis=1)


def _simulate_chunk(rng, n, cal, E0, P, shocks):
    dep = cal.get("dependencies") or {}
    C, _ = _factor_corr(dep, P["rho_shift"]); L = np.linalg.cholesky(C)
    half = n // 2 if cal["simulation"].get("antithetic_variates", True) else n
    z = rng.standard_normal((half, 3)); z = np.vstack([z, -z])[:n] if half < n else z[:n]
    draw = _Draw(rng, n, z @ L.T, dep.get("default_loading", 0.7))
    eff = _driver_effects(cal, shocks, n)
    if cal["archetype"] == "pre_service_or_milestone_driven":
        return milestone_mc.simulate_chunk(draw, cal, E0, P, eff)
    rev_y, base_annual = _revenue(draw, cal, P, eff)
    margins = _margins(draw, cal, P, eff); fcf_y = rev_y * margins
    E3, b3 = _value_at(draw, cal, P, "Y3", rev_y[:, 2], fcf_y[:, 2], eff)
    E5, b5 = _value_at(draw, cal, P, "Y5", rev_y[:, 4], fcf_y[:, 4], eff)
    E8, b8 = _value_at(draw, cal, P, "Y8", rev_y[:, 7], fcf_y[:, 7], eff)
    dd = _max_drawdown(rng, n, cal, E0, E3, E5, E8)
    return {"E3": E3, "E5": E5, "E8": E8, "maxdd5": dd, "b3": b3, "b5": b5, "b8": b8, "rev5": rev_y[:, 4], "m5": margins[:, 4],
            "base_annual": base_annual, "warnings": eff["warnings"]}


def _summarize(E0, acc, quantiles, cal):
    E3, E5, E8, dd = acc["E3"], acc["E5"], acc["E8"], acc["maxdd5"]
    r3, r5, r8 = E3 / E0, E5 / E0, E8 / E0
    cagr = lambda r, h: np.power(np.clip(r, 1e-12, None), 1.0 / h) - 1.0  # noqa: E731
    c3, c5, c8 = cagr(r3, 3), cagr(r5, 5), cagr(r8, 8)
    ret5 = r5 - 1.0; k = max(1, int(math.ceil(0.05 * len(ret5)))); es5 = float(np.sort(ret5)[:k].mean())
    med5, med8 = float(np.median(c5)), float(np.median(c8))
    pr = (med8 / med5) if med5 > 0 else None
    pr_class = None if pr is None else ("strong" if pr >= 0.75 else ("moderate" if pr >= 0.5 else "weak"))
    basis_share = {}
    for h, key in (("Y3", "b3"), ("Y5", "b5"), ("Y8", "b8")):
        b = acc[key]; basis_share[h] = {"multiple": float((b == 0).mean()), "revenue_bridge": float((b == 1).mean()), "negative_fcf_fallback": float((b == 2).mean()),
                                        "milestone_conditioned_EV": float((b == 3).mean()), "failure_residual": float((b == 4).mean())}
    bridge_dep = {h: (v["revenue_bridge"] + v["negative_fcf_fallback"] + v["milestone_conditioned_EV"] + v["failure_residual"]) > 0.0 for h, v in basis_share.items()}
    ba = acc["base_annual"]
    rev_cagr5 = float(np.median(np.power(acc["rev5"] / ba, 0.2) - 1.0)) if (ba is not None and np.isfinite(ba) and ba > 0) else None
    gaps = {"median_revenue_CAGR_5Y": rev_cagr5, "median_fcf_margin_Y5": float(np.median(acc["m5"]))}
    rv = cal.get("reverse_valuation_ref") or {}
    if rv.get("implied_revenue_cagr_5y") is not None and rev_cagr5 is not None:
        gaps["RV_Growth_Gap"] = float(rv["implied_revenue_cagr_5y"]) - rev_cagr5
    if rv.get("discount_rate") is not None:
        r = float(rv["discount_rate"]); gaps["Price_Expectation_Gap"] = float(E0 / (np.median(E5) / (1 + r) ** 5))
    gaps["note"] = "диагностика (ответ LLM 21.09): без автоматического перехода оси Valuation"
    return {
        "paths": int(len(E5)),
        "return": {"median_CAGR_3Y": float(np.median(c3)), "median_CAGR_5Y": med5, "median_CAGR_8Y": med8,
                   "P_2x_3Y": float((r3 >= 2).mean()), "P_2x_5Y": float((r5 >= 2).mean()), "P_2x_8Y": float((r8 >= 2).mean()),
                   "P_5x_5Y": float((r5 >= 5).mean()), "P_5x_8Y": float((r8 >= 5).mean()),
                   "CAGR_5Y_quantiles": {str(qq): float(np.quantile(c5, qq)) for qq in quantiles}, "bridge_dependent": bridge_dep},
        "downside": {"P_loss_gt_30pct_5Y": float((r5 < 0.7).mean()), "P_loss_gt_50pct_5Y": float((r5 < 0.5).mean()), "expected_shortfall_5pct_5Y": es5,
                     "max_drawdown_5Y_quantiles": {str(qq): float(np.quantile(dd, qq)) for qq in (0.05, 0.25, 0.5, 0.75, 0.95)}, "max_drawdown_model_dependent": True},
        "scenario": {"variance_within_state_CAGR_5Y": float(np.var(c5)), "variance_between_state_scenarios": None,
                     "persistence_ratio": pr, "persistence_class": pr_class, "scenario_concentration": None},
        "valuation_basis_share": basis_share, "gap_metrics": gaps, "median_equity_value_5Y_b": float(np.median(E5) / 1e9),
        **(milestone_mc.summarize_extra(acc) if "ms5" in acc else {}),
    }


def _run_once(cal, E0, paths, seed, chunk, P, quantiles, joint, keep_paths=False):
    rng = np.random.default_rng(seed)
    acc = None
    done = 0; base_annual = None; warnings = []; ci = 0
    while done < paths:
        n = min(chunk, paths - done); n = n if n % 2 == 0 else n + 1
        shocks = None
        if joint:
            # общий путь: (global_seed, номер чанка) → одинаковые шоки драйверов у всех компаний при одинаковом chunk
            sh_seed = int(np.random.SeedSequence([joint["global_seed"], ci]).generate_state(1)[0])
            shocks = joint_layer.driver_shocks(joint["spec"], joint["drivers"], n, QUARTERS, sh_seed, cal["simulation"].get("antithetic_variates", True), joint.get("scenario"))
            for d, sig in (joint.get("adverse") or {}).items():
                if d in shocks:
                    shocks[d] = np.full_like(shocks[d], float(sig))
        r = _simulate_chunk(rng, n, cal, E0, P, shocks); base_annual = r["base_annual"]; warnings = r["warnings"]
        if acc is None:
            acc = {k: [] for k in r if k not in ("base_annual", "warnings")}
        for k in acc:
            acc[k].append(r[k])
        done += n; ci += 1
    acc = {k: np.concatenate(v)[:paths] for k, v in acc.items()}; acc["base_annual"] = base_annual
    out = _summarize(E0, acc, quantiles, cal); out["mapping_warnings"] = sorted(set(warnings))
    if keep_paths:
        out["_paths"] = {"r3": (acc["E3"] / E0).astype(np.float32), "r5": (acc["E5"] / E0).astype(np.float32), "r8": (acc["E8"] / E0).astype(np.float32),
                         "maxdd5": acc["maxdd5"].astype(np.float32), "b3": acc["b3"].astype(np.int8), "b5": acc["b5"].astype(np.int8), "b8": acc["b8"].astype(np.int8),
                         "path_id": np.arange(paths, dtype=np.int64)}
    return out


def run(inputs: dict, seed: int) -> dict:
    cal = copy.deepcopy(_normalize(inputs["calibration"]))
    E0 = float(inputs["equity_value_0"]); sim = cal["simulation"]
    paths = int(inputs.get("paths") or sim["paths"]); seed_used = int(inputs.get("seed_override") or sim.get("seed", seed))
    chunk = int(inputs.get("chunk", 50000)); quantiles = sim.get("store_summary_quantiles", [0.05, 0.25, 0.5, 0.75, 0.95])
    P0 = {"growth_shift": 0.0, "margin_shift": 0.0, "mult_factor": 1.0, "rho_shift": 0.0}
    C, fixed = _factor_corr(cal.get("dependencies") or {})
    # срез 2: совместный слой
    joint = None; knockout_applied = []
    js = cal.get("joint_simulation"); mapping = cal.get("driver_parameter_mapping") or []
    if mapping:
        spec = inputs.get("joint_layer_spec")
        if not spec:
            raise ValueError("driver_parameter_mapping задан, но inputs.joint_layer_spec (Joint_Simulation_Layer_Schema) не передан")
        drivers = list((js or {}).get("active_drivers") or [m["driver_id"] for m in mapping])
        adverse = {}
        for d in inputs.get("adverse_driver_stress") or []:
            m = next((m for m in mapping if m["driver_id"] == d), None)
            sig = ((m or {}).get("stability") or {}).get("adverse_driver_stress", {}).get("driver_sigma")
            if sig is None:
                raise ValueError(f"adverse_driver_stress: у {d} нет stability.adverse_driver_stress.driver_sigma")
            adverse[d] = float(sig)
        joint = {"spec": spec, "drivers": drivers, "global_seed": int(inputs.get("global_seed", seed_used)), "scenario": inputs.get("scenario"), "adverse": adverse}
        if inputs.get("knockout"):
            knockout_applied = _apply_knockout(cal, list(inputs["knockout"]))
    store = bool(inputs.get("store_paths"))
    base = _run_once(cal, E0, paths, seed_used, chunk, P0, quantiles, joint, keep_paths=store)
    paths_file = None
    if store:
        import os
        rd = inputs.get("_runs_dir"); rid = inputs.get("_run_id")
        if not rd or not rid:
            raise ValueError("store_paths: нужны _runs_dir и _run_id (подставляет сайдкар)")
        arrays = base.pop("_paths")
        meta = {"ticker": cal.get("ticker"), "model_version": VERSION, "global_seed": (joint or {}).get("global_seed", seed_used), "seed": seed_used,
                "chunk": chunk, "paths": paths, "joint": bool(joint), "scenario": (inputs.get("scenario") or {}).get("id", "BASE"), "equity_value_0": E0,
                "archetype": cal["archetype"], "path_id_rule": "path_id = chunk_index*chunk + i"}
        paths_file = os.path.join(rd, f"{rid}-paths.npz")
        np.savez_compressed(paths_file, meta=np.array(json.dumps(meta, ensure_ascii=False)), **arrays)
    out = {"model_version": VERSION, "paths_file": paths_file, "spec_version": SPEC_VERSION, "ticker": cal.get("ticker"), "archetype": cal["archetype"],
           "margin_method": (cal.get("margin_model") or {}).get("method") or ("milestone_model" if cal["archetype"] == "pre_service_or_milestone_driven" else None), "adapted_from": cal.get("adapted_from"), "state_vector": cal.get("state_vector"),
           "inputs_hash": hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16],
           "seed": seed_used, "paths": paths, "equity_value_0": E0, "factor_correlation_psd_fixed": fixed,
           "dependency_structure": "latent_factor_plus_idiosyncratic_shock (Archetypes §2.1); общий ранг не используется",
           "joint_simulation": None if not joint else {"layer_version": joint_layer.VERSION, "global_seed": joint["global_seed"], "active_drivers": joint["drivers"],
                                                        "scenario": (inputs.get("scenario") or {}).get("id", "BASE"), "adverse_driver_stress": sorted(joint["adverse"]),
                                                        "knockout_applied": knockout_applied, "path_id_rule": "path_id = chunk_index*chunk + i; шоки по SeedSequence([global_seed, chunk_index])"},
           "base": base}
    if inputs.get("convergence_check", True):
        conv = {}
        for pth in sorted({min(100_000, paths), min(250_000, paths), paths}):
            r = _run_once(cal, E0, pth, seed_used, chunk, P0, quantiles, joint)
            conv[str(pth)] = {"median_CAGR_5Y": r["return"]["median_CAGR_5Y"], "ES5": r["downside"]["expected_shortfall_5pct_5Y"], "P_loss_gt_30pct_5Y": r["downside"]["P_loss_gt_30pct_5Y"]}
        vals = list(conv.values())
        out["convergence"] = {"runs": conv, "stable": all(abs(v["median_CAGR_5Y"] - vals[-1]["median_CAGR_5Y"]) < 0.005 and abs(v["ES5"] - vals[-1]["ES5"]) < 0.01 and abs(v["P_loss_gt_30pct_5Y"] - vals[-1]["P_loss_gt_30pct_5Y"]) < 0.01 for v in vals),
                              "tolerance": {"median_CAGR_5Y": 0.005, "ES5": 0.01, "P_loss_gt_30pct_5Y": 0.01}}
    if inputs.get("robustness", True):
        rt = (cal.get("robustness_tests") or {}).get("Scenario_Robustness") or {}
        pert = rt.get("perturbations") or {}; tol = float(rt.get("delta_tolerance", 0.10))
        rp = min(paths, int(inputs.get("robustness_paths", 50_000))); runs = []
        for key, shifts in [("growth_modes_pp", "growth_shift"), ("margin_nodes_pp", "margin_shift"), ("terminal_multiple_pct", "mult_factor"), ("correlation_rho", "rho_shift")]:
            for v in pert.get(key, []):
                P = dict(P0); P[shifts] = (1.0 + float(v)) if shifts == "mult_factor" else float(v)
                r = _run_once(cal, E0, rp, seed_used, chunk, P, quantiles, joint)
                runs.append({"perturbation": key, "value": v, "median_CAGR_5Y": r["return"]["median_CAGR_5Y"],
                             "dP_2x_5Y": r["return"]["P_2x_5Y"] - base["return"]["P_2x_5Y"],
                             "dP_loss_gt_30pct_5Y": r["downside"]["P_loss_gt_30pct_5Y"] - base["downside"]["P_loss_gt_30pct_5Y"]})
        sign0 = np.sign(base["return"]["median_CAGR_5Y"])
        same = [np.sign(r["median_CAGR_5Y"]) == sign0 for r in runs]
        within = [abs(r["dP_2x_5Y"]) <= tol and abs(r["dP_loss_gt_30pct_5Y"]) <= tol for r in runs]
        out["robustness"] = {"runs": runs, "paths_per_run": rp, "same_sign_share": (sum(same) / len(runs)) if runs else None,
                             "within_delta_tolerance_share": (sum(within) / len(runs)) if runs else None, "delta_tolerance": tol,
                             "pass": bool((sum(same) / len(runs) >= 0.75) and (sum(within) / len(runs) >= 0.75)) if runs else None,  # bool(): numpy.bool не сериализуется FastAPI при save=false
                             "pass_rule": "v1.1: знак медианы CAGR 5Y сохранён в ≥75% прогонов И |ΔP(2x,5Y)|, |ΔP(loss>30%,5Y)| ≤ допуска в ≥75%"}
    return out
