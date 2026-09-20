"""KPI-10: мультипликатор капитализации к выручке за 12 месяцев (market cap / TTM revenue).

inputs: {"price": 152.71, "shares_outstanding": 13.55e9, "ttm_revenue_usd": 23.04e9,
         "thresholds": {"green_below": 30, "yellow_below": 60}}   # red: >= yellow_below
outputs: market_cap_usd, ps_multiple, color (green|yellow|red), inputs echo. Детерминированно, seed не используется.
"""
from __future__ import annotations

VERSION = "0.1.0"


def run(inputs: dict, seed: int) -> dict:
    price = float(inputs["price"])
    shares = float(inputs["shares_outstanding"])
    ttm = float(inputs["ttm_revenue_usd"])
    if price <= 0 or shares <= 0 or ttm <= 0:
        raise ValueError("price, shares_outstanding, ttm_revenue_usd must be positive")
    th = inputs.get("thresholds") or {}
    g = float(th.get("green_below", 30))
    y = float(th.get("yellow_below", 60))
    cap = price * shares
    ps = cap / ttm
    color = "green" if ps < g else ("yellow" if ps < y else "red")
    return {
        "market_cap_usd": cap,
        "market_cap_usd_b": round(cap / 1e9, 2),
        "ps_multiple": round(ps, 2),
        "color": color,
        "thresholds": {"green_below": g, "yellow_below": y},
        "inputs": {"price": price, "shares_outstanding": shares, "ttm_revenue_usd": ttm},
    }
