"""joint_layer 1.3.0 — нормативная семантика persistence_override (ответ IMMA 25.09 на вопрос 2.1):
η_{d,t} = standardize(Σ_r λ_{d,r}·u_{r,t} + w_d·ε_{d,t}) — инновации корней текущего квартала (после фазовой матрицы корреляций) и та же
идиосинкратическая инновация драйвера, что в BASE; y_t = ρ_t·y_{t−1} + sqrt(1−ρ_t²)·η_t там, где ρ задан; null — bypass (базовый путь);
инициализация y_{t−1} последним выпущенным стандартизированным шоком драйвера; numeric→numeric — линейно по фазовому весу.
Валидатор: SCN-011 — на плато с постоянным ρ после прогрева Var(y) ≈ 1 и лаг-1 корреляция ≈ ρ."""
from pathlib import Path

ROOT = Path("C:/openclaw-lab/calc")


def patch(path, reps):
    p = ROOT / path; s = p.read_text(encoding="utf-8")
    for a, b in reps:
        assert s.count(a) == 1, (path, a[:70]); s = s.replace(a, b)
    p.write_text(s, encoding="utf-8", newline="\n"); print("patched", path)


patch("engine/joint_layer.py", [
    ('VERSION = "1.2.1"', 'VERSION = "1.3.0"'),
    ('''  до mapping компании. persistence_override ρ ∈ [0, 0.99] — ПРЕДВАРИТЕЛЬНАЯ интерпретация (вопрос 2.1 к IMMA, вариант «б»):
  AR(1)-перепостоянство стандартизированного пути драйвера y_t = ρ_t·y_{t−1} + sqrt(1−ρ_t²)·x_t там, где ρ задана (null — y_t = x_t,
  базовая персистентность Joint Layer); на ramp — линейная интерполяция, если заданы оба конца, иначе до середины ramp старое
  значение, после — новое (§3.3). Сценарный драйвер = mu + vol·y.''',
     '''  до mapping компании. persistence_override ρ ∈ [0, 0.99] — НОРМАТИВНАЯ семантика (ответ IMMA 25.09, п. 2.1): innovation-level:
  η_{d,t} = standardize(Σ_r λ_{d,r}·u_{r,t} + w_d·ε_{d,t}), где u_{r,t} — инновации корней текущего квартала (после фазовой матрицы
  корреляций), ε_{d,t} — та же идиосинкратическая инновация драйвера, что в BASE; y_t = ρ_t·y_{t−1} + sqrt(1−ρ_t²)·η_t там, где ρ
  задан; null — bypass (базовый путь драйвера, не ρ=0); при старте override y_{t−1} = последний выпущенный стандартизированный шок
  драйвера; numeric→numeric — линейно по фазовому весу, один конец null — до середины ramp старое, после — новое (§3.3).
  Сценарный драйвер = mu + vol·y. phi корней и decay mapping компаний не меняются.'''),
    ('''def _repersist(x: np.ndarray, rho: np.ndarray, ac1: float) -> np.ndarray:
    """AR(1)-перепостоянство пути драйвера там, где rho задана (не NaN): инновации базового пути e_t = (x_t − φ·x_{t−1})/sqrt(1−φ²)
    (φ — теоретическая лаг-1 автокорреляция драйвера из корней), y_t = ρ_t·y_{t−1} + sqrt(1−ρ_t²)·e_t; где rho null — y_t = x_t."""
    if np.isnan(rho).all():
        return x
    phi = float(min(max(ac1, -0.99), 0.99))
    e = np.empty_like(x); e[:, 0] = x[:, 0]; e[:, 1:] = (x[:, 1:] - phi * x[:, :-1]) / math.sqrt(1.0 - phi ** 2)
    y = np.empty_like(x); y[:, 0] = x[:, 0]
    for tq in range(1, x.shape[1]):
        r = rho[:, tq]; has = ~np.isnan(r); rr = np.where(has, r, 0.0)
        y[:, tq] = np.where(has, rr * y[:, tq - 1] + np.sqrt(1.0 - rr ** 2) * e[:, tq], x[:, tq])
    return y''',
     '''def _repersist(x: np.ndarray, eta: np.ndarray, rho: np.ndarray) -> np.ndarray:
    """Нормативное перепостоянство (IMMA 2.1): y_t = ρ_t·y_{t−1} + sqrt(1−ρ_t²)·η_t там, где rho задана (не NaN), η — стандартизированные
    инновации драйвера того же квартала; где rho null — y_t = x_t (bypass); при старте override y_{t−1} — последний выпущенный шок."""
    if np.isnan(rho).all():
        return x
    y = np.empty_like(x); y[:, 0] = x[:, 0]
    for tq in range(1, x.shape[1]):
        r = rho[:, tq]; has = ~np.isnan(r); rr = np.where(has, r, 0.0)
        y[:, tq] = np.where(has, rr * y[:, tq - 1] + np.sqrt(1.0 - rr ** 2) * eta[:, tq], x[:, tq])
    return y


def _root_innovations(F: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """Инновации AR(1)-корней по путям: u_0 = F_0 (стационарный старт), u_t = (F_t − phi·F_{t−1}) / sqrt(1−phi²)."""
    U = np.empty_like(F); U[:, :, 0] = F[:, :, 0]
    U[:, :, 1:] = (F[:, :, 1:] - phi[None, :, None] * F[:, :, :-1]) / np.sqrt(1.0 - phi ** 2)[None, :, None]
    return U'''),
    ('''    rng = np.random.default_rng(seed + 7919)  # отдельный поток для идиосинкратических шоков драйверов (детерминирован seed'ом)
    phi_roots = np.array([float(spec["root_factors"]["factors"][k].get("phi", 0.0)) for k in ids])
    out = {}
    legacy = ((scenario or {}).get("driver_overrides") or {}) if sched is None else {}
    for d in drivers:
        m = maps.get(d)
        if m:
            lam = np.zeros(len(ids))
            for k, v in (m.get("roots") or {}).items():
                lam[ids_i[k]] = float(v)
            idio = float(m.get("idio_weight", 0.0))
            raw = np.einsum("k,nkt->nt", lam, F) + idio * rng.standard_normal((n, quarters))
            var = float(lam @ R @ lam) + idio ** 2
            ac1 = float(lam @ (phi_roots[:, None] * R) @ lam) / var if var > 0 else 0.0   # теоретическая лаг-1 автокорреляция драйвера
        else:
            raw = rng.standard_normal((n, quarters)); var = 1.0; ac1 = 0.0
        x = raw / math.sqrt(var) if var > 0 else raw
        if sched is not None:
            x = sched["mu"][d] + np.exp(sched["logvol"][d]) * _repersist(x, sched["rho"][d], ac1)''',
     '''    rng = np.random.default_rng(seed + 7919)  # отдельный поток для идиосинкратических шоков драйверов (детерминирован seed'ом)
    phi_roots = np.array([float(spec["root_factors"]["factors"][k].get("phi", 0.0)) for k in ids])
    need_eta = sched is not None and any(not np.isnan(sched["rho"][d]).all() for d in drivers)
    U = _root_innovations(F, phi_roots) if need_eta else None
    out = {}
    legacy = ((scenario or {}).get("driver_overrides") or {}) if sched is None else {}
    for d in drivers:
        m = maps.get(d)
        eps = rng.standard_normal((n, quarters))                          # та же идиосинкратическая инновация для BASE и сценария
        if m:
            lam = np.zeros(len(ids))
            for k, v in (m.get("roots") or {}).items():
                lam[ids_i[k]] = float(v)
            idio = float(m.get("idio_weight", 0.0))
            raw = np.einsum("k,nkt->nt", lam, F) + idio * eps
            var = float(lam @ R @ lam) + idio ** 2
        else:
            lam = None; idio = 1.0; raw = eps; var = 1.0
        x = raw / math.sqrt(var) if var > 0 else raw
        if sched is not None:
            rho = sched["rho"][d]
            if not np.isnan(rho).all():
                if lam is not None:
                    inn = np.einsum("k,nkt->nt", lam, U) + idio * eps
                    var_state = np.array([float(lam @ M @ lam) + idio ** 2 for M in sched["corr_mats"]])   # дисперсия инновации по состоянию корреляций
                    eta = inn / np.sqrt(var_state[sched["corr_idx"]])
                else:
                    eta = eps
                x = _repersist(x, eta, rho)
            x = sched["mu"][d] + np.exp(sched["logvol"][d]) * x'''),
    # диагностика персистентности для валидатора
    ('''def scenario_diagnostics(spec: dict, scenario: dict, drivers: list[str], n: int, quarters: int, seed: int) -> dict:''',
     '''def persistence_diagnostics(spec: dict, scenario: dict, drivers: list[str], n: int, quarters: int, seed: int, warmup: int = 4) -> dict:
    """SCN-011: для каждой фазы с числовым ρ и драйвера — на плато (после warmup кварталов) Var(y) ≈ 1 и lag-1 corr ≈ ρ.
    y восстанавливается из шоков: y = (driver − mu) / vol."""
    if not is_phased(scenario):
        return {}
    sched = scenario_schedule(spec, scenario, drivers, n, quarters, seed)
    sh = driver_shocks(spec, drivers, n, quarters, seed, scenario=scenario)
    out = {}
    for d in drivers:
        rho = sched["rho"][d]
        if np.isnan(rho).all():
            continue
        y = (sh[d] - sched["mu"][d]) / np.exp(sched["logvol"][d])
        for pid, st in sched["starts"].items():
            ph = next(p for p in scenario["phases"] if p["phase_id"] == pid)
            r_target = (ph.get("driver_overrides") or {}).get(d, {}).get("persistence_override")
            if r_target is None:
                continue
            ramp = int(ph.get("ramp_quarters") or 0)
            t0 = st + ramp + warmup
            ok = (t0 + 2 < quarters) & np.all(np.stack([np.abs(rho[np.arange(n), np.clip(t0 + k, 0, quarters - 1)] - float(r_target)) < 1e-9 for k in range(3)]), axis=0)
            if ok.sum() < 200:
                out[f"{pid}/{d}"] = {"rho": float(r_target), "paths": int(ok.sum()), "status": "insufficient_paths"}; continue
            rows = np.where(ok)[0]; a = y[rows, t0[rows] + 1]; b = y[rows, t0[rows] + 2]
            var = float(np.var(np.concatenate([a, b]))); corr = float(np.corrcoef(a, b)[0, 1])
            out[f"{pid}/{d}"] = {"rho": float(r_target), "paths": int(len(rows)), "var_y": var, "lag1_corr": corr, "ok": bool(abs(var - 1.0) <= 0.15 and abs(corr - float(r_target)) <= 0.10)}
    return out


def scenario_diagnostics(spec: dict, scenario: dict, drivers: list[str], n: int, quarters: int, seed: int) -> dict:'''),
])

