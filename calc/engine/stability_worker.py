"""Обёртка задач пула процессов Stability Test. Отдельный модуль, который сайдкар НЕ перезагружает (engine/registry.py делает
importlib.reload только для моделей): ссылки на функции, передаваемые в ProcessPoolExecutor, должны быть теми же объектами, что в
sys.modules, иначе pickle отказывает («not the same object»), когда параллельный запрос перезагрузил portfolio_stability."""
from __future__ import annotations


def init(inputs: dict, n: int, cw: dict, cdp: float) -> None:
    from engine import portfolio_stability as ps
    ps._worker_init(inputs, n, cw, cdp)


def task(t: dict) -> dict:
    from engine import portfolio_stability as ps
    return ps._run_task(t)
