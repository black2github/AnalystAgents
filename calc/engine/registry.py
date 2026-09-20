"""Реестр моделей движка: имя → {version, fn(inputs, seed) -> outputs, doc}."""
from __future__ import annotations

import importlib

from engine import reverse_valuation, selftest, valuation_multiple

importlib.reload(selftest)
importlib.reload(valuation_multiple)
importlib.reload(reverse_valuation)

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
}
