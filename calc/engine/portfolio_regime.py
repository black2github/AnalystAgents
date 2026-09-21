"""Портфель v1.0: NAV, просадки, взвешенная секторная просадка, режим Normal/Stress/Shock (Portfolio_Drawdown_and_Regime_Rules_v1.0).

inputs:
  positions: [{ticker, sector_id, quantity, price, fx_to_base (=1), price_12m_max, role}]
  cash: [{amount, fx_to_base (=1)}]
  nav_running_max: float|None  (исторический максимум NAV; если None — текущий NAV)
  sector_benchmarks: {sector_id: {index, index_12m_max}}  (сектора без benchmark исключаются из знаменателя)
  severity: {WATCH: -0.15, STRESS: -0.25, SHOCK: -0.40}; regime_rules — v1.0 по умолчанию (переопределяемы)
  limits: {single_name_max_weight, sector_max_weight, ...} — проверка нарушений, если заданы
  sector_overrides (1.1.0): [{sector_id, min_weight, dd_threshold, regime_floor}] — floor режима по концентрации сектора
  (AI_COMPUTE_Sector_Benchmark_Specification_v1.0 §8); sector_benchmarks[sid].quality — пробрасывается в benchmark_quality
outputs: nav, weights, drawdowns (по позициям, портфелю, секторам), weighted_sector_drawdown + benchmark_coverage,
  breadth, regime, constraint_breaches. Детерминированно, seed не используется. Не торговый сигнал (§10).
"""
from __future__ import annotations

VERSION = "1.1.0"
DEFAULT_SEVERITY = {"WATCH": -0.15, "STRESS": -0.25, "SHOCK": -0.40}
DEFAULT_REGIME = {  # model_assumption v1.0
    "stress": {"portfolio_dd": -0.15, "sector_dd": -0.20, "breadth_dd": -0.25, "breadth_frac": 0.25},
    "shock": {"portfolio_dd": -0.30, "sector_dd": -0.35, "breadth_dd": -0.40, "breadth_frac": 0.25},
}


