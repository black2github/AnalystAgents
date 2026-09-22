"""Реестр моделей движка: имя → {version, fn(inputs, seed) -> outputs, doc}."""
from __future__ import annotations

import importlib

from engine import company_mc, conditional_mc, conviction_overlay, portfolio_regime, reverse_valuation, selftest, synthetic_basket, valuation_multiple

importlib.reload(selftest)
importlib.reload(valuation_multiple)
importlib.reload(reverse_valuation)
importlib.reload(portfolio_regime)
importlib.reload(conditional_mc)
importlib.reload(synthetic_basket)
importlib.reload(conviction_overlay)
importlib.reload(company_mc)

MODELS = {
    "selftest": {
        "version": selftest.VERSION,
        "fn": selftest.run,
        "doc": selftest.__doc__.strip().splitlines()[0],
    },
    "valuation_multiple": {
        "version": valuation_multiple.VERSION,
        "fn": valuation_multiple.run,
        "doc": valuation_multiple.__doc__.strip().splitlines()[0],
    },
    "reverse_valuation": {
        "version": reverse_valuation.VERSION,
        "fn": reverse_valuation.run,
        "doc": reverse_valuation.__doc__.strip().splitlines()[0],
    },
    "portfolio_regime": {
        "version": portfolio_regime.VERSION,
        "fn": portfolio_regime.run,
        "doc": portfolio_regime.__doc__.strip().splitlines()[0],
    },
    "conditional_mc": {
        "version": conditional_mc.VERSION,
        "fn": conditional_mc.run,
        "doc": conditional_mc.__doc__.strip().splitlines()[0],
    },
    "synthetic_basket": {
        "version": synthetic_basket.VERSION,
        "fn": synthetic_basket.run,
        "doc": synthetic_basket.__doc__.strip().splitlines()[0],
    },
    "conviction_overlay": {
        "version": conviction_overlay.VERSION,
        "fn": conviction_overlay.run,
        "doc": conviction_overlay.__doc__.strip().splitlines()[0],
    },
    "company_mc": {
        "version": company_mc.VERSION,
        "fn": company_mc.run,
        "doc": company_mc.__doc__.strip().splitlines()[0],
    },
}
