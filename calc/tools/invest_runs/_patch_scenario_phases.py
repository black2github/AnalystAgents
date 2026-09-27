"""Черновая поддержка сценарного слоя в движке (до спецификации IMMA; семантика будет подогнана под её текст):
joint_layer 1.1.0 — фазы сценария (effective_from число или распределение, ramp, duration, decay, after_phase), профиль m_i(t)∈[0,1]
на путь; сдвиг и множитель волатильности действуют через профиль; legacy top-level driver_overrides = одна фаза с t0 до конца.
portfolio_paths 1.1.0 — смешивание сценариев: по каждому path_id сценарий выбирается детерминированно по вероятностям,
метрики по смеси + по каждому сценарию + дельта к BASE; scenario_concentration — None до определения IMMA."""
from pathlib import Path

ROOT = Path("C:/openclaw-lab/calc")

# ---------------------------------------------------------------- joint_layer
p = ROOT / "engine/joint_layer.py"; s = p.read_text(encoding="utf-8")


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]; s = s.replace(old, new)


rep('''Сценарий (Scenario Engine): driver_overrides {mean_shift_sigma, volatility_multiplier}; без него — BASE.
"""''', '''Сценарий (Scenario Engine): driver_overrides {mean_shift_sigma, volatility_multiplier}; без него — BASE.
Фазы (1.1.0, ЧЕРНОВИК до спецификации Scenario Engine v1.0 IMMA): scenario.phases = [{phase_id, effective_from: квартал от t0
(число) или распределение {distribution: uniform|triangular, min, mode, max} (розыгрыш на путь), after_phase: id предыдущей фазы
(+ offset — число/распределение — от конца её плато), ramp_quarters, duration_quarters|null (до конца), decay_quarters,
driver_overrides}]. Профиль m_i(t) ∈ [0,1] на путь: 0 до начала, линейный подъём ramp, плато duration, линейный спад decay.
Сдвиг: x += shift·m(t); волатильность: x *= 1 + (vm − 1)·m(t); фазы суммируются (сдвиги) и перемножаются (волатильность).
Legacy top-level driver_overrides без phases = одна фаза с t0 до конца (m ≡ 1) — прежние результаты не меняются.
root_correlation_overrides по фазам — НЕ реализовано (ждём спецификацию).
"""''')
rep('VERSION = "1.0.0"', 'VERSION = "1.1.0"')
rep('''def driver_shocks(spec: dict, drivers: list[str], n: int, quarters: int, seed: int, antithetic: bool = True,
                  scenario: dict | None = None):
    """dict driver → (n, quarters) стандартизированных шоков. Драйвер без mapping — чисто идиосинкратический."""
    ids, F = root_paths(spec, n, quarters, seed, antithetic)
    ids_i = {k: i for i, k in enumerate(ids)}
    _, R, _ = root_correlation(spec)
    maps = (spec.get("driver_generation") or {}).get("mappings") or {}
    rng = np.random.default_rng(seed + 7919)  # отдельный поток для идиосинкратических шоков драйверов (детерминирован seed'ом)
    out = {}
    ov = (scenario or {}).get("driver_overrides") or {}
    for d in drivers:''', '''def _draw_quarters(spec_v, n: int, rng: np.random.Generator) -> np.ndarray:
    """Розыгрыш квартала на путь: число → константа; {distribution: uniform|triangular, min, mode, max} → вектор (n,)."""
    if spec_v is None:
        return np.zeros(n)
    if isinstance(spec_v, (int, float)):
        return np.full(n, float(spec_v))
    dist = str(spec_v.get("distribution", "triangular")).lower()
    lo, hi = float(spec_v["min"]), float(spec_v["max"])
    if dist == "uniform":
        return rng.uniform(lo, hi, n)
    return rng.triangular(lo, float(spec_v.get("mode", 0.5 * (lo + hi))), hi, n)


def scenario_profiles(scenario: dict | None, n: int, quarters: int, seed: int) -> list[dict]:
    """Список фаз сценария с профилями m (n, quarters) ∈ [0,1] и стартами (n,). Legacy driver_overrides → одна фаза m ≡ 1.
    Детерминировано по seed (отдельный поток seed + 104_729)."""
    if not scenario:
        return []
    phases = scenario.get("phases")
    if not phases:
        ov = scenario.get("driver_overrides") or {}
        return [{"phase_id": "__all__", "overrides": ov, "m": np.ones((n, quarters)), "start": np.zeros(n)}] if ov else []
    rng = np.random.default_rng(seed + 104_729)
    t = np.arange(quarters, dtype=float)[None, :]
    out = []; ends: dict = {}
    for ph in phases:
        pid = ph.get("phase_id") or f"phase{len(out) + 1}"
        if ph.get("after_phase"):
            prev = ends.get(ph["after_phase"])
            if prev is None:
                raise ValueError(f"фаза {pid}: after_phase {ph['after_phase']} не определена раньше")
            start = prev + _draw_quarters(ph.get("offset", 0), n, rng)
        else:
            start = _draw_quarters(ph.get("effective_from", 0), n, rng)
        start = np.clip(start, 0.0, None)
        ramp = float(ph.get("ramp_quarters") or 0); dur = ph.get("duration_quarters"); dec = float(ph.get("decay_quarters") or 0)
        st = start[:, None]
        up = np.clip((t - st) / ramp, 0.0, 1.0) if ramp > 0 else (t >= st).astype(float)
        if dur is None:
            m = up; plateau_end = np.full(n, float(quarters))
        else:
            pe = st + ramp + float(dur)
            down = np.clip(1.0 - (t - pe) / dec, 0.0, 1.0) if dec > 0 else (t < pe).astype(float)
            m = np.minimum(up, down); plateau_end = pe[:, 0]
        ends[pid] = plateau_end
        out.append({"phase_id": pid, "overrides": ph.get("driver_overrides") or {}, "m": m, "start": start})
    return out


def driver_shocks(spec: dict, drivers: list[str], n: int, quarters: int, seed: int, antithetic: bool = True,
                  scenario: dict | None = None):
    """dict driver → (n, quarters) стандартизированных шоков. Драйвер без mapping — чисто идиосинкратический.
    Сценарий — через профили фаз (scenario_profiles)."""
    ids, F = root_paths(spec, n, quarters, seed, antithetic)
    ids_i = {k: i for i, k in enumerate(ids)}
    _, R, _ = root_correlation(spec)
    maps = (spec.get("driver_generation") or {}).get("mappings") or {}
    rng = np.random.default_rng(seed + 7919)  # отдельный поток для идиосинкратических шоков драйверов (детерминирован seed'ом)
    out = {}
    phases = scenario_profiles(scenario, n, quarters, seed)
    for d in drivers:''')