def run(inputs: dict, seed: int) -> dict:
    positions = inputs.get("positions") or []
    cash = inputs.get("cash") or []
    sev = {**DEFAULT_SEVERITY, **(inputs.get("severity") or {})}
    rules = inputs.get("regime_rules") or DEFAULT_REGIME
    bench = inputs.get("sector_benchmarks") or {}
    limits = inputs.get("limits") or {}

    pos_out = []
    pos_total = 0.0
    for p in positions:
        q, px, fx = float(p["quantity"]), float(p["price"]), float(p.get("fx_to_base", 1.0))
        if q < 0 or px <= 0 or fx <= 0:
            raise ValueError(f"позиция {p.get('ticker')}: quantity/price/fx должны быть положительными")
        value = q * px * fx
        pos_total += value
        mx = p.get("price_12m_max")
        dd = (px / float(mx) - 1.0) if mx else None
        pos_out.append({"ticker": p.get("ticker"), "sector_id": p.get("sector_id"), "value_base": value, "drawdown_12m": dd,
                        "severity": _severity(dd, sev) if dd is not None else None, "role": p.get("role")})
    cash_total = sum(float(c["amount"]) * float(c.get("fx_to_base", 1.0)) for c in cash)
    nav = pos_total + cash_total
    if nav <= 0:
        raise ValueError("NAV должен быть положительным")
    for po in pos_out:
        po["weight_nav"] = po["value_base"] / nav
    running_max = inputs.get("nav_running_max")
    running_max = max(float(running_max), nav) if running_max is not None else nav
    portfolio_dd = nav / running_max - 1.0

    # секторные просадки: только сектора с benchmark
    sector_weights: dict[str, float] = {}
    for po in pos_out:
        if po["sector_id"]:
            sector_weights[po["sector_id"]] = sector_weights.get(po["sector_id"], 0.0) + po["weight_nav"]
    sector_dd = {}
    covered_w = 0.0
    wsum = 0.0
    for sid, w in sector_weights.items():
        b = bench.get(sid)
        if b and b.get("index") and b.get("index_12m_max"):
            dd = float(b["index"]) / float(b["index_12m_max"]) - 1.0
            sector_dd[sid] = dd
            covered_w += w
            wsum += w * dd
        else:
            sector_dd[sid] = None
    weighted_sector_dd = (wsum / covered_w) if covered_w > 0 else None
    equity_w = sum(sector_weights.values())
    coverage = (covered_w / equity_w) if equity_w > 0 else 0.0

    # широта просадок
    dds = [po["drawdown_12m"] for po in pos_out if po["drawdown_12m"] is not None]
    n = len(dds)
    frac_le_25 = (sum(1 for d in dds if d <= rules["stress"]["breadth_dd"]) / n) if n else 0.0
    frac_le_40 = (sum(1 for d in dds if d <= rules["shock"]["breadth_dd"]) / n) if n else 0.0

    # режим: precedence Shock > Stress > Normal; секторный слой учитывается только при наличии benchmark
    sdd = weighted_sector_dd
    shock = portfolio_dd <= rules["shock"]["portfolio_dd"] or (sdd is not None and sdd <= rules["shock"]["sector_dd"]) \
        or frac_le_40 >= rules["shock"]["breadth_frac"]
    stress = (rules["shock"]["portfolio_dd"] < portfolio_dd <= rules["stress"]["portfolio_dd"]) \
        or (sdd is not None and rules["shock"]["sector_dd"] < sdd <= rules["stress"]["sector_dd"]) \
        or frac_le_25 >= rules["stress"]["breadth_frac"]
    regime_base = "Shock" if shock else ("Stress" if stress else "Normal")

    # 1.1.0: concentration override — floor режима по сектору (AI_COMPUTE_Sector_Benchmark_Specification_v1.0 §8):
    # если вес сектора в NAV >= min_weight И его просадка <= dd_threshold → режим не мягче regime_floor.
    # Только floor: просадка второй раз в weighted_sector_dd не добавляется (no_double_count).
    rank = {"Normal": 0, "Stress": 1, "Shock": 2}
    floors_applied = []
    for ov in inputs.get("sector_overrides") or []:
        sid = ov.get("sector_id")
        w = sector_weights.get(sid, 0.0)
        dd = sector_dd.get(sid)
        if dd is None:
            continue
        if w >= float(ov["min_weight"]) and dd <= float(ov["dd_threshold"]):
            floors_applied.append({"sector_id": sid, "weight": round(w, 4), "drawdown": round(dd, 4), "regime_floor": ov["regime_floor"],
                                   "provenance": ov.get("provenance", "model_assumption")})
    regime = regime_base
    for f in floors_applied:
        if rank[f["regime_floor"]] > rank[regime]:
            regime = f["regime_floor"]

    breaches = []
    lim = limits.get("single_name_max_weight")
    if lim is not None:
        breaches += [{"limit": "single_name_max_weight", "ticker": po["ticker"], "weight": round(po["weight_nav"], 4), "max": lim}
                     for po in pos_out if po["weight_nav"] > float(lim)]
    lim = limits.get("sector_max_weight")
    if lim is not None:
        breaches += [{"limit": "sector_max_weight", "sector_id": s, "weight": round(w, 4), "max": lim}
                     for s, w in sector_weights.items() if w > float(lim)]
    dp_min, dp_max = limits.get("minimum_dry_powder_weight"), limits.get("maximum_dry_powder_weight")
    cash_w = cash_total / nav
    if dp_min is not None and cash_w < float(dp_min):
        breaches.append({"limit": "minimum_dry_powder_weight", "weight": round(cash_w, 4), "min": dp_min})
    if dp_max is not None and cash_w > float(dp_max):
        breaches.append({"limit": "maximum_dry_powder_weight", "weight": round(cash_w, 4), "max": dp_max})

    return {
        "nav_base": round(nav, 2), "positions_value_base": round(pos_total, 2), "cash_value_base": round(cash_total, 2),
        "cash_weight": round(cash_w, 4), "nav_running_max": round(running_max, 2),
        "positions": [{**po, "value_base": round(po["value_base"], 2), "weight_nav": round(po["weight_nav"], 4),
                       "drawdown_12m": None if po["drawdown_12m"] is None else round(po["drawdown_12m"], 4)} for po in pos_out],
        "sector_weights": {k: round(v, 4) for k, v in sector_weights.items()},
        "drawdowns": {"portfolio": round(portfolio_dd, 4), "portfolio_severity": _severity(portfolio_dd, sev),
                      "sectors": {k: (None if v is None else round(v, 4)) for k, v in sector_dd.items()},
                      "weighted_sector": None if weighted_sector_dd is None else round(weighted_sector_dd, 4),
                      "benchmark_coverage": round(coverage, 4)},
        "breadth": {"fraction_positions_dd_le_stress": round(frac_le_25, 4), "fraction_positions_dd_le_shock": round(frac_le_40, 4), "n_positions_with_dd": n},
        "regime": regime, "regime_base": regime_base, "regime_floors_applied": floors_applied,
        "regime_rules_provenance": "model_assumption v1.0",
        "benchmark_quality": {sid: b.get("quality", "external") for sid, b in bench.items() if isinstance(b, dict)},
        "constraint_breaches": breaches,
    }


def _severity(dd: float, sev: dict) -> str:
    if dd <= sev["SHOCK"]:
        return "SHOCK"
    if dd <= sev["STRESS"]:
        return "STRESS"
    if dd <= sev["WATCH"]:
        return "WATCH"
    return "NONE"
