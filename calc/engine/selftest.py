"""Проверочная модель: Монте-Карло геометрического роста одной позиции.

Не инвестиционная модель, а тест каркаса: детерминизм по seed, форма выхода (median CAGR, P(2x), P(5x),
downside, max drawdown) — та же, что потребует спецификация расчётов.
inputs: {"years": 5, "mu": 0.15, "sigma": 0.35, "paths": 20000, "start": 100.0}
"""
from __future__ import annotations

import numpy as np

VERSION = "0.1.0"


def run(inputs: dict, seed: int) -> dict:
    years = int(inputs.get("years", 5))
    mu = float(inputs.get("mu", 0.15))
    sigma = float(inputs.get("sigma", 0.35))
    paths = int(inputs.get("paths", 20_000))
    start = float(inputs.get("start", 100.0))
    steps = years * 12
    rng = np.random.default_rng(seed)
    dt = 1.0 / 12.0
    # логнормальные месячные приращения
    z = rng.standard_normal((paths, steps))
    incr = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
    log_paths = np.cumsum(incr, axis=1)
    values = start * np.exp(log_paths)
    final = values[:, -1]
    cagr = (final / start) ** (1.0 / years) - 1.0
    running_max = np.maximum.accumulate(np.concatenate([np.full((paths, 1), start), values], axis=1), axis=1)
    drawdown = 1.0 - np.concatenate([np.full((paths, 1), start), values], axis=1) / running_max
    max_dd = drawdown.max(axis=1)
    return {
        "years": years,
        "paths": paths,
        "median_cagr": float(np.median(cagr)),
        "p10_cagr": float(np.percentile(cagr, 10)),
        "p90_cagr": float(np.percentile(cagr, 90)),
        "p_2x": float(np.mean(final >= 2 * start)),
        "p_5x": float(np.mean(final >= 5 * start)),
        "p_loss": float(np.mean(final < start)),
        "downside_p5_multiple": float(np.percentile(final / start, 5)),
        "median_max_drawdown": float(np.median(max_dd)),
    }