rep('''        x = raw / math.sqrt(var) if var > 0 else raw
        o = ov.get(d) or {}
        if o.get("volatility_multiplier") is not None:
            x = x * float(o["volatility_multiplier"])
        if o.get("mean_shift_sigma") is not None:
            x = x + float(o["mean_shift_sigma"])
        out[d] = x
    return out''', '''        x = raw / math.sqrt(var) if var > 0 else raw
        for ph in phases:
            o = ph["overrides"].get(d) or {}
            if not o:
                continue
            m = ph["m"]
            if o.get("volatility_multiplier") is not None:
                x = x * (1.0 + (float(o["volatility_multiplier"]) - 1.0) * m)
            if o.get("mean_shift_sigma") is not None:
                x = x + float(o["mean_shift_sigma"]) * m
        out[d] = x
    return out''')
p.write_text(s, encoding="utf-8", newline="\n"); print("joint_layer 1.1.0 patched")

# ---------------------------------------------------------------- portfolio_paths: смешивание сценариев
p = ROOT / "engine/portfolio_paths.py"; s = p.read_text(encoding="utf-8")
rep('''inputs: {"paths_files": {ticker: путь .npz}, "weights": {ticker: w}, "dry_powder_weight": w_dp,
         "dry_powder_return_annual": r_dp (model_assumption; например доходность T-bills), "allow_unaligned": false}''',
    '''inputs: {"paths_files": {ticker: путь .npz}, "weights": {ticker: w}, "dry_powder_weight": w_dp,
         "dry_powder_return_annual": r_dp (model_assumption; например доходность T-bills), "allow_unaligned": false}
Смешивание сценариев (1.1.0, ЧЕРНОВИК до Scenario Engine v1.0): вместо paths_files — "scenarios": [{"id", "probability",
"paths_files": {ticker: .npz}}] (сумма вероятностей 1; пути всех сценариев выровнены по path_id — общий global_seed);
по каждому path_id сценарий выбирается детерминированно (mixture_seed) по вероятностям → смесь; в выходе — метрики смеси,
по каждому сценарию отдельно и scenario_delta (медиана/ES5/P(loss) к первому сценарию в списке, обычно BASE);
scenario_concentration — None до определения IMMA.''')
rep('VERSION = "1.0.0"', 'VERSION = "1.1.0"')
rep('''def run(inputs: dict, seed: int) -> dict:
    files = inputs.get("paths_files") or {}
    w = {k: float(v) for k, v in (inputs.get("weights") or {}).items()}''', '''def _metrics_for(data: dict, w: dict, wdp: float, rdp: float, n: int) -> dict:
    out = {}
    for h, key, yrs in (("Y3", "r3", 3), ("Y5", "r5", 5), ("Y8", "r8", 8)):
        pv = np.zeros(n)
        for t, wt in w.items():
            pv += wt * data[t][key][:n].astype(float)
        pv += wdp * (1.0 + rdp) ** yrs
        cagr = np.power(np.clip(pv, 1e-12, None), 1.0 / yrs) - 1.0; ret = pv - 1.0; k = max(1, int(math.ceil(0.05 * n)))
        out[h] = {"median_CAGR": float(np.median(cagr)), "P_2x": float((pv >= 2).mean()), "P_loss_gt_30pct": float((pv < 0.7).mean()),
                  "P_loss_gt_50pct": float((pv < 0.5).mean()), "expected_shortfall_5pct": float(np.sort(ret)[:k].mean()),
                  "CAGR_quantiles": {str(q): float(np.quantile(cagr, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}}
    return out


def run(inputs: dict, seed: int) -> dict:
    if inputs.get("scenarios"):
        return _run_mixture(inputs, seed)
    files = inputs.get("paths_files") or {}
    w = {k: float(v) for k, v in (inputs.get("weights") or {}).items()}''')
