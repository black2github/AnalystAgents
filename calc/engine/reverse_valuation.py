"""Reverse valuation v0.1: какой CAGR выручки заложен в текущей капитализации при заданных terminal-допущениях.

Формулы (спецификация другой LLM, 20.09.2026, шаги 1–5):
  Revenue_t = Revenue_{t-1} · (1+g);  FCF_t = Revenue_t · margin_t (маржа линейно от current к terminal);
  PV(g) = Σ_{t=1..N} FCF_t/(1+r)^t + FCF_N · M/(1+r)^N − NetDebt;   ищем g: PV(g) = MarketCap.
Мультипликатор M трактуется как equity-multiple к FCF; если задан enterprise-multiple — вычитается net_debt.
Классификация V1..V5 — ПРЕДВАРИТЕЛЬНАЯ (worst-case ≥2 из 3), до утверждения спецификации.

inputs: {"market_cap_usd": 2.013e12, "net_debt_usd": 0, "revenue_ttm_usd": 23.044e9, "current_fcf_margin": -0.5,
         "terminal_fcf_margin": 0.20, "terminal_multiple": 30, "discount_rate": 0.10, "forecast_years": 5,
         "multiple_kind": "equity"|"enterprise", "cagr_bounds": [-0.5, 3.0]}
outputs: implied_revenue_cagr, implied_revenue_terminal_usd, terminal_fcf_usd, pv_check, iterations, v_state (предварительно).
"""
from __future__ import annotations

VERSION = "0.1.0"


def _pv(g: float, p: dict) -> float:
    n = int(p["forecast_years"])
    rev = float(p["revenue_ttm_usd"])
    m0 = float(p["current_fcf_margin"])
    m1 = float(p["terminal_fcf_margin"])
    r = float(p["discount_rate"])
    mult = float(p["terminal_multiple"])
    pv = 0.0
    fcf_t = 0.0
    for t in range(1, n + 1):
        rev *= 1.0 + g
        margin = m0 + (m1 - m0) * t / n
        fcf_t = rev * margin
        pv += fcf_t / (1.0 + r) ** t
    terminal = fcf_t * mult
    if p.get("multiple_kind", "equity") == "enterprise":
        terminal -= float(p.get("net_debt_usd", 0.0))
    pv += terminal / (1.0 + r) ** n
    pv -= float(p.get("net_debt_usd", 0.0)) if p.get("multiple_kind", "equity") == "equity" else 0.0
    return pv


def _classify(cagr: float, margin: float, mult: float) -> dict:
    # предварительно: каждое измерение — normal / demanding / extreme; V4 = ≥2 demanding+, V5 = ≥2 extreme
    def lvl(v, demanding, extreme):
        return 2 if v > extreme else (1 if v > demanding else 0)
    levels = {"cagr": lvl(cagr, 0.25, 0.35), "margin": lvl(margin, 0.25, 0.30), "multiple": lvl(mult, 35, 45)}
    n_ext = sum(1 for v in levels.values() if v == 2)
    n_dem = sum(1 for v in levels.values() if v >= 1)
    if n_ext >= 2:
        v = "V5"
    elif n_dem >= 2:
        v = "V4"
    elif cagr <= 0.15 and margin >= 0.20 and mult <= 25:
        v = "V1"
    elif cagr <= 0.20 and margin >= 0.20 and mult <= 30:
        v = "V2"
    elif cagr <= 0.25 and margin >= 0.20 and mult <= 35:
        v = "V3"
    else:
        v = "V4"
    return {"v_state": v, "levels": levels, "rule": "provisional: worst-case ≥2 of 3 (v0.1, не утверждено)"}


def run(inputs: dict, seed: int) -> dict:
    p = dict(inputs)
    p.setdefault("forecast_years", 5)
    p.setdefault("discount_rate", 0.10)
    p.setdefault("net_debt_usd", 0.0)
    p.setdefault("current_fcf_margin", p["terminal_fcf_margin"])
    target = float(p["market_cap_usd"])
    lo, hi = p.get("cagr_bounds", [-0.5, 3.0])
    if _pv(hi, p) < target:
        raise ValueError("market cap unreachable within cagr_bounds: increase terminal assumptions or bounds")
    if _pv(lo, p) > target:
        raise ValueError("market cap below PV at minimum cagr: assumptions too generous")
    it = 0
    while hi - lo > 1e-7 and it < 200:
        mid = (lo + hi) / 2
        if _pv(mid, p) < target:
            lo = mid
        else:
            hi = mid
        it += 1
    g = (lo + hi) / 2
    rev_terminal = float(p["revenue_ttm_usd"]) * (1 + g) ** int(p["forecast_years"])
    fcf_terminal = rev_terminal * float(p["terminal_fcf_margin"])
    cls = _classify(g, float(p["terminal_fcf_margin"]), float(p["terminal_multiple"]))
    return {
        "implied_revenue_cagr": round(g, 5),
        "implied_revenue_terminal_usd_b": round(rev_terminal / 1e9, 2),
        "terminal_fcf_usd_b": round(fcf_terminal / 1e9, 2),
        "pv_check_usd_b": round(_pv(g, p) / 1e9, 2),
        "target_market_cap_usd_b": round(target / 1e9, 2),
        "iterations": it,
        "assumptions": {k: p[k] for k in ("forecast_years", "discount_rate", "terminal_fcf_margin", "terminal_multiple", "current_fcf_margin", "net_debt_usd", "multiple_kind") if k in p},
        **cls,
    }
