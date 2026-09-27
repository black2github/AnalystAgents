"""joint_layer 1.2.1: persistence_override (предварительная интерпретация «б» — AR(1)-перепостоянство пути драйвера), таксономия v1.2
(added_v1_2 на верхнем уровне) в валидаторе, тесты."""
from pathlib import Path

ROOT = Path("C:/openclaw-lab/calc")


def patch(path, reps):
    p = ROOT / path; s = p.read_text(encoding="utf-8")
    for a, b in reps:
        assert s.count(a) == 1, (path, a[:70]); s = s.replace(a, b)
    p.write_text(s, encoding="utf-8", newline="\n"); print("patched", path)


patch("engine/joint_layer.py", [
    ('''  до mapping компании. persistence_override ≠ null — НЕ реализовано (ждём определение IMMA, вопрос 2.1) → ValueError.''',
     '''  до mapping компании. persistence_override ρ ∈ [0, 0.99] — ПРЕДВАРИТЕЛЬНАЯ интерпретация (вопрос 2.1 к IMMA, вариант «б»):
  AR(1)-перепостоянство стандартизированного пути драйвера y_t = ρ_t·y_{t−1} + sqrt(1−ρ_t²)·x_t там, где ρ задана (null — y_t = x_t,
  базовая персистентность Joint Layer); на ramp — линейная интерполяция, если заданы оба конца, иначе до середины ramp старое
  значение, после — новое (§3.3). Сценарный драйвер = mu + vol·y.'''),
    ('''    mu = {d: np.zeros((n, quarters)) for d in drivers}; lv = {d: np.zeros((n, quarters)) for d in drivers}''',
     '''    mu = {d: np.zeros((n, quarters)) for d in drivers}; lv = {d: np.zeros((n, quarters)) for d in drivers}
    rho = {d: np.full((n, quarters), np.nan) for d in drivers}   # NaN = null (базовая персистентность)'''),
    ('''        ov = ph.get("driver_overrides") or {}
        for d, o in ov.items():
            if o.get("persistence_override") is not None:
                raise ValueError(f"фаза {pid}, драйвер {d}: persistence_override не реализован (ожидает определения IMMA, вопрос 2.1)")
''', '''        ov = ph.get("driver_overrides") or {}
        for d, o in ov.items():
            po = o.get("persistence_override")
            if po is not None and not (0.0 <= float(po) <= 0.99):
                raise ValueError(f"фаза {pid}, драйвер {d}: persistence_override {po} вне [0, 0.99]")
'''),
    ('''            for S, target in ((mu[d], tm), (lv[d], tl)):
                prev = np.where(s_i > 0, S[rows, prev_q], 0.0)[:, None]          # состояние в квартале перед стартом фазы
                new = S.copy()
                new[in_ramp] = ((1.0 - lam) * prev + lam * target)[in_ramp]
                new[in_plateau] = target
                new[in_decay] = (a_dec * target)[in_decay]
                new[after] = 0.0
                S[:] = new''',
     '''            for S, target in ((mu[d], tm), (lv[d], tl)):
                prev = np.where(s_i > 0, S[rows, prev_q], 0.0)[:, None]          # состояние в квартале перед стартом фазы
                new = S.copy()
                new[in_ramp] = ((1.0 - lam) * prev + lam * target)[in_ramp]
                new[in_plateau] = target
                new[in_decay] = (a_dec * target)[in_decay]
                new[after] = 0.0
                S[:] = new
            # persistence_override: оба конца заданы → линейно; один null → до середины ramp старое, после — новое; decay/после → null
            R_ = rho[d]; tp_raw = o.get("persistence_override"); tp = np.nan if tp_raw is None else float(tp_raw)
            prev_r = np.where(s_i > 0, R_[rows, prev_q], np.nan)[:, None]
            both = np.broadcast_to(~np.isnan(prev_r) & (not np.isnan(tp)), lam.shape)
            lin = (1.0 - lam) * np.where(np.isnan(prev_r), 0.0, prev_r) + lam * (0.0 if np.isnan(tp) else tp)
            ramp_val = np.where(both, lin, np.where(lam <= 0.5 + 1e-12, np.broadcast_to(prev_r, lam.shape), tp))
            new = R_.copy()
            new[in_ramp] = ramp_val[in_ramp]
            new[in_plateau] = tp
            new[in_decay | after] = np.nan
            R_[:] = new'''),
    ('''    return {"mu": mu, "logvol": lv, "corr_idx": corr_idx, "corr_mats": mats, "starts": starts, "phase_share": share, "n_corr_states": len(mats)}''',
     '''    return {"mu": mu, "logvol": lv, "rho": rho, "corr_idx": corr_idx, "corr_mats": mats, "starts": starts, "phase_share": share, "n_corr_states": len(mats)}


def _repersist(x: np.ndarray, rho: np.ndarray) -> np.ndarray:
    """AR(1)-перепостоянство пути там, где rho задана (не NaN): y_t = ρ_t·y_{t−1} + sqrt(1−ρ_t²)·x_t; иначе y_t = x_t."""
    if np.isnan(rho).all():
        return x
    y = np.empty_like(x); y[:, 0] = x[:, 0]
    for tq in range(1, x.shape[1]):
        r = rho[:, tq]; has = ~np.isnan(r); rr = np.where(has, r, 0.0)
        y[:, tq] = np.where(has, rr * y[:, tq - 1] + np.sqrt(1.0 - rr ** 2) * x[:, tq], x[:, tq])
    return y'''),
    ('''        if sched is not None:
            x = sched["mu"][d] + np.exp(sched["logvol"][d]) * x''',
     '''        if sched is not None:
            x = sched["mu"][d] + np.exp(sched["logvol"][d]) * _repersist(x, sched["rho"][d])'''),
    ('VERSION = "1.2.0"', 'VERSION = "1.2.1"'),
])