s = s.rstrip("\n") + '''


def _run_mixture(inputs: dict, seed: int) -> dict:
    """Смесь сценариев по path_id (черновик): выбор сценария на путь по вероятностям, метрики смеси и по сценариям."""
    scen = inputs["scenarios"]
    w = {k: float(v) for k, v in (inputs.get("weights") or {}).items()}
    wdp = float(inputs.get("dry_powder_weight", 0.0)); rdp = float(inputs.get("dry_powder_return_annual", 0.0))
    probs = np.array([float(sc.get("probability", 0.0)) for sc in scen])
    if abs(probs.sum() - 1.0) > 1e-6 or (probs < 0).any():
        raise ValueError(f"вероятности сценариев должны быть ≥0 и давать 1.0, получено {probs.tolist()}")
    if abs(sum(w.values()) + wdp - 1.0) > 1e-6:
        raise ValueError("веса + dry powder должны давать 1.0")
    loaded = []
    for sc in scen:
        files = sc.get("paths_files") or {}
        missing = [t for t in w if t not in files]
        if missing:
            raise ValueError(f"сценарий {sc.get('id')}: нет файлов путей для {missing}")
        loaded.append({t: load_paths(files[t]) for t in w})
    n = min(len(d[t]["r5"]) for d in loaded for t in w)
    ref_ids = loaded[0][next(iter(w))]["path_id"][:n]; ref_meta = loaded[0][next(iter(w))]["meta"]
    for sc, d in zip(scen, loaded):
        for t in w:
            m = d[t]["meta"]
            if m.get("global_seed") != ref_meta.get("global_seed") or m.get("chunk") != ref_meta.get("chunk") or not np.array_equal(d[t]["path_id"][:n], ref_ids):
                raise ValueError(f"сценарий {sc.get('id')}, {t}: пути не выровнены по path_id с {scen[0].get('id')} — смесь не считается")
    rng = np.random.default_rng(int(inputs.get("mixture_seed", seed)) + 424_243)
    choice = rng.choice(len(scen), size=n, p=probs)          # сценарий на путь (детерминировано)
    mixed = {t: {key: np.select([choice == j for j in range(len(scen))], [loaded[j][t][key][:n] for j in range(len(scen))]) for key in ("r3", "r5", "r8")} for t in w}
    mix = _metrics_for(mixed, w, wdp, rdp, n)
    per = {sc["id"]: _metrics_for(loaded[j], w, wdp, rdp, n) for j, sc in enumerate(scen)}
    base_id = scen[0]["id"]
    delta = {sc["id"]: {h: {k: per[sc["id"]][h][k] - per[base_id][h][k] for k in ("median_CAGR", "P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct", "P_2x")} for h in ("Y3", "Y5", "Y8")} for sc in scen[1:]}
    shares = {sc["id"]: float((choice == j).mean()) for j, sc in enumerate(scen)}
    return {"model_version": VERSION, "mode": "scenario_mixture_draft", "paths": int(n), "weights": w, "dry_powder_weight": wdp, "dry_powder_return_annual": rdp,
            "scenarios": [{"id": sc["id"], "probability": float(sc["probability"]), "realized_share": shares[sc["id"]]} for sc in scen], "mixture_seed": int(inputs.get("mixture_seed", seed)),
            "horizons": mix, "by_scenario": per, "scenario_delta_vs_first": delta, "scenario_concentration": None,
            "note": "ЧЕРНОВИК до Scenario Engine v1.0: смесь по path_id (общие случайные числа), дельта сценария = разность метрик сценария и первого в списке; определение Scenario Concentration и вклада смеси — по спецификации IMMA; decision: none",
            "decision": "none"}
'''
p.write_text(s, encoding="utf-8", newline="\n"); print("portfolio_paths 1.1.0 patched")

