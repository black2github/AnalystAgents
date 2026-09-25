"""Portfolio Stability Test v1.0 (Portfolio_Stability_Test_Specification_v1.0, схема v1.0): устойчивость включения и веса бумаг
к малым правдоподобным изменениям предпосылок — серия повторных прогонов portfolio_optimizer на возмущённых совместных путях.

Центральный прогон = optimizer на тех же входах (тёплый старт «current», как в нормативном прогоне). Каждое возмущение меняет
ровно один слой (§2), возмущённые пути живут в памяти, на диск не пишутся. Слои v1.0.0 (все величины — model_assumption):
- return: сдвиг медианного CAGR ±3 / ±5 п.п. по компании — масштаб относительной стоимости пути (1+δ)^h на всех горизонтах (§3.1);
- terminal multiple ±20 %: лог-множитель к стоимости пути на всех горизонтах (§3.4; точно для базы FCF_multiple, прокси для смеси);
- terminal margin ±5 п.п.: ПРОКСИ на уровне пути — масштаб (m+δ)/m по терминальной марже калибровки (inputs.terminal_margins) на
  горизонтах Y5/Y8; без терминальной маржи — not_testable; точная пересимуляция company_mc — следующий срез;
- correlations ±0.10 / ±0.15: переспаривание путей методом Имана–Коновера под целевую ранговую корреляцию стоимостей Y5
  (маргиналы сохраняются, горизонты внутри компании переставляются вместе); PSD-ремонт (обрезка собственных чисел) логируется;
  нулевое δ прогоняется отдельно как контроль шума самого метода;
- scenario probabilities: единственный сценарий BASE → not_applicable (§3.3);
- milestones ±10 п.п. и driver knockout (§3.5): на уровне пути не воспроизводятся → not_testable (пересимуляция — следующий срез);
  материальные драйверы (взвешенная |экспозиция| ≥ 0.30) перечисляются по inputs.driver_exposures;
- leave-one-company-out: позиции с центральным весом ≥ 5 % исключаются по одной (потолок 0), optimizer заново на трёх стартах
  (given/equal/empty: одиночный тёплый старт из точки, нарушающей потолки после удаления бумаги, застревал — 1.0.1) (§3.6);
  к каждому LOO и к центру — линейная проверка ёмкости (1.0.2, scipy.linprog): максимум размещаемого Σw при потолках, общих
  причинах и секторах против минимума budget − dry_powder_hard_max; если максимум ниже — недопустимость структурная, а не
  недоработка поиска;
- combined: латинский гиперкуб N (по умолчанию 500) по измерениям [return ±3 п.п., multiple ±20 %, margin ±5 п.п.] × компании
  + общий сдвиг корреляций ±0.10; фиксированный seed.
Популяция для §5–6 (включение, веса): однофакторные + корреляционные + combined прогоны, ДОПУСТИМЫЕ (valid = feasible);
LOO-прогоны в статистику бумаг не входят (там исключение задано конструкцией) — отдельный блок структурной зависимости.
Серия идёт на первых max_paths совместных путях (по умолчанию 100000) — допущение скорости; центральный прогон внутри теста
считается на той же выборке, внешний нормативный (500k) указывается ссылкой central_run_ref и сравнивается по весам.
Исполнение (1.1.0): возмущения независимы → задачи пула процессов (spawn, OPENBLAS/OMP/MKL_NUM_THREADS=1 в потомках; каждый
потомок загружает пути из файлов один раз); stability.workers (по умолчанию cpu−2, не более 12); workers=1 — последовательно
в процессе. Порядок задач и seed'ы фиксированы → результат не зависит от числа процессов.

inputs: всё, что принимает portfolio_optimizer (paths_files, weights_current, fixed_weights, limits, per_name_caps, …) +
        {"stability": {"combined_runs": 500, "max_paths": 100000, "search_paths": 100000, "terminal_margins": {tk: m5},
                       "driver_exposures": {tk: {driver: ±2|±1}}, "milestone_companies": [tk], "central_run_ref": run_id|null,
                       "return_shift_pp": [3, 5], "multiple_pct": 0.20, "margin_pp": 0.05, "corr_delta": [0.10, 0.15],
                       "loo_min_weight": 0.05, "inclusion_threshold": 0.01, "workers": null,
                       "families": null | ["return_shift","terminal","correlation","combined","loo"] (частичный перепрогон: partial=true)}}
outputs: §10 — central_weights, inclusion_frequency_by_asset, weight_p10_p50_p90, weight_spread, return/terminal/correlation/
  scenario/driver sensitivity, feasibility_rate, turnover_distribution, binding_constraint_frequency, company_stability_classification,
  portfolio_stability_classification (критерии по отдельности + not_evaluated), leave_one_out, mpc_robustness_mapping (null: нужен
  кандидат), assumptions_hash, perturbation config, decision: none.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from engine import portfolio_optimizer as po
from engine import portfolio_paths

VERSION = "1.1.0"
HKEYS = (("r3", 3), ("r5", 5), ("r8", 8))
DEFAULTS = {"combined_runs": 500, "max_paths": 100_000, "search_paths": 100_000, "return_shift_pp": [3, 5], "multiple_pct": 0.20, "margin_pp": 0.05,
            "corr_delta": [0.10, 0.15], "loo_min_weight": 0.05, "inclusion_threshold": 0.01, "material_driver_min": 0.30, "combined_return_pp": 3,
            "combined_corr_delta": 0.10, "objective_sign_reference": "median_CAGR_5Y", "workers": None}
FAMILIES = ("return_shift", "terminal", "correlation", "combined", "loo")


# ----------------------------------------------------------------------------------------------------------- возмущения путей
def _copy(data: dict, n: int) -> dict:
    return {t: {"meta": d["meta"], "path_id": d["path_id"][:n], "maxdd5": d["maxdd5"][:n], **{k: d[k][:n].astype(np.float32) for k, _ in HKEYS}} for t, d in data.items()}


def _scale(data: dict, t: str, factors: dict) -> None:
    """Умножить стоимости компании t на множитель по горизонту (in place, по возмущённой копии)."""
    for k, f in factors.items():
        data[t][k] = (data[t][k].astype(np.float64) * f).astype(np.float32)


def _rank_corr(data: dict, tick: list) -> np.ndarray:
    R = np.stack([data[t]["r5"].astype(np.float64) for t in tick], axis=1)
    ranks = np.argsort(np.argsort(R, axis=0), axis=0).astype(np.float64)
    return np.corrcoef(ranks, rowvar=False)


def _nearest_psd(C: np.ndarray) -> tuple[np.ndarray, bool]:
    vals, vecs = np.linalg.eigh(C)
    if vals.min() > 1e-8:
        return C, False
    vals = np.clip(vals, 1e-6, None)
    M = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(M))
    M = M / np.outer(d, d)
    np.fill_diagonal(M, 1.0)
    return M, True


def _iman_conover(data: dict, tick: list, target: np.ndarray, seed: int) -> None:
    """Переупорядочить пути каждой компании так, чтобы ранговая корреляция стоимостей Y5 стала ≈ target (маргиналы сохранены;
    r3/r5/r8/maxdd5 компании переставляются одной перестановкой — горизонты внутри пути согласованы)."""
    n = len(data[tick[0]]["r5"]); k = len(tick)
    rng = np.random.default_rng(seed)
    # баллы — отсортированные стандартные нормальные розыгрыши (аналог van der Waerden), по столбцу — своя перестановка (seed фиксирован)
    z = np.sort(rng.standard_normal(n))
    M = np.column_stack([z[rng.permutation(n)] for _ in range(k)])
    E = np.corrcoef(M, rowvar=False)
    F = np.linalg.cholesky(E); Q = np.linalg.cholesky(target)
    Ms = M @ np.linalg.inv(F).T @ Q.T
    for j, t in enumerate(tick):
        order_target = np.argsort(np.argsort(Ms[:, j]))            # ранг, который должен занять i-й путь
        order_vals = np.argsort(data[t]["r5"])                      # индексы путей по возрастанию r5
        perm = order_vals[order_target]                              # путь на позиции i получает значения пути с рангом order_target[i]
        for key in ("r3", "r5", "r8", "maxdd5"):
            data[t][key] = data[t][key][perm]


# ------------------------------------------------------------------------------------------------------------- прогон optimizer
def _opt(inputs: dict, data: dict, start_w: dict | None, start_dp: float | None) -> dict:
    inp = dict(inputs)
    inp.pop("stability", None)
    if start_w is not None:
        inp["starts"] = ["given"]; inp["start_weights"] = start_w; inp["start_dry_powder"] = start_dp
    else:
        inp["starts"] = ["current"]
    r = po.run(inp, 0, data=data)
    y5 = r["portfolio_return_distribution"]["Y5"]; d5 = r["portfolio_downside"]["Y5"]
    return {"feasible": bool(r["feasible"]), "weights": r["proposed_weights"], "dry_powder": r["dry_powder_weight"], "median_CAGR_5Y": y5["median_CAGR"],
            "ES5": d5["expected_shortfall_5pct"], "P_loss_gt_30pct_5Y": d5["P_loss_gt_30pct"], "binding": r["binding_constraints"],
            "violations": [v["constraint"] for v in r["violations_at_optimum"]], "turnover_from_current": r["turnover_from_current"]}


def _capacity(inputs: dict, tick: list, excluded: str | None) -> dict | None:
    """Линейная задача: max Σw при 0 ≤ w ≤ cap, общие причины ≤ cc_max (с вкладом фиксированных позиций), секторы ≤ sector_max.
    Сравнивается с минимумом, который надо разместить: budget − dry_powder_hard_max(режим). Топ-3 и риск-лимиты не входят
    (нелинейны/невыпуклы) — оценка сверху: если и она ниже минимума, недопустимость структурная."""
    try:
        from scipy.optimize import linprog
    except ImportError:
        return None
    caps = inputs.get("per_name_caps") or {}; cc = inputs.get("common_cause") or {}; fixed = inputs.get("fixed_weights") or {}; sectors = inputs.get("sectors") or {}
    L = inputs.get("limits") or {}; regime = inputs.get("regime") or "Normal"
    dp = (L.get("dry_powder") or {}).get(regime) or {"hard_max": 0.15}
    names = [t for t in tick if t != excluded and (inputs.get("roles") or {}).get(t) != "Watch"]
    budget = 1.0 - float(sum(float(v) for v in fixed.values())); need = budget - float(dp["hard_max"])
    A, b = [], []
    if L.get("common_cause_effective_max") is not None:
        for cause, m in cc.items():
            A.append([float(m.get(t, 0.0)) for t in names]); b.append(float(L["common_cause_effective_max"]) - sum(float(fixed.get(t, 0.0)) * float(f) for t, f in m.items() if t in fixed))
    if L.get("sector_max") is not None:
        for sct in sorted({sectors.get(t, "UNMAPPED") for t in list(names) + list(fixed)}):
            A.append([1.0 if sectors.get(t, "UNMAPPED") == sct else 0.0 for t in names]); b.append(float(L["sector_max"]) - sum(float(w) for t, w in fixed.items() if sectors.get(t, "UNMAPPED") == sct))
    bounds = [(0.0, float(caps[t]) if caps.get(t) is not None else float((inputs.get("mpc_range") or {}).get("max_weight", 0.20))) for t in names]
    if A:
        r = linprog(-np.ones(len(names)), A_ub=np.array(A), b_ub=np.array(b), bounds=bounds, method="highs")
        if not r.success:
            return {"status": "lp_failed", "message": str(r.message)}
        mx = float(-r.fun); w = {t: round(float(x), 4) for t, x in zip(names, r.x)}
    else:
        mx = float(sum(bd[1] for bd in bounds)); w = {t: bd[1] for t, bd in zip(names, bounds)}
    return {"lp_max_placeable": round(mx, 4), "required_min_placed": round(need, 4), "headroom": round(mx - need, 4), "structurally_infeasible": bool(mx < need - 1e-9), "argmax_weights": w,
            "note": "оценка сверху без топ-3 и риск-лимитов; structurally_infeasible=true доказывает недопустимость, false её не гарантирует"}


def _turnover(w: dict, dp: float, w0: dict, dp0: float) -> float:
    keys = set(w) | set(w0)
    return float(0.5 * (sum(abs(w.get(t, 0.0) - w0.get(t, 0.0)) for t in keys) + abs(dp - dp0)))


def _q(x: list, q: float) -> float:
    return float(np.quantile(np.array(x, dtype=float), q)) if x else float("nan")


# ------------------------------------------------------------------------------------------------------- задачи и пул процессов
_W: dict = {}   # состояние процесса-исполнителя (или главного процесса при workers=1)


def _worker_init(inputs: dict, n: int, cw: dict, cdp: float) -> None:
    files = inputs["paths_files"]; tick = sorted(files)
    base = _copy({t: portfolio_paths.load_paths(files[t]) for t in tick}, n)
    _W.update({"inp": inputs, "n": n, "tick": tick, "base": base, "cw": cw, "cdp": cdp})


def _apply_ops(d: dict, ops: list, tick: list) -> dict:
    for op in ops:
        if op[0] == "scale":
            _scale(d, op[1], op[2])
        elif op[0] == "corr":
            _iman_conover(d, tick, np.array(op[1], dtype=float), int(op[2]))
    return d


def _run_task(task: dict) -> dict:
    inp, n, tick, base, cw, cdp = (_W[k] for k in ("inp", "n", "tick", "base", "cw", "cdp"))
    d = _apply_ops(_copy(base, n), task["ops"], tick)
    if task["family"] == "loo":
        t = task["exclude"]; inp2 = dict(inp); inp2.pop("stability", None)
        caps = dict(inp2.get("per_name_caps") or {}); caps[t] = 0.0; inp2["per_name_caps"] = caps
        sw = dict(cw); sw[t] = 0.0
        r = po.run({**inp2, "starts": ["given", "equal", "empty"], "start_weights": sw, "start_dry_powder": cdp}, 0, data=d)
        res = {"feasible": bool(r["feasible"]), "start_used": r["start_used"], "weights": r["proposed_weights"], "dry_powder": r["dry_powder_weight"],
               "median_CAGR_5Y": r["portfolio_return_distribution"]["Y5"]["median_CAGR"], "ES5": r["portfolio_downside"]["Y5"]["expected_shortfall_5pct"],
               "violations": [v["constraint"] for v in r["violations_at_optimum"]], "binding": r["binding_constraints"]}
    else:
        res = _opt(inp, d, cw, cdp)
        if task.get("measure_corr"):
            res["achieved_C1"] = _rank_corr(d, tick).tolist()
    res.update({"family": task["family"], "label": task["label"], "layer": task["layer"], "key": task["key"], "turnover_from_central": _turnover(res["weights"], res["dry_powder"], cw, cdp)})
    return res


def _execute(tasks: list, inputs: dict, n: int, cw: dict, cdp: float, workers: int) -> list:
    if workers <= 1 or len(tasks) <= 1:
        _worker_init(inputs, n, cw, cdp)
        return [_run_task(t) for t in tasks]
    keys = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"); backup = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = "1"                                            # потомки (spawn) стартуют с одним потоком BLAS — без оверсабскрипшна
    try:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks)), mp_context=mp.get_context("spawn"), initializer=_worker_init, initargs=(inputs, n, cw, cdp)) as ex:
            return list(ex.map(_run_task, tasks, chunksize=1))
    finally:
        for k, v in backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------------------------------------------------------------------------------ run
def run(inputs: dict, seed: int) -> dict:
    cfg = {**DEFAULTS, **(inputs.get("stability") or {})}
    files = inputs.get("paths_files") or {}
    tick = sorted(files)
    if not tick:
        raise ValueError("paths_files пуст")
    base = {t: portfolio_paths.load_paths(files[t]) for t in tick}
    n = min(min(len(d["r5"]) for d in base.values()), int(cfg["max_paths"]))
    base = _copy(base, n)
    inp = dict(inputs); inp["max_paths"] = n; inp["search_paths"] = min(int(cfg["search_paths"]), n)
    margins = {t: float(m) for t, m in (cfg.get("terminal_margins") or {}).items() if m is not None}
    incl_thr = float(cfg["inclusion_threshold"])

    # --- центральный прогон
    central = _opt(inp, _copy(base, n), None, None)
    cw, cdp = central["weights"], central["dry_powder"]
    if not central["feasible"]:
        raise ValueError(f"центральный прогон недопустим: {central['violations']} — Stability Test не определён")

    fam = set(cfg.get("families") or FAMILIES)
    bad = fam - set(FAMILIES)
    if bad:
        raise ValueError(f"неизвестные семейства прогонов: {sorted(bad)}; допустимы {FAMILIES}")
    partial = fam != set(FAMILIES)
    workers = cfg.get("workers")
    workers = int(workers) if workers else max(1, min(12, (os.cpu_count() or 2) - 2))
    k = len(tick)
    C0 = _rank_corr(base, tick)
    tasks: list[dict] = []

    def add(family, label, ops, layer, key, **extra):
        tasks.append({"family": family, "label": label, "ops": ops, "layer": layer, "key": key, **extra})

    # --- 3.1 сдвиги доходности
    for t in (tick if "return_shift" in fam else []):
        for pp in cfg["return_shift_pp"]:
            for sgn in (-1, 1):
                delta = sgn * pp / 100.0
                add("return_shift", f"{t}:{sgn * pp:+d}pp", [("scale", t, {kk: (1.0 + delta) ** h for kk, h in HKEYS})], {"company": t, "shift_pp": sgn * pp}, ("ret", t, f"{sgn * pp:+d}pp"))
    # --- 3.4 терминальные допущения
    term_sens = {}
    for t in (tick if "terminal" in fam else []):
        term_sens[t] = {"multiple": {}, "margin": {}, "milestone_probability": "not_testable_path_level" if t in (cfg.get("milestone_companies") or []) else "not_applicable"}
        for sgn in (-1, 1):
            f = 1.0 + sgn * float(cfg["multiple_pct"])
            add("terminal_multiple", f"{t}:x{f:.2f}", [("scale", t, {kk: f for kk, _ in HKEYS})], {"company": t, "multiple_factor": f}, ("mult", t, f"{sgn * cfg['multiple_pct'] * 100:+.0f}%"))
        m = margins.get(t)
        if m is None or m <= 0.02:
            term_sens[t]["margin"] = "not_testable" + ("" if m is None else "_margin_near_zero")
            continue
        for sgn in (-1, 1):
            delta = sgn * float(cfg["margin_pp"]); f = float(np.clip((m + delta) / m, 0.1, 3.0))
            add("terminal_margin", f"{t}:{delta * 100:+.0f}pp", [("scale", t, {"r5": f, "r8": f})], {"company": t, "margin_pp": delta, "proxy_factor": f, "terminal_margin": m}, ("margin", t, f"{delta * 100:+.0f}pp", round(f, 4)))
    # --- 3.2 корреляции
    corr_sens = {"rank_corr_Y5_base_max_offdiag": float(np.max(np.abs(C0 - np.eye(k)))), "runs": {}}
    for delta in ([0.0] + [sg * d_ for d_ in cfg["corr_delta"] for sg in (-1, 1)]) if "correlation" in fam else []:
        T = C0 + delta * (np.ones_like(C0) - np.eye(k))
        T = np.clip(T, -0.99, 0.99); np.fill_diagonal(T, 1.0)
        T, repaired = _nearest_psd(T)
        label = "zero_delta_control" if delta == 0.0 else f"{delta:+.2f}"
        add("correlation", f"corr:{label}", [("corr", T.tolist(), seed + 7919)], {"delta": delta, "psd_repaired": repaired}, ("corr", label, repaired), measure_corr=True)
    # --- 3.3 сценарии; 3.5 драйверы
    scen_sens = {"status": "not_applicable", "reason": "единственный сценарий BASE — вероятности сценариев не определены"}
    expo = cfg.get("driver_exposures") or {}
    material = []
    if expo:
        drivers = sorted({d for m in expo.values() for d in m})
        for dname in drivers:
            wabs = sum(abs(float(expo.get(t, {}).get(dname, 0.0))) / 2.0 * float(cw.get(t, 0.0)) for t in tick)
            if wabs >= float(cfg["material_driver_min"]) * sum(float(cw.get(t, 0.0)) for t in tick):
                material.append({"driver": dname, "weighted_abs_exposure_share": round(wabs / max(sum(float(cw.get(t, 0.0)) for t in tick), 1e-9), 3)})
    driver_sens = {"status": "not_testable_path_level", "reason": "выбивание драйвера требует пересимуляции company_mc с обнулённым положительным вкладом mapping — следующий срез",
                   "material_drivers": material, "material_rule": "Σ_i w_i·|exposure_i|/2 ≥ 0.30 × Σ w_i (экспозиция ±2 → 1.0, ±1 → 0.5)"}
    # --- 3.6 leave-one-company-out
    for t in (tick if "loo" in fam else []):
        if float(cw.get(t, 0.0)) < float(cfg["loo_min_weight"]):
            continue
        add("loo", f"loo:{t}", [], {"exclude": t}, ("loo", t), exclude=t)
    # --- §4 combined (LHS)
    N = int(cfg["combined_runs"]) if "combined" in fam else 0
    dims = [(t, "return") for t in tick] + [(t, "multiple") for t in tick] + [(t, "margin") for t in tick if t in margins and margins[t] > 0.02] + [("*", "corr")]
    rng = np.random.default_rng(seed)
    U = np.empty((N, len(dims)))
    for j in range(len(dims)):
        U[:, j] = (rng.permutation(N) + rng.random(N)) / N      # латинский гиперкуб: по одной точке в каждой страте
    for i in range(N):
        ops, layer = [], {}
        for j, (t, kind) in enumerate(dims):
            u = 2.0 * U[i, j] - 1.0
            if kind == "return":
                delta = u * cfg["combined_return_pp"] / 100.0; ops.append(("scale", t, {kk: (1.0 + delta) ** h for kk, h in HKEYS})); layer[f"{t}:return_pp"] = round(delta * 100, 3)
            elif kind == "multiple":
                f = 1.0 + u * float(cfg["multiple_pct"]); ops.append(("scale", t, {kk: f for kk, _ in HKEYS})); layer[f"{t}:multiple_factor"] = round(f, 4)
            elif kind == "margin":
                m = margins[t]; delta = u * float(cfg["margin_pp"]); f = float(np.clip((m + delta) / m, 0.1, 3.0)); ops.append(("scale", t, {"r5": f, "r8": f})); layer[f"{t}:margin_pp"] = round(delta * 100, 3)
            else:
                delta = u * float(cfg["combined_corr_delta"]); layer["corr_delta"] = round(delta, 4)
                T = np.clip(C0 + delta * (np.ones_like(C0) - np.eye(k)), -0.99, 0.99); np.fill_diagonal(T, 1.0); T, rep_ = _nearest_psd(T); layer["psd_repaired"] = rep_
                ops.append(("corr", T.tolist(), seed + 100_003 + i))
        add("combined", f"lhs:{i}", ops, layer, ("lhs", i))

    # --- исполнение
    results = _execute(tasks, inp, n, cw, cdp, workers)
    runs = [r for r in results if r["family"] != "loo"]   # популяция §5–6 (LOO — отдельно)
    ret_sens: dict = {}
    loo: dict = {}
    combined: list = []
    for r in results:
        key = r["key"]
        if key[0] == "ret":
            ret_sens.setdefault(key[1], {})[key[2]] = {"weight": r["weights"].get(key[1]), "feasible": r["feasible"], "median_CAGR_5Y": r["median_CAGR_5Y"], "turnover_from_central": r["turnover_from_central"]}
        elif key[0] == "mult":
            term_sens[key[1]]["multiple"][key[2]] = {"weight": r["weights"].get(key[1]), "feasible": r["feasible"], "median_CAGR_5Y": r["median_CAGR_5Y"]}
        elif key[0] == "margin":
            term_sens[key[1]]["margin"][key[2]] = {"weight": r["weights"].get(key[1]), "feasible": r["feasible"], "median_CAGR_5Y": r["median_CAGR_5Y"], "proxy_factor": key[3]}
        elif key[0] == "corr":
            C1 = np.array(r.pop("achieved_C1"))
            corr_sens["runs"][key[1]] = {"weights": r["weights"], "feasible": r["feasible"], "median_CAGR_5Y": r["median_CAGR_5Y"], "ES5": r["ES5"], "psd_repaired": key[2],
                                         "achieved_mean_offdiag_shift": float(np.mean((C1 - C0)[~np.eye(k, dtype=bool)])), "turnover_from_central": r["turnover_from_central"]}
        elif key[0] == "loo":
            t = key[1]
            loo[t] = {"feasible": r["feasible"], "start_used": r["start_used"], "capacity": _capacity(inp, tick, t), "weights": r["weights"], "dry_powder": r["dry_powder"], "median_CAGR_5Y": r["median_CAGR_5Y"],
                      "ES5": r["ES5"], "violations": r["violations"], "turnover_from_central": r["turnover_from_central"], "median_CAGR_5Y_delta_vs_central": r["median_CAGR_5Y"] - central["median_CAGR_5Y"]}
        elif key[0] == "lhs":
            combined.append({"i": key[1], "feasible": r["feasible"], "weights": r["weights"], "dry_powder": r["dry_powder"], "median_CAGR_5Y": r["median_CAGR_5Y"], "ES5": r["ES5"], "turnover_from_central": r["turnover_from_central"], "binding": r["binding"]})
    # --- §5–7 статистика
    valid = [r for r in runs if r["feasible"]]
    total = len(runs)
    feas_rate = len(valid) / total if total else None
    incl, wstats, spread, cls = {}, {}, {}, {}
    for t in tick:
        ws = [float(r["weights"].get(t, 0.0)) for r in valid]
        c = float(cw.get(t, 0.0))
        if not ws:
            incl[t] = None; wstats[t] = None; spread[t] = None; cls[t] = {"class": "not_evaluated", "central_weight": c, "note": "популяция прогонов пуста (частичный прогон)"}
            continue
        f_incl = float(np.mean([w >= incl_thr for w in ws]))
        p10, p50, p90 = _q(ws, 0.10), _q(ws, 0.50), _q(ws, 0.90)
        incl[t] = round(f_incl, 4); wstats[t] = {"p10": round(p10, 4), "p50": round(p50, 4), "p90": round(p90, 4)}; spread[t] = round(p90 - p10, 4)
        if c >= incl_thr:
            crit_spread = (p90 - p10) <= max(0.04, 0.5 * c) + 1e-9
            crit_med = abs(p50 - c) <= max(0.02, 0.25 * c) + 1e-9
            collapse = float(np.mean([w < incl_thr for w in ws])) if ws else float("nan")
            if f_incl >= 0.80 and crit_spread and crit_med:
                label = "stable"
            elif f_incl >= 0.50:
                label = "conditional"
            else:
                label = "unstable"
            cls[t] = {"class": label, "central_weight": c, "inclusion_frequency": round(f_incl, 4), "spread_ok": crit_spread, "median_deviation_ok": crit_med,
                      "spread_limit": round(max(0.04, 0.5 * c), 4), "median_deviation_limit": round(max(0.02, 0.25 * c), 4), "collapse_to_zero_frequency": round(collapse, 4)}
        else:
            cls[t] = {"class": "excluded_at_central", "central_weight": c, "inclusion_frequency": round(f_incl, 4), "note": "центральный вес < 1 % — критерии веса не применяются (§6); частота включения показывает, входит ли бумага при возмущениях"}
    turn = [r["turnover_from_central"] for r in valid]
    sign_c = np.sign(central["median_CAGR_5Y"])
    flips = float(np.mean([np.sign(r["median_CAGR_5Y"]) != sign_c for r in valid])) if valid else None
    bind_freq: dict = {}
    for r in runs:
        for b in r["binding"]:
            bind_freq[b] = bind_freq.get(b, 0) + 1
    bind_freq = {b: round(v / total, 4) for b, v in sorted(bind_freq.items(), key=lambda x: -x[1])}

    def crit(value, limit, ok):
        return {"value": (round(value, 4) if value is not None else None), "limit": limit, "pass": (bool(ok(value)) if value is not None else None)}

    t50 = _q(turn, 0.5) if turn else None; t90 = _q(turn, 0.9) if turn else None
    criteria = {"hard_constraint_feasibility": crit(feas_rate, 0.95, lambda v: v >= 0.95),
                "median_turnover_from_central": crit(t50, 0.25, lambda v: v <= 0.25),
                "p90_turnover_from_central": crit(t90, 0.50, lambda v: v <= 0.50),
                "driver_knockout_feasible_replacement": {"value": None, "pass": None, "status": "not_evaluated (driver knockout not testable at path level)"},
                "median_5y_cagr_sign_flip_fraction": crit(flips, 0.20, lambda v: v <= 0.20)}
    evaluated = [c for c in criteria.values() if c["pass"] is not None]
    port_class = ("structurally_stable" if all(c["pass"] for c in evaluated) else "not_structurally_stable") if evaluated else "not_evaluated"
    ah = hashlib.sha256(json.dumps({"inputs": {k: v for k, v in inputs.items() if k != "paths_files"}, "paths_meta": {t: base[t]["meta"] for t in tick}, "n": n, "cfg": cfg, "seed": seed, "version": VERSION},
                                   sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    fam_counts: dict = {}
    for r in runs:
        fam_counts[r["family"]] = fam_counts.get(r["family"], 0) + 1
    return {"model_version": VERSION, "spec": "Portfolio_Stability_Test_Specification_v1.0", "companies": tick, "paths_used": n, "search_paths": inp["search_paths"],
            "central_run_ref": cfg.get("central_run_ref"), "central": {"weights": cw, "dry_powder": cdp, "median_CAGR_5Y": central["median_CAGR_5Y"], "ES5": central["ES5"],
                                                                        "binding": central["binding"], "start": "current", "capacity": _capacity(inp, tick, None)},
            "central_weights": cw, "partial": partial, "families": sorted(fam), "workers": workers, "runs_total": total, "runs_by_family": fam_counts, "valid_runs": len(valid),
            "feasibility_rate": (round(feas_rate, 4) if feas_rate is not None else None),
            "inclusion_frequency_by_asset": incl, "weight_p10_p50_p90": wstats, "weight_spread": spread,
            "return_sensitivity": ret_sens, "terminal_sensitivity": term_sens, "correlation_sensitivity": corr_sens, "scenario_sensitivity": scen_sens, "driver_sensitivity": driver_sens,
            "leave_one_out": loo, "combined": {"method": "latin_hypercube", "runs": N, "dimensions": [f"{t}:{k}" for t, k in dims], "seed": seed,
                                               "feasibility_rate": round(float(np.mean([c["feasible"] for c in combined])), 4) if combined else None,
                                               "median_CAGR_5Y_quantiles": {q: round(_q([c["median_CAGR_5Y"] for c in combined if c["feasible"]], float(q)), 4) for q in ("0.1", "0.5", "0.9")} if combined else None,
                                               "runs_detail": combined},
            "turnover_distribution": ({"p10": round(_q(turn, 0.1), 4), "p50": round(_q(turn, 0.5), 4), "p90": round(_q(turn, 0.9), 4), "max": round(max(turn), 4)} if turn else None),
            "binding_constraint_frequency": bind_freq, "company_stability_classification": cls,
            "portfolio_stability_classification": {"class": port_class, "criteria": criteria, "criteria_not_evaluated": [k for k, c in criteria.items() if c["pass"] is None]},
            "mpc_robustness_mapping": None, "mpc_note": "сравнение без/с кандидатом (§8) — отдельный вызов с кандидатом; здесь не применимо",
            "perturbation_config": {k: v for k, v in cfg.items() if k not in ("driver_exposures",)}, "assumptions_hash": ah,
            "assumptions": ["серия на первых max_paths совместных путях (скорость); центральный прогон внутри теста — на той же выборке",
                            "valid_runs = допустимые прогоны; недопустимые входят только в feasibility_rate",
                            "terminal margin — прокси на уровне пути ((m+δ)/m на Y5/Y8), не пересимуляция", "terminal multiple — лог-множитель ко всем горизонтам (точно для базы FCF_multiple)",
                            "корреляции — Иман–Коновер по рангам стоимости Y5; контроль нулевого δ показывает шум переспаривания",
                            "LOO-прогоны не входят в статистику включения/весов", "milestones и driver knockout — not_testable до пересимуляции"],
            "decision": "none"}