patch("engine/artifact_validator.py", [
    ('''    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    drivers = d.get("drivers") or {}
    ids: set[str] = set()
    for v in (drivers.values() if isinstance(drivers, dict) else [drivers]):''',
     '''    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    drivers = d.get("drivers") or {}
    ids: set[str] = set()
    extra = [v for k, v in d.items() if str(k).startswith("added_v") and k not in drivers]   # v1.2: added_v1_2 на верхнем уровне (не под drivers)
    for v in (list(drivers.values()) if isinstance(drivers, dict) else [drivers]) + extra:'''),
])

patch("tests/test_joint_layer.py", [
    ('''    with pytest.raises(ValueError):                                                                          # persistence_override не реализован
        bad = {"scenario_id": "P", "phases": [_ph("A", quarter=0, ov={d: (0.0, 1.0)})]}; bad["phases"][0]["driver_overrides"][d]["persistence_override"] = 0.5
        jl.scenario_schedule(SPEC, bad, [d], n, T, 1)''',
     '''    # persistence_override (вариант «б», предварительно): AR(1)-перепостоянство пути на плато; вне [0,0.99] → ValueError; null = базовый путь
    pers = {"scenario_id": "P", "phases": [_ph("A", quarter=4, ramp=2, ov={d: (0.0, 1.0)})]}; pers["phases"][0]["driver_overrides"][d]["persistence_override"] = 0.9
    sch = jl.scenario_schedule(SPEC, pers, [d], n, T, 1); r = sch["rho"][d][0]
    assert np.isnan(r[:4]).all() and np.isnan(r[4]) and r[5] == 0.9 and (r[6:] == 0.9).all()               # один конец null: до середины ramp старое (null), после — новое
    xb = jl.driver_shocks(SPEC, [d], n, T, 1)[d]; xp = jl.driver_shocks(SPEC, [d], n, T, 1, scenario=pers)[d]
    assert np.array_equal(xp[:, :5], xb[:, :5])
    ac_b = np.mean(xb[:, 10:] * xb[:, 9:-1]); ac_p = np.mean(xp[:, 10:] * xp[:, 9:-1])
    assert ac_p > ac_b + 0.2 and abs(np.var(xp[:, 20:]) - 1.0) < 0.15                                        # автокорреляция выросла, дисперсия ≈ 1
    with pytest.raises(ValueError):
        bad = {"scenario_id": "P2", "phases": [_ph("A", quarter=0, ov={d: (0.0, 1.0)})]}; bad["phases"][0]["driver_overrides"][d]["persistence_override"] = 1.5
        jl.scenario_schedule(SPEC, bad, [d], n, T, 1)'''),
])
