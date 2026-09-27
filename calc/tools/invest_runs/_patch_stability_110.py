"""portfolio_stability 1.1.0: независимые прогоны возмущений (OFAT, корреляции, combined, LOO) — задачи для пула процессов
(spawn, по одному потоку BLAS на процесс); последовательный режим при workers=1. Результаты и статистика — те же."""
from pathlib import Path

p = Path("C:/openclaw-lab/calc/engine/portfolio_stability.py"); s = p.read_text(encoding="utf-8")


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]; s = s.replace(old, new)


rep('VERSION = "1.0.2"', 'VERSION = "1.1.0"')
rep('''Серия идёт на первых max_paths совместных путях (по умолчанию 100000) — допущение скорости; центральный прогон внутри теста
считается на той же выборке, внешний нормативный (500k) указывается ссылкой central_run_ref и сравнивается по весам.''',
    '''Серия идёт на первых max_paths совместных путях (по умолчанию 100000) — допущение скорости; центральный прогон внутри теста
считается на той же выборке, внешний нормативный (500k) указывается ссылкой central_run_ref и сравнивается по весам.
Исполнение (1.1.0): возмущения независимы → задачи пула процессов (spawn, OPENBLAS/OMP/MKL_NUM_THREADS=1 в потомках; каждый
потомок загружает пути из файлов один раз); stability.workers (по умолчанию cpu−2, не более 12); workers=1 — последовательно
в процессе. Порядок задач и seed'ы фиксированы → результат не зависит от числа процессов.''')
rep('''                       "loo_min_weight": 0.05, "inclusion_threshold": 0.01,''', '''                       "loo_min_weight": 0.05, "inclusion_threshold": 0.01, "workers": null,''')
rep('''import hashlib
import json

import numpy as np
''', '''import hashlib
import json
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
''')
rep('''            "combined_corr_delta": 0.10, "objective_sign_reference": "median_CAGR_5Y"}''', '''            "combined_corr_delta": 0.10, "objective_sign_reference": "median_CAGR_5Y", "workers": None}''')

# ---- воркеры: вставка перед разделом run
rep('''# ------------------------------------------------------------------------------------------------------------------------ run
def run(inputs: dict, seed: int) -> dict:''', '''# ------------------------------------------------------------------------------------------------------- задачи и пул процессов
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
def run(inputs: dict, seed: int) -> dict:''')

# ---- тело run: от fam до статистики
start = s.index("    fam = set(cfg.get(\"families\") or FAMILIES)")
end = s.index("    # --- §5–7 статистика")
body = '''    fam = set(cfg.get("families") or FAMILIES)
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
'''
s = s[:start] + body + s[end:]
rep('''            "central_weights": cw, "partial": partial, "families": sorted(fam), "runs_total": total,''', '''            "central_weights": cw, "partial": partial, "families": sorted(fam), "workers": workers, "runs_total": total,''')
p.write_text(s, encoding="utf-8", newline="\n")
import ast; ast.parse(s); print("engine 1.1.0 patched")

# тесты: пул из 2 процессов в основном тесте, последовательный режим в частичном; равенство результатов
t = Path("C:/openclaw-lab/calc/tests/test_portfolio_stability.py"); u = t.read_text(encoding="utf-8")
old = '''                       "central_run_ref": "ref-run"}}
    d.update(over); return d'''
new = '''                       "central_run_ref": "ref-run", "workers": 2}}
    d.update(over); return d'''
assert u.count(old) == 1; u = u.replace(old, new)
old2 = '''    assert again["assumptions_hash"] == out["assumptions_hash"] and again["inclusion_frequency_by_asset"] == out["inclusion_frequency_by_asset"] and again["combined"]["runs_detail"] == out["combined"]["runs_detail"]'''
new2 = old2 + '''
    # последовательный режим (workers=1) даёт тот же результат, что пул из 2 процессов
    seq = ps.run(_inputs(paths, stability={**_inputs(paths)["stability"], "workers": 1}), 11)
    assert seq["workers"] == 1 and out["workers"] == 2
    assert seq["inclusion_frequency_by_asset"] == out["inclusion_frequency_by_asset"] and seq["weight_p10_p50_p90"] == out["weight_p10_p50_p90"]
    assert seq["combined"]["runs_detail"] == out["combined"]["runs_detail"] and seq["leave_one_out"] == out["leave_one_out"] and seq["correlation_sensitivity"] == out["correlation_sensitivity"]'''
assert u.count(old2) == 1; u = u.replace(old2, new2)
t.write_text(u, encoding="utf-8", newline="\n"); print("tests patched")
