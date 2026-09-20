"""Reverse valuation v1.0: какой 5-летний CAGR выручки заложен в текущей капитализации (спецификация v1.0 от 20.09.2026).

PV_Equity(g) = Σ_{t=1..4} FCF_t/(1+r)^t + FCF_5·M/(1+r)^5,  FCF_t = Revenue_0·(1+g)^t · margin_t,
margin_t = current + (terminal − current)·t/5 (линейная конвергенция, §5). Equity-мультипликатор: net debt не вычитается (§7).
Enterprise-мультипликатор: TerminalEquity_5 = FCF_5·M − net_debt_5. Решение по g — бисекция в расширяемых границах (§14).
Классификации V1..V5 движок НЕ придумывает (§12.1): вычисляет метрики и проверяет только существующие переходы
E-31/E-32/E-33 из текущего состояния Valuation, если оно передано.

inputs (по §3, допускается плоская форма для совместимости):
  market: {price, shares_outstanding}; balance_sheet: {net_debt}; base_period: {revenue_ttm, current_fcf_margin};
  discounting: {discount_rate, stress_rates: [..]}; terminal: {fcf_margin_range: {min, base, max}, multiple_range: {min, base, max}};
  calculation: {forecast_years: 5, terminal_method: equity_fcf_multiple | enterprise_fcf_multiple, net_debt_5};
  scenario_state: {...}; current_valuation_state: "V4"; cagr_bounds: [-0.5, 3.0]; hard_limit: 10.0
"""
from __future__ import annotations

import hashlib
import json
import math

VERSION = "1.0.0"
SPEC_VERSION = "Investment_System_Reverse_Valuation_Specification_v1.0"

# существующие нормативные переходы оси Valuation (triggers.yaml SpaceX); движок их только проверяет
VALUATION_TRANSITIONS = [
    {"trigger_id": "SPCX-E-31", "from": "V4", "to": "V3", "cond": lambda g, m, M: g <= 0.25 and m >= 0.20 and M <= 35},
    {"trigger_id": "SPCX-E-32", "from": "V3", "to": "V2", "cond": lambda g, m, M: g <= 0.20 and m >= 0.20 and M <= 30},
    {"trigger_id": "SPCX-E-33", "from": "V4", "to": "V5", "cond": lambda g, m, M: g > 0.35 and m > 0.30 and M > 35},
]


def _norm(inputs: dict) -> dict:
    """Приводит вложенную (§3) или плоскую форму к плоскому словарю параметров."""
    g = lambda *ks, d=None: next((inputs[k] for k in ks if k in inputs), d)  # noqa: E731
    mk = inputs.get("market", {}); bs = inputs.get("balance_sheet", {}); bp = inputs.get("base_period", {})
    dc = inputs.get("discounting", {}); tm = inputs.get("terminal", {}); calc = inputs.get("calculation", {})
    p = {
        "price": mk.get("price", g("price")),
        "shares": mk.get("shares_outstanding", g("shares_outstanding")),
        "equity_value": mk.get("equity_value") if isinstance(mk.get("equity_value"), (int, float)) else g("market_cap_usd"),
        "net_debt": bs.get("net_debt", g("net_debt_usd", d=0.0)),
        "revenue0": bp.get("revenue_ttm", g("revenue_ttm_usd")),
        "m0": bp.get("current_fcf_margin", g("current_fcf_margin")),
        "r": dc.get("discount_rate", g("discount_rate", d=0.10)),
        "stress_rates": dc.get("stress_rates", g("stress_rates", d=[])),
        "margin": tm.get("fcf_margin_range", {"base": g("terminal_fcf_margin")}),
        "multiple": tm.get("multiple_range", {"base": g("terminal_multiple")}),
        "years": int(calc.get("forecast_years", g("forecast_years", d=5))),
        "method": calc.get("terminal_method", g("multiple_kind", d="equity_fcf_multiple")),
        "net_debt_5": calc.get("net_debt_5", g("net_debt_5", d=None)),
        "cagr_bounds": list(g("cagr_bounds", d=[-0.5, 3.0])),
        "hard_limit": float(g("hard_limit", d=10.0)),
        "scenario_state": inputs.get("scenario_state"),
        "current_v": g("current_valuation_state"),
    }
    if p["method"] == "enterprise": p["method"] = "enterprise_fcf_multiple"
    if p["method"] == "equity": p["method"] = "equity_fcf_multiple"
    if p["equity_value"] is None:
        if p["price"] is None or p["shares"] is None:
            raise ValueError("нужны price и shares_outstanding либо market_cap_usd")
        p["equity_value"] = float(p["price"]) * float(p["shares"])
    if p["m0"] is None: p["m0"] = float(p["margin"]["base"])
    for k in ("revenue0", "r"):
        if p[k] is None: raise ValueError(f"missing input {k}")
    if p["method"] == "enterprise_fcf_multiple" and p["net_debt_5"] is None:
        raise ValueError("enterprise_fcf_multiple требует net_debt_5")
    return p