# ---------------------------------------------------------------- тесты
t = ROOT / "tests/test_joint_layer.py"; u = t.read_text(encoding="utf-8")
u = u.rstrip("\n") + '''


def test_scenario_phases_profile_and_legacy_equivalence():
    n, T = 4000, 32
    # legacy driver_overrides == одна фаза с t0 до конца
    legacy = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.5, "volatility_multiplier": 1.2}}})
    one = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"phases": [{"phase_id": "p", "effective_from": 0, "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.5, "volatility_multiplier": 1.2}}}]})
    assert np.allclose(legacy["AI_COMPUTE_DEMAND"], one["AI_COMPUTE_DEMAND"])
    # профиль: старт по распределению, подъём 4 кв., плато 8 кв., спад 4 кв.
    prof = jl.scenario_profiles({"phases": [{"phase_id": "a", "effective_from": {"distribution": "uniform", "min": 4, "max": 8}, "ramp_quarters": 4, "duration_quarters": 8, "decay_quarters": 4, "driver_overrides": {"X": {"mean_shift_sigma": 1}}},
                                            {"phase_id": "b", "after_phase": "a", "offset": 2, "driver_overrides": {"X": {"mean_shift_sigma": -1}}}]}, n, T, 7)
    a, b = prof[0], prof[1]
    assert a["m"].shape == (n, T) and a["m"].min() >= 0 and a["m"].max() <= 1
    assert (a["start"] >= 4).all() and (a["start"] <= 8).all()
    i = 0; st = a["start"][i]
    assert a["m"][i, int(np.floor(st))] <= 1e-9 or st == np.floor(st)                 # до старта — 0
    assert abs(a["m"][i, int(np.ceil(st)) + 5] - 1.0) < 1e-9                             # плато
    assert a["m"][i, min(T - 1, int(np.ceil(st)) + 4 + 8 + 4)] <= 1e-9 or int(np.ceil(st)) + 16 >= T   # после спада — 0
    assert (b["start"] >= a["start"] + 4 + 8 + 2 - 1e-9).all()                            # after_phase: старт после плато a + offset
    # сдвиг действует только после старта: средний шок до 4-го квартала ≈ 0, на плато ≈ +1
    sh = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"phases": [{"phase_id": "a", "effective_from": 8, "ramp_quarters": 0, "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": 1.0}}}]})["AI_COMPUTE_DEMAND"]
    assert abs(sh[:, :8].mean()) < 0.1 and abs(sh[:, 8:].mean() - 1.0) < 0.1
    # детерминизм
    again = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"phases": [{"phase_id": "a", "effective_from": {"distribution": "triangular", "min": 2, "mode": 6, "max": 10}, "ramp_quarters": 2, "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.0}}}]})
    again2 = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"phases": [{"phase_id": "a", "effective_from": {"distribution": "triangular", "min": 2, "mode": 6, "max": 10}, "ramp_quarters": 2, "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.0}}}]})
    assert np.array_equal(again["AI_COMPUTE_DEMAND"], again2["AI_COMPUTE_DEMAND"])
'''
t.write_text(u, encoding="utf-8", newline="\n"); print("test_joint_layer patched")

