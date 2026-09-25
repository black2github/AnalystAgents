"""Реестр моделей движка: имя → {version, fn(inputs, seed) -> outputs, doc}."""
from __future__ import annotations

import importlib

from engine import artifact_validator, company_mc, conditional_mc, conviction_overlay, joint_layer, milestone_mc, portfolio_optimizer, portfolio_paths, portfolio_regime, portfolio_stability, reverse_valuation, selftest, synthetic_basket, valuation_multiple

importlib.reload(selftest)
importlib.reload(valuation_multiple)
importlib.reload(reverse_valuation)
importlib.reload(portfolio_regime)
importlib.reload(conditional_mc)
importlib.reload(synthetic_basket)
importlib.reload(conviction_overlay)
importlib.reload(joint_layer)   # зависимости company_mc — тоже перезагружать, иначе в процессе сайдкара остаётся старый модуль
importlib.reload(milestone_mc)
importlib.reload(company_mc)
importlib.reload(portfolio_paths)
importlib.reload(portfolio_optimizer)
importlib.reload(portfolio_stability)
importlib.reload(artifact_validator)

MODELS = {
    "portfolio_stability": {
        "version": portfolio_stability.VERSION,
        "fn": portfolio_stability.run,
        "doc": portfolio_stability.__doc__.strip().splitlines()[0],
    },
    "portfolio_optimizer": {
        "version": portfolio_optimizer.VERSION,
        "fn": portfolio_optimizer.run,
        "doc": portfolio_optimizer.__doc__.strip().splitlines()[0],
    },
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
    "portfolio_paths": {
        "version": portfolio_paths.VERSION,
        "fn": portfolio_paths.run,
        "doc": portfolio_paths.__doc__.strip().splitlines()[0],
    },
    "artifact_validator": {
        "version": artifact_validator.VERSION,
        "fn": artifact_validator.run,
        "doc": artifact_validator.__doc__.strip().splitlines()[0],
    },
}