patch("engine/artifact_validator.py", [
    ('''                unmapped_joint = [d for d in drv if d not in ((jspec.get("driver_generation") or {}).get("mappings") or {})]''',
     '''                pers = jl.persistence_diagnostics(jspec, sc, drv_known, n_chk, Q, seed)
                replay["persistence"] = pers
                bad_p = [k for k, v in pers.items() if v.get("ok") is False]
                if bad_p:
                    findings.append(_f("SCN-011", "phases", f"persistence_override: Var(y) или lag-1 corr вне допуска на плато у {bad_p[:6]}", "warning"))
                unmapped_joint = [d for d in drv if d not in ((jspec.get("driver_generation") or {}).get("mappings") or {})]'''),
])

t = ROOT / "tests/test_joint_layer.py"; u = t.read_text(encoding="utf-8")
a = '''    assert ac_p > ac_b + 0.2 and abs(np.var(xp[:, 20:]) - 1.0) < 0.25                                        # автокорреляция выросла, дисперсия ≈ 1 (остаток: драйвер — смесь AR-корней, отбеливание одним φ приближённое)'''
b = '''    assert ac_p > ac_b + 0.2 and abs(np.var(xp[:, 20:]) - 1.0) < 0.15                                        # автокорреляция выросла, дисперсия ≈ 1 (инновационная семантика IMMA)
    diag = jl.persistence_diagnostics(SPEC, pers, [d], n, T, 1)
    k = f"A/{d}"; assert diag[k]["ok"] and abs(diag[k]["lag1_corr"] - 0.9) < 0.1 and abs(diag[k]["var_y"] - 1.0) < 0.15   # SCN-011: Var(y) ≈ 1, lag-1 ≈ ρ'''
assert u.count(a) == 1; u = u.replace(a, b); t.write_text(u, encoding="utf-8", newline="\n"); print("tests patched")