t = ROOT / "tests/test_portfolio_paths.py"; u = t.read_text(encoding="utf-8")
u = u.rstrip("\n") + '''


def test_scenario_mixture_draft(tmp_path):
    base_a = _run_store(_joint(cal_mature(), "AAA"), tmp_path); base_b = _run_store(_joint(cal_capital(), "BBB"), tmp_path)
    down = {"id": "DOWN", "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -2.0}}}
    ca = dict(_joint(cal_mature(), "AAA")); cb = dict(_joint(cal_capital(), "BBB"))
    da = cm.run({"calibration": ca, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp_path), "_run_id": "t-AAA-DOWN", "scenario": down}, 0)
    db = cm.run({"calibration": cb, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp_path), "_run_id": "t-BBB-DOWN", "scenario": down}, 0)
    scen = [{"id": "BASE", "probability": 0.7, "paths_files": {"AAA": base_a["paths_file"], "BBB": base_b["paths_file"]}},
            {"id": "DOWN", "probability": 0.3, "paths_files": {"AAA": da["paths_file"], "BBB": db["paths_file"]}}]
    inp = {"scenarios": scen, "weights": {"AAA": 0.5, "BBB": 0.4}, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}
    out = pp.run(inp, 5)
    assert out["mode"] == "scenario_mixture_draft" and out["decision"] == "none" and out["scenario_concentration"] is None
    sh = {s["id"]: s["realized_share"] for s in out["scenarios"]}; assert abs(sh["BASE"] - 0.7) < 0.03 and abs(sh["DOWN"] - 0.3) < 0.03
    b, d, m = out["by_scenario"]["BASE"]["Y5"], out["by_scenario"]["DOWN"]["Y5"], out["horizons"]["Y5"]
    assert d["median_CAGR"] < b["median_CAGR"] and out["scenario_delta_vs_first"]["DOWN"]["Y5"]["median_CAGR"] < 0
    assert min(b["median_CAGR"], d["median_CAGR"]) - 1e-9 <= m["median_CAGR"] <= max(b["median_CAGR"], d["median_CAGR"]) + 1e-9   # смесь между сценариями
    # вероятность 1.0 у BASE воспроизводит обычный прогон
    single = pp.run({"paths_files": scen[0]["paths_files"], "weights": {"AAA": 0.5, "BBB": 0.4}, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    only = pp.run({**inp, "scenarios": [{**scen[0], "probability": 1.0}, {**scen[1], "probability": 0.0}]}, 5)
    assert abs(only["horizons"]["Y5"]["median_CAGR"] - single["horizons"]["Y5"]["median_CAGR"]) < 1e-12
    assert pp.run(inp, 5)["horizons"] == out["horizons"]                                                     # детерминизм
    import pytest
    with pytest.raises(ValueError):
        pp.run({**inp, "scenarios": [{**scen[0], "probability": 0.5}, {**scen[1], "probability": 0.3}]}, 5)
'''
t.write_text(u, encoding="utf-8", newline="\n"); print("test_portfolio_paths patched")