def _pv_parts(g: float, m1: float, M: float, r: float, p: dict) -> tuple[float, float, float, float]:
    n = p["years"]; rev0 = float(p["revenue0"]); m0 = float(p["m0"])
    pv_interim = 0.0; rev = rev0; fcf_n = 0.0
    for t in range(1, n + 1):
        rev = rev0 * (1.0 + g) ** t
        fcf_t = rev * (m0 + (m1 - m0) * t / n)
        if t < n:
            pv_interim += fcf_t / (1.0 + r) ** t
        else:
            fcf_n = fcf_t
    terminal_equity = fcf_n * M
    if p["method"] == "enterprise_fcf_multiple":
        terminal_equity -= float(p["net_debt_5"])
    pv_terminal = terminal_equity / (1.0 + r) ** n
    return pv_interim, pv_terminal, rev, fcf_n


def _solve(m1: float, M: float, r: float, p: dict) -> dict:
    target = float(p["equity_value"])
    f = lambda g: _pv_parts(g, m1, M, r, p)[0] + _pv_parts(g, m1, M, r, p)[1] - target  # noqa: E731
    lo, hi = float(p["cagr_bounds"][0]), float(p["cagr_bounds"][1])
    # расширяем верхнюю границу до hard limit, если корень выше
    while f(hi) < 0 and hi < p["hard_limit"]:
        hi = min(hi * 2 if hi > 0 else 1.0, p["hard_limit"])
    if f(lo) > 0 or f(hi) < 0:
        return {"status": "no_solution_within_bounds", "bounds": [lo, hi]}
    it = 0
    while hi - lo > 1e-9 and it < 300:
        mid = (lo + hi) / 2
        if f(mid) < 0: lo = mid
        else: hi = mid
        it += 1
    g = (lo + hi) / 2
    pv_i, pv_t, rev_n, fcf_n = _pv_parts(g, m1, M, r, p)
    resid = pv_i + pv_t - target
    return {"status": "ok", "g": g, "pv_interim": pv_i, "pv_terminal": pv_t, "terminal_revenue": rev_n,
            "terminal_fcf": fcf_n, "residual": resid, "iterations": it,
            "converged": abs(resid) <= max(1e-6 * target, 1.0) and math.isfinite(g)}


def run(inputs: dict, seed: int) -> dict:
    p = _norm(inputs)
    m_r, M_r = p["margin"], p["multiple"]
    m_b, M_b, r = float(m_r["base"]), float(M_r["base"]), float(p["r"])
    base = _solve(m_b, M_b, r, p)
    inputs_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]
    out = {
        "model_version": VERSION, "spec_version": SPEC_VERSION, "inputs_hash": inputs_hash,
        "scenario_state": p["scenario_state"], "terminal_method": p["method"],
        "calculated": {"equity_value": p["equity_value"], "enterprise_value": p["equity_value"] + float(p["net_debt"]),
                       "terminal_fcf_margin": m_b, "terminal_multiple": M_b, "discount_rate": r, "current_fcf_margin": p["m0"],
                       "revenue_ttm": float(p["revenue0"])},
        "validation": {"converged": base.get("converged", False), "residual": base.get("residual"), "status": base["status"],
                       "assumption_conflict": False},
        "sensitivity": {"margin_multiple_grid": {}, "discount_rate_grid": {}},
        "valuation_state": {"previous": p["current_v"], "candidate": p["current_v"], "transition_trigger": None, "transition_allowed": False},
    }
    if base["status"] != "ok":
        out["calculated"]["implied_revenue_cagr_5y"] = None
        return out
    g = base["g"]
    pv_total = base["pv_interim"] + base["pv_terminal"]
    out["calculated"].update({
        "implied_revenue_cagr_5y": round(g, 6), "terminal_revenue": round(base["terminal_revenue"], 2),
        "terminal_fcf": round(base["terminal_fcf"], 2), "pv_interim_fcf": round(base["pv_interim"], 2),
        "pv_terminal_value": round(base["pv_terminal"], 2),
        "terminal_value_share_of_pv": round(base["pv_terminal"] / pv_total, 4) if pv_total else None,
        "control_cagr": round((base["terminal_revenue"] / float(p["revenue0"])) ** (1.0 / p["years"]) - 1.0, 6),
    })
    # sensitivity 3×3 по марже × мультипликатору (если заданы min/max)
    ms = [m_r.get(k) for k in ("min", "base", "max") if m_r.get(k) is not None]
    Ms = [M_r.get(k) for k in ("min", "base", "max") if M_r.get(k) is not None]
    for m in ms:
        for M in Ms:
            s = _solve(float(m), float(M), r, p)
            out["sensitivity"]["margin_multiple_grid"][f"margin={m}|multiple={M}"] = round(s["g"], 4) if s["status"] == "ok" else s["status"]
    for rr in p["stress_rates"]:
        s = _solve(m_b, M_b, float(rr), p)
        out["sensitivity"]["discount_rate_grid"][f"r={rr}"] = round(s["g"], 4) if s["status"] == "ok" else s["status"]
    # проверка существующих переходов оси Valuation из текущего состояния (§13 п.9)
    if p["current_v"]:
        for tr in VALUATION_TRANSITIONS:
            if tr["from"] == p["current_v"] and tr["cond"](g, m_b, M_b):
                out["valuation_state"].update({"candidate": tr["to"], "transition_trigger": tr["trigger_id"], "transition_allowed": True})
                break
    return out
