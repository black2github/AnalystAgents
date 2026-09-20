"""Условный Монте-Карло v1.0 (SPCX_Conditional_Monte_Carlo_Specification_v1.0, 20.09.2026).

State Vector → условные распределения параметров → MC → оценка на 3/5/8Y → распределение доходности.
inputs: {"calibration": <dict из mc_calibration YAML>, "equity_value_0": float,
         "paths": int|None (переопределение), "chunk": 50000, "convergence_check": bool, "robustness": bool}
Интерпретации движка, не заданные спецификацией явно (помечены в outputs.engine_interpretations):
  I1 начальный и долгосрочный рост сегмента берутся из одной равномерной величины (когерентный сценарий);
  I2 один и тот же ранг terminal_multiple используется для Y3 (revenue bridge), Y5 и Y8;
  I3 margin_improvement — общий ранг для узлов Y1..Y3; доля Y4 — независимый розыгрыш;
  I4 путь цены для max drawdown: лог-линейная интерполяция фундаментальной стоимости между якорями
     0/Y3/Y5/Y8 и OU-шум (sigma annualized, half-life = valuation_mean_reversion_half_life_years), окно 5Y.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np
from scipy.special import ndtr

VERSION = "1.0.0"
SPEC_VERSION = "SPCX_Conditional_Monte_Carlo_Specification_v1.0"
VARS = ["AI_growth", "Connectivity_growth", "Space_growth", "margin_improvement", "terminal_margin", "terminal_multiple"]
SEGMENTS = {"AI": "AI_growth", "Connectivity": "Connectivity_growth", "Space": "Space_growth"}
QUARTERS = 32  # 8 лет


def _tri_ppf(u, lo, mode, hi):
    lo, mode, hi = float(lo), float(mode), float(hi)
    if not (lo <= mode <= hi):
        raise ValueError(f"triangular: требуется min <= mode <= max, получено {lo}, {mode}, {hi}")
    if hi == lo:
        return np.full_like(u, lo, dtype=float)
    fc = (mode - lo) / (hi - lo)
    left = lo + np.sqrt(np.clip(u, 0, 1) * (hi - lo) * (mode - lo))
    right = hi - np.sqrt((1 - np.clip(u, 0, 1)) * (hi - lo) * (hi - mode))
    return np.where(u < fc, left, right)


def _corr_matrix(cal: dict, rho_shift: float = 0.0):
    rc = (cal.get("dependencies") or {}).get("rank_correlations") or {}
    idx = {v: i for i, v in enumerate(VARS)}
    C = np.eye(len(VARS))
    alias = {"margin_improvement": "margin_improvement", "terminal_margin": "terminal_margin", "terminal_multiple": "terminal_multiple"}
    for key, val in rc.items():
        a, b = key.split("__")
        a, b = alias.get(a, a), alias.get(b, b)
        if a in idx and b in idx:
            r = float(val["rho"] if isinstance(val, dict) else val)
            r = max(-0.95, min(0.95, r + rho_shift))
            C[idx[a], idx[b]] = C[idx[b], idx[a]] = r
    w, V = np.linalg.eigh(C)
    fixed = False
    if w.min() < -1e-10:
        w = np.clip(w, 1e-8, None)
        C = V @ np.diag(w) @ V.T
        d = np.sqrt(np.diag(C))
        C = C / np.outer(d, d)
        fixed = True
    return C, fixed


def _growth_path(u, seg: dict, shift: float):
    gi = seg["annual_growth_initial"]
    gl = seg["long_run_growth_y8"]
    g0 = _tri_ppf(u, gi["min"] + shift, gi["mode"] + shift, gi["max"] + shift)
    g8 = _tri_ppf(u, gl["min"] + shift, gl["mode"] + shift, gl["max"] + shift)  # I1
    hl = float(seg["mean_reversion_half_life_years"])
    t = (np.arange(1, QUARTERS + 1) / 4.0)[None, :]
    g = g8[:, None] + (g0 - g8)[:, None] * np.power(2.0, -t / hl)
    return g  # (n, 32) годовой темп в квартале k


def _simulate_chunk(rng, n, cal, E0, P):
    """Возвращает dict массивов длины n: E3, E5, E8, R5, maxdd5."""
    C, _ = _corr_matrix(cal, P["rho_shift"])
    L = np.linalg.cholesky(C)
    half = n // 2 if cal["simulation"].get("antithetic_variates", True) else n
    z = rng.standard_normal((half, len(VARS)))
    z = np.vstack([z, -z]) if half < n else z
    z = z[:n]
    u = ndtr(z @ L.T)
    U = {v: u[:, i] for i, v in enumerate(VARS)}
    facts = cal["source_facts"]["q2_2026"]
    rev_q0 = {"AI": facts["AI_revenue_b"]["value"], "Connectivity": facts["Connectivity_revenue_b"]["value"], "Space": facts["Space_revenue_b"]["value"]}
    total_q = np.zeros((n, QUARTERS))
    for seg, var in SEGMENTS.items():
        g = _growth_path(U[var], cal["revenue_model"]["segments"][seg], P["growth_shift"])
        qf = np.power(1.0 + g, 0.25)
        path = float(rev_q0[seg]) * 1e9 * np.cumprod(qf, axis=1)
        total_q += path
    rev_y = total_q.reshape(n, 8, 4).sum(axis=2)  # годовая выручка Y1..Y8
    mm = cal["margin_model"]["nodes"]
    ms = P["margin_shift"]
    um = U["margin_improvement"]
    y1 = _tri_ppf(um, mm["Y1"]["min"] + ms, mm["Y1"]["mode"] + ms, mm["Y1"]["max"] + ms)
    y2 = _tri_ppf(um, mm["Y2"]["min"] + ms, mm["Y2"]["mode"] + ms, mm["Y2"]["max"] + ms)
    y3 = _tri_ppf(um, mm["Y3"]["min"] + ms, mm["Y3"]["mode"] + ms, mm["Y3"]["max"] + ms)
    y5 = _tri_ppf(U["terminal_margin"], mm["Y5_terminal_margin"]["min"] + ms, mm["Y5_terminal_margin"]["mode"] + ms, mm["Y5_terminal_margin"]["max"] + ms)
    f4 = _tri_ppf(rng.random(n), mm["Y4_terminal_fraction"]["min"], mm["Y4_terminal_fraction"]["mode"], mm["Y4_terminal_fraction"]["max"])  # I3
    y2 = np.maximum(y2, y1); y3 = np.maximum(y3, y2)
    y4 = f4 * y5; y5 = np.maximum(y5, y4)
    y8 = np.clip(y5 + rng.normal(0, 0.03, n), 0.15, 0.40)
    y6 = y5 + (y8 - y5) / 3.0; y7 = y5 + 2.0 * (y8 - y5) / 3.0
    margins = np.stack([y1, y2, y3, y4, y5, y6, y7, y8], axis=1)
    fcf_y = rev_y * margins
    tm = cal["terminal_multiple"]
    mk = P["mult_factor"]
    um2 = U["terminal_multiple"]  # I2
    m5 = _tri_ppf(um2, tm["Y5"]["min"] * mk, tm["Y5"]["mode"] * mk, tm["Y5"]["max"] * mk)
    m8 = _tri_ppf(um2, tm["Y8"]["min"] * mk, tm["Y8"]["mode"] * mk, tm["Y8"]["max"] * mk)
    m3 = _tri_ppf(um2, tm["Y3"]["min"] * mk, tm["Y3"]["mode"] * mk, tm["Y3"]["max"] * mk)
    E3 = rev_y[:, 2] * m3
    E5 = fcf_y[:, 4] * m5
    E8 = fcf_y[:, 7] * m8
    # I4: путь цены для max drawdown (окно 5Y = 20 кварталов)
    mp = cal.get("market_path_model") or {}
    sigma = float((mp.get("quarterly_log_price_noise") or {}).get("annualized_sigma", 0.55))
    hl = float(mp.get("valuation_mean_reversion_half_life_years", 2.0))
    kappa = math.log(2) / hl; dt = 0.25
    a = math.exp(-kappa * dt); s = sigma * math.sqrt((1 - math.exp(-2 * kappa * dt)) / (2 * kappa))
    anchors_q = np.array([0, 12, 20, 32]); anchors_v = np.log(np.stack([np.full(n, E0), E3, E5, E8], axis=1).clip(min=1.0))
    q = np.arange(0, 21)
    log_fund = np.stack([np.interp(q, anchors_q, anchors_v[i]) for i in range(n)]) if n <= 2000 else _interp_rows(q, anchors_q, anchors_v)
    x = np.zeros((n, 21))
    eps = rng.standard_normal((n, 20))
    for k in range(1, 21):
        x[:, k] = x[:, k - 1] * a + s * eps[:, k - 1]
    price = np.exp(log_fund + x)
    running_max = np.maximum.accumulate(price, axis=1)
    maxdd5 = (price / running_max - 1.0).min(axis=1)
    return {"E3": E3, "E5": E5, "E8": E8, "maxdd5": maxdd5}


def _interp_rows(q, xq, yrows):
    # линейная интерполяция по строкам без цикла python: сегменты [0,12],[12,20],[20,32]
    out = np.empty((yrows.shape[0], len(q)))
    for j, qq in enumerate(q):
        i = np.searchsorted(xq, qq, side="right") - 1
        i = min(max(i, 0), len(xq) - 2)
        w = (qq - xq[i]) / (xq[i + 1] - xq[i])
        out[:, j] = yrows[:, i] * (1 - w) + yrows[:, i + 1] * w
    return out


def _summarize(E0, acc, quantiles):
    E3, E5, E8, dd = acc["E3"], acc["E5"], acc["E8"], acc["maxdd5"]
    r3, r5, r8 = E3 / E0, E5 / E0, E8 / E0
    cagr = lambda r, h: np.power(np.clip(r, 1e-12, None), 1.0 / h) - 1.0  # noqa: E731
    c3, c5, c8 = cagr(r3, 3), cagr(r5, 5), cagr(r8, 8)
    ret5 = r5 - 1.0
    k = max(1, int(math.ceil(0.05 * len(ret5))))
    es5 = float(np.sort(ret5)[:k].mean())
    med5, med8 = float(np.median(c5)), float(np.median(c8))
    pr = (med8 / med5) if med5 > 0 else None
    pr_class = None if pr is None else ("strong" if pr >= 0.75 else ("moderate" if pr >= 0.5 else "weak"))
    qs = {str(qq): float(np.quantile(c5, qq)) for qq in quantiles}
    return {
        "paths": int(len(E5)),
        "return": {"median_CAGR_3Y": float(np.median(c3)), "median_CAGR_5Y": med5, "median_CAGR_8Y": med8,
                   "P_2x_3Y": float((r3 >= 2).mean()), "P_2x_5Y": float((r5 >= 2).mean()), "P_2x_8Y": float((r8 >= 2).mean()),
                   "P_5x_5Y": float((r5 >= 5).mean()), "P_5x_8Y": float((r8 >= 5).mean()),
                   "CAGR_5Y_quantiles": qs},
        "downside": {"P_loss_gt_30pct_5Y": float((r5 < 0.7).mean()), "P_loss_gt_50pct_5Y": float((r5 < 0.5).mean()),
                     "expected_shortfall_5pct_5Y": es5,
                     "max_drawdown_5Y_quantiles": {str(qq): float(np.quantile(dd, qq)) for qq in (0.05, 0.25, 0.5, 0.75, 0.95)},
                     "max_drawdown_model_dependent": True},
        "scenario": {"variance_within_state_CAGR_5Y": float(np.var(c5)), "variance_between_state_scenarios": None,
                     "persistence_ratio": pr, "persistence_class": pr_class,
                     "scenario_concentration": None, "scenario_concentration_note": "единственное условное состояние — не интерпретируется (§11)"},
        "median_equity_value_5Y_b": float(np.median(E5) / 1e9), "median_terminal_revenue_5Y_note": "см. calibration revenue_model",
    }


def _run_once(cal, E0, paths, seed, chunk, P, quantiles):
    rng = np.random.default_rng(seed)
    acc = {"E3": [], "E5": [], "E8": [], "maxdd5": []}
    done = 0
    while done < paths:
        n = min(chunk, paths - done)
        n = n if n % 2 == 0 else n + 1
        r = _simulate_chunk(rng, n, cal, E0, P)
        for k in acc:
            acc[k].append(r[k])
        done += n
    acc = {k: np.concatenate(v)[:paths] for k, v in acc.items()}
    return _summarize(E0, acc, quantiles)


def run(inputs: dict, seed: int) -> dict:
    cal = inputs["calibration"]
    E0 = float(inputs["equity_value_0"])
    sim = cal["simulation"]
    paths = int(inputs.get("paths") or sim["paths"])
    seed_used = int(inputs.get("seed_override") or sim.get("seed", seed))
    chunk = int(inputs.get("chunk", 50000))
    quantiles = sim.get("store_summary_quantiles", [0.05, 0.25, 0.5, 0.75, 0.95])
    P0 = {"growth_shift": 0.0, "margin_shift": 0.0, "mult_factor": 1.0, "rho_shift": 0.0}
    C, fixed = _corr_matrix(cal)
    base = _run_once(cal, E0, paths, seed_used, chunk, P0, quantiles)
    out = {
        "model_version": VERSION, "spec_version": SPEC_VERSION, "state_vector": cal.get("state_vector"),
        "inputs_hash": hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16],
        "seed": seed_used, "paths": paths, "equity_value_0": E0,
        "correlation_matrix_psd_fixed": fixed,
        "engine_interpretations": ["I1 g_init/g_long из одного ранга", "I2 общий ранг мультипликатора Y3/Y5/Y8",
                                   "I3 margin_improvement — общий ранг Y1..Y3; доля Y4 независима",
                                   "I4 путь цены: лог-интерполяция якорей 0/Y3/Y5/Y8 + OU-шум, окно 5Y"],
        "base": base,
    }
    if inputs.get("convergence_check", True):
        conv = {}
        for pth in [100_000, 250_000, paths]:
            if pth <= paths:
                r = _run_once(cal, E0, pth, seed_used, chunk, P0, quantiles)
                conv[str(pth)] = {"median_CAGR_5Y": r["return"]["median_CAGR_5Y"], "ES5": r["downside"]["expected_shortfall_5pct_5Y"]}
        vals = list(conv.values())
        stable = all(abs(v["median_CAGR_5Y"] - vals[-1]["median_CAGR_5Y"]) < 0.005 and abs(v["ES5"] - vals[-1]["ES5"]) < 0.01 for v in vals)
        out["convergence"] = {"runs": conv, "stable": stable, "tolerance": {"median_CAGR_5Y": 0.005, "ES5": 0.01}}
    if inputs.get("robustness", True):
        rt = (cal.get("robustness_tests") or {}).get("Scenario_Robustness") or {}
        pert = rt.get("perturbations") or {}
        rp = min(paths, int(inputs.get("robustness_paths", 50_000)))
        runs = []
        for key, shifts in [("growth_modes_pp", "growth_shift"), ("margin_nodes_pp", "margin_shift"), ("terminal_multiple_pct", "mult_factor"), ("correlation_rho", "rho_shift")]:
            for v in pert.get(key, []):
                P = dict(P0)
                P[shifts] = (1.0 + float(v)) if shifts == "mult_factor" else float(v)
                r = _run_once(cal, E0, rp, seed_used, chunk, P, quantiles)
                runs.append({"perturbation": key, "value": v, "median_CAGR_5Y": r["return"]["median_CAGR_5Y"]})
        sign0 = np.sign(base["return"]["median_CAGR_5Y"])
        same = sum(1 for r in runs if np.sign(r["median_CAGR_5Y"]) == sign0)
        out["robustness"] = {"runs": runs, "paths_per_run": rp, "same_sign_share": (same / len(runs)) if runs else None,
                             "pass": (same / len(runs) >= 0.75) if runs else None, "pass_rule": rt.get("pass_rule")}
    return out
