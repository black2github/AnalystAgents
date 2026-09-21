"""Синтетический секторный индекс v1.0: равновзвешенная корзина с квартальной ребалансировкой и chain-link
(AI_COMPUTE_Sector_Benchmark_Specification_v1.0, 21.09.2026). Нужен для секторной просадки в portfolio_regime,
не для оценки/alpha.

inputs:
  constituents: [{ticker, weight (опционально; по умолчанию равные), series: [[date "YYYY-MM-DD", adjusted_close], ...]}]
  initial_level: 1000; lookback_days: 365; max_carry_forward_days: 1 (дольше — benchmark_status=degraded)
  rebalance: "quarterly" (первый торговый день после конца календарного квартала) | "none"
  tail: сколько последних точек индекса вернуть (по умолчанию 30)
outputs: index_last, index_12m_max, drawdown_12m, inception, rebalances, benchmark_status (ok|degraded), gaps,
  series_tail. Детерминированно, seed не используется.
"""
from __future__ import annotations

from datetime import date

VERSION = "1.0.0"
SPEC_VERSION = "1.0"


def _d(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def run(inputs: dict, seed: int) -> dict:
    cons = inputs.get("constituents") or []
    if not cons:
        raise ValueError("constituents пуст")
    level0 = float(inputs.get("initial_level", 1000.0))
    lookback = int(inputs.get("lookback_days", 365))
    max_cf = int(inputs.get("max_carry_forward_days", 1))
    rebalance = inputs.get("rebalance", "quarterly")
    n = len(cons)
    weights = [float(c.get("weight", 1.0 / n)) for c in cons]
    wsum = sum(weights)
    if wsum <= 0:
        raise ValueError("сумма весов должна быть положительной")
    weights = [w / wsum for w in weights]
    tables = []
    for c in cons:
        t = {}
        for row in c.get("series") or []:
            dt, px = row[0], row[1]
            if px is None:
                continue
            px = float(px)
            if px <= 0:
                raise ValueError(f"{c.get('ticker')}: цена должна быть положительной ({dt})")
            t[_d(dt)] = px
        if not t:
            raise ValueError(f"{c.get('ticker')}: пустая ценовая история")
        tables.append(t)
    dates = sorted(set().union(*[set(t) for t in tables]))
    # inception — первая дата, где у всех есть цена
    inception = next((d for d in dates if all(d in t for t in tables)), None)
    if inception is None:
        raise ValueError("нет даты, на которую у всех компонентов есть цена")
    dates = [d for d in dates if d >= inception]

    last_px = [t[inception] for t in tables]
    miss_run = [0] * n
    gaps = []
    degraded = False
    base_px = list(last_px)
    idx_at_reb = level0
    series = []
    rebalances = [inception.isoformat()]
    prev_q = (inception.year, (inception.month - 1) // 3)
    for i, d in enumerate(dates):
        for k, t in enumerate(tables):
            if d in t:
                last_px[k] = t[d]
                miss_run[k] = 0
            else:
                miss_run[k] += 1
                if miss_run[k] > max_cf:
                    degraded = True
                    gaps.append({"ticker": cons[k].get("ticker"), "date": d.isoformat(), "consecutive_missing": miss_run[k]})
        q = (d.year, (d.month - 1) // 3)
        if i > 0 and rebalance == "quarterly" and q != prev_q:
            # первый торговый день нового квартала: chain-link, новые базовые цены
            idx_at_reb = idx_at_reb * sum(w * p / b for w, p, b in zip(weights, last_px, base_px))
            base_px = list(last_px)
            rebalances.append(d.isoformat())
        prev_q = q
        val = idx_at_reb * sum(w * p / b for w, p, b in zip(weights, last_px, base_px))
        series.append((d, val))
    last_d, last_v = series[-1]
    window = [v for d, v in series if (last_d - d).days <= lookback]
    mx = max(window)
    tail = int(inputs.get("tail", 30))
    return {
        "model_version": VERSION, "spec_version": SPEC_VERSION,
        "constituents": [{"ticker": c.get("ticker"), "weight": round(w, 6)} for c, w in zip(cons, weights)],
        "inception": inception.isoformat(), "as_of": last_d.isoformat(), "n_dates": len(series),
        "rebalances": rebalances, "benchmark_status": "degraded" if degraded else "ok", "gaps": gaps,
        "index_last": round(last_v, 4), "index_12m_max": round(mx, 4), "drawdown_12m": round(last_v / mx - 1.0, 4),
        "series_tail": [[d.isoformat(), round(v, 4)] for d, v in series[-tail:]],
        "note": "секторный индикатор просадки; не valuation/alpha benchmark (спецификация §1)",
    }
