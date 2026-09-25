"""Joint Simulation Layer v1.0 (Joint_Simulation_Layer_Specification_v1.0, 21.09.2026) — срез 2 company_mc.

Root-факторы: стационарные AR(1) N(0,1), квартальный шаг: F_t = phi·F_{t-1} + sqrt(1−phi²)·u_t, u ~ MVN(0, R_root).
Драйверы: Raw_d,t = Σ_k λ_dk F_k,t + σ_idio,d ε_d,t → стандартизация к unit variance (теоретическая, стационарная).
Общий путь: одна и та же пара (global_seed, path_index) даёт один и тот же набор root/driver шоков для любой компании —
массивы не передаются между вызовами, а воспроизводятся детерминированно (инвариант «same factor path for all companies»).

Сценарии (1.2.0 — Scenario_Engine_Specification_v1.0, IMMA 25.09.2026):
- legacy: scenario.driver_overrides {D: {mean_shift_sigma, volatility_multiplier}} без phases — постоянный уровень на всём горизонте
  (прежние прогоны воспроизводятся);
- фазовый: scenario.phases = [{phase_id, effective_from {kind: fixed_quarter|triangular_quarter, anchor: t0|phase:<id>, quarter |
  min/mode/max}, ramp_quarters, duration_quarters (int | until_next_phase | until_end), decay_quarters, driver_overrides
  {D: {mean_shift_sigma, volatility_multiplier, persistence_override}}, root_correlation_overrides [{root_a, root_b, correlation}]}].
  Фаза — ЦЕЛЕВОЕ состояние относительно BASE (отсутствующий драйвер = BASE: сдвиг 0, волатильность 1). Розыгрыш старта — один на
  (scenario_id, path, phase_id), целочисленный квартал; anchor phase:<id> — смещение от фактического старта той фазы.
  Ramp: линейная интерполяция сдвига и log(волатильности) от предыдущего активного состояния к целевому; плато — до следующей
  фазы / до конца / N кварталов; при целочисленной длительности — линейный возврат к BASE за decay_quarters (0 — ступенькой).
  Формула: ScenarioDriver_d,t = mu_d,t + vol_d,t · BaseDriver_d,t. Override — после генерации корней и стандартизации драйвера,
  до mapping компании. persistence_override ρ ∈ [0, 0.99] — НОРМАТИВНАЯ семантика (ответ IMMA 25.09, п. 2.1): innovation-level:
  η_{d,t} = standardize(Σ_r λ_{d,r}·u_{r,t} + w_d·ε_{d,t}), где u_{r,t} — инновации корней текущего квартала (после фазовой матрицы
  корреляций), ε_{d,t} — та же идиосинкратическая инновация драйвера, что в BASE; y_t = ρ_t·y_{t−1} + sqrt(1−ρ_t²)·η_t там, где ρ
  задан; null — bypass (базовый путь драйвера, не ρ=0); при старте override y_{t−1} = последний выпущенный стандартизированный шок
  драйвера; numeric→numeric — линейно по фазовому весу, один конец null — до середины ramp старое, после — новое (§3.3).
  Сценарный драйвер = mu + vol·y. phi корней и decay mapping компаний не меняются.
- корреляции корней по фазам: целевая матрица = базовая с переопределёнными парами; PSD обязательна (без авторемонта — иначе
  ValueError); на ramp/decay — выпуклая интерполяция матриц (квантованная по кварталам: конечный набор матриц, для каждой —
  своё разложение Холецкого); одни и те же iid-инновации по (path, factor, quarter) для BASE и сценариев (общие случайные числа).
"""
from __future__ import annotations

import math
import zlib

import numpy as np

VERSION = "1.3.0"


def root_correlation(spec: dict):
    """(ids, R, psd_fixed) из root_factors/root_correlation спецификации (pair_overrides A__B: rho)."""
    ids = list(spec["root_factors"]["factors"].keys())
    n = len(ids); R = np.eye(n)
    rc = spec.get("root_correlation") or {}
    for key, v in (rc.get("pair_overrides") or {}).items():
        a, b = key.split("__")
        if a in ids and b in ids:
            R[ids.index(a), ids.index(b)] = R[ids.index(b), ids.index(a)] = float(v)
    w, V = np.linalg.eigh(R); fixed = False
    if w.min() < -1e-10:
        w = np.clip(w, 1e-8, None); R = V @ np.diag(w) @ V.T; d = np.sqrt(np.diag(R)); R = R / np.outer(d, d); fixed = True
    return ids, R, fixed


def phase_correlation(spec: dict, phase: dict) -> np.ndarray:
    """Целевая матрица корреляций корней фазы: базовая + root_correlation_overrides; PSD не чинится (ValueError)."""
    ids, R, _ = root_correlation(spec)
    T = R.copy()
    for o in phase.get("root_correlation_overrides") or []:
        a, b = o["root_a"], o["root_b"]
        if a not in ids or b not in ids:
            raise ValueError(f"фаза {phase.get('phase_id')}: неизвестный корень в root_correlation_overrides: {a}__{b}")
        T[ids.index(a), ids.index(b)] = T[ids.index(b), ids.index(a)] = float(o["correlation"])
    if np.linalg.eigvalsh(T).min() < -1e-10:
        raise ValueError(f"фаза {phase.get('phase_id')}: целевая матрица корреляций не PSD (min eig {np.linalg.eigvalsh(T).min():.4g}); авторемонт запрещён")
    return T


def _crc(s: str) -> int:
    return zlib.crc32(str(s).encode("utf-8")) & 0xFFFFFFFF


def phase_starts(scenario: dict, n: int, quarters: int, seed: int) -> dict:
    """Стартовые кварталы фаз на путь: {phase_id: (n,) int}. Розыгрыш детерминирован по (seed, scenario_id, phase_id);
    anchor phase:<id> — смещение от фактического старта той фазы (должна идти раньше в списке)."""
    starts: dict = {}
    sid = scenario.get("scenario_id") or scenario.get("id") or "SCENARIO"
    for ph in scenario.get("phases") or []:
        pid = ph["phase_id"]; ef = ph.get("effective_from") or {}
        rng = np.random.default_rng(np.random.SeedSequence([int(seed) & 0xFFFFFFFF, _crc(sid), _crc(pid), 0x5CE7]))
        kind = ef.get("kind", "fixed_quarter")
        if kind == "fixed_quarter":
            draw = np.full(n, int(ef.get("quarter", 0)))
        elif kind == "triangular_quarter":
            lo, hi = float(ef["min"]), float(ef["max"]); mode = float(ef.get("mode", 0.5 * (lo + hi)))
            draw = np.clip(np.rint(rng.triangular(lo, mode, hi, n)), lo, hi).astype(int) if hi > lo else np.full(n, int(lo))
        else:
            raise ValueError(f"фаза {pid}: неизвестный kind effective_from: {kind}")
        anchor = str(ef.get("anchor", "t0"))
        if anchor == "t0":
            base = np.zeros(n, dtype=int)
        elif anchor.startswith("phase:"):
            ref = anchor.split(":", 1)[1]
            if ref not in starts:
                raise ValueError(f"фаза {pid}: anchor {anchor} ссылается на фазу, не определённую раньше")
            base = starts[ref]
        else:
            raise ValueError(f"фаза {pid}: неизвестный anchor {anchor}")
        starts[pid] = np.clip(base + draw, 0, quarters)   # старт ≥ quarters — фаза вне горизонта
    return starts


def scenario_schedule(spec: dict, scenario: dict, drivers: list[str], n: int, quarters: int, seed: int) -> dict:
    """Расписание сценария на путь и квартал: mu[d] (n,T), logvol[d] (n,T), corr_idx (n,T) → corr_mats (список матриц),
    starts {phase_id: (n,)}, phase_share {phase_id: доля путь-кварталов в активном состоянии (ramp+плато+decay)}."""
    phases = scenario.get("phases") or []
    t = np.arange(quarters, dtype=float)[None, :]
    mu = {d: np.zeros((n, quarters)) for d in drivers}; lv = {d: np.zeros((n, quarters)) for d in drivers}
    rho = {d: np.full((n, quarters), np.nan) for d in drivers}   # NaN = null (базовая персистентность)
    ids, R0, _ = root_correlation(spec)
    mats: list = [R0]; keys: dict = {("base",): 0}
    corr_idx = np.zeros((n, quarters), dtype=np.int32)
    starts = phase_starts(scenario, n, quarters, seed)
    share = {}

    def mat_index(key, builder):
        if key not in keys:
            keys[key] = len(mats); mats.append(builder())
        return keys[key]

    rows = np.arange(n)
    for k, ph in enumerate(phases):
        pid = ph["phase_id"]; s_i = starts[pid]; s = s_i[:, None].astype(float)
        if k + 1 < len(phases):
            nxt = starts[phases[k + 1]["phase_id"]]
            if (nxt < s_i).any():
                raise ValueError(f"фаза {phases[k + 1]['phase_id']} стартует раньше фазы {pid} на {(nxt < s_i).sum()} путях — старты фаз должны быть монотонны (§12)")
            nxt = nxt[:, None].astype(float)
        else:
            nxt = np.full((n, 1), float(quarters))
        ramp = int(ph.get("ramp_quarters") or 0); dur = ph.get("duration_quarters", "until_end"); dec = int(ph.get("decay_quarters") or 0)
        Tk = phase_correlation(spec, ph); tk_idx = mat_index(("phase", k), lambda Tk=Tk: Tk)
        ov = ph.get("driver_overrides") or {}
        for d, o in ov.items():
            po = o.get("persistence_override")
            if po is not None and not (0.0 <= float(po) <= 0.99):
                raise ValueError(f"фаза {pid}, драйвер {d}: persistence_override {po} вне [0, 0.99]")
        # регионы фазы на путь (кварталы), все — до старта следующей фазы: ramp s…s+ramp−1 (доля (t−s+1)/ramp от состояния в квартале
        # s−1 к целевому), плато, decay pe…pe+dec−1 (к BASE), после — BASE
        started = (t >= s) & (t < nxt)
        in_ramp = started & (t < s + ramp)
        lam = np.clip((t - s + 1.0) / ramp, 0.0, 1.0) if ramp > 0 else np.ones((n, quarters))
        if isinstance(dur, int):
            pe = s + ramp + dur
            in_plateau = started & ~in_ramp & (t < pe)
            in_decay = started & (t >= pe) & (t < pe + dec)
            a_dec = np.clip(1.0 - (t - pe + 1.0) / dec, 0.0, 1.0) if dec > 0 else np.zeros((n, quarters))
            after = started & (t >= pe + dec)
        else:
            pe = None
            in_plateau = started & ~in_ramp
            in_decay = np.zeros((n, quarters), dtype=bool); a_dec = np.zeros((n, quarters)); after = np.zeros((n, quarters), dtype=bool)
        share[pid] = float((in_ramp | in_plateau | in_decay).mean())
        prev_q = np.clip(s_i - 1, 0, quarters - 1)
        for d in drivers:
            o = ov.get(d) or {}
            tm = float(o.get("mean_shift_sigma", 0.0)); tl = math.log(float(o.get("volatility_multiplier", 1.0)))
            for S, target in ((mu[d], tm), (lv[d], tl)):
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
            R_[:] = new
        # корреляции: ramp — смесь матрицы квартала s−1 (по пути) и целевой; плато — целевая; decay — смесь целевой и базовой
        prev_idx = np.where(s_i > 0, corr_idx[rows, prev_q], 0)
        if ramp > 0:
            step = np.rint(t - s + 1.0).astype(int)
            for j in range(1, ramp + 1):
                m_step = in_ramp & (step == j)
                if not m_step.any():
                    continue
                lamj = j / ramp
                for pv in np.unique(prev_idx[m_step.any(axis=1)]):
                    sel = m_step & (prev_idx[:, None] == pv)
                    if lamj >= 1.0:
                        corr_idx[sel] = tk_idx
                    else:
                        idx = mat_index(("blend", int(pv), k, j), lambda pv=int(pv), lamj=lamj, Tk=Tk: (1.0 - lamj) * mats[pv] + lamj * Tk)
                        corr_idx[sel] = idx
        corr_idx[in_plateau] = tk_idx
        if pe is not None and dec > 0:
            step = np.rint(t - pe + 1.0).astype(int)
            for j in range(1, dec + 1):
                m_step = in_decay & (step == j)
                if m_step.any():
                    a = 1.0 - j / dec
                    idx = 0 if a <= 0 else mat_index(("decay", k, j), lambda a=a, Tk=Tk: a * Tk + (1.0 - a) * R0)
                    corr_idx[m_step] = idx
        corr_idx[after] = 0
    return {"mu": mu, "logvol": lv, "rho": rho, "corr_idx": corr_idx, "corr_mats": mats, "starts": starts, "phase_share": share, "n_corr_states": len(mats)}


def _repersist(x: np.ndarray, eta: np.ndarray, rho: np.ndarray) -> np.ndarray:
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
    return U


def root_paths(spec: dict, n: int, quarters: int, seed: int, antithetic: bool = True, corr_schedule: tuple | None = None):
    """(n, K, quarters) стационарные AR(1) траектории root-факторов; детерминированно по seed.
    corr_schedule = (mats, idx (n,T)): матрица корреляций инноваций по пути и кварталу (сценарий); одни и те же iid-инновации."""
    ids, R, _ = root_correlation(spec)
    phi = np.array([float(spec["root_factors"]["factors"][k].get("phi", 0.0)) for k in ids])
    if corr_schedule is None:
        Ls = [np.linalg.cholesky(R)]; idx = None
    else:
        mats, idx = corr_schedule
        Ls = []
        for M in mats:
            w = np.linalg.eigvalsh(M)
            if w.min() < -1e-10:
                raise ValueError("матрица корреляций фазы не PSD")
            Ls.append(np.linalg.cholesky(M + np.eye(len(ids)) * 1e-12) if w.min() < 1e-10 else np.linalg.cholesky(M))
    rng = np.random.default_rng(seed)
    half = n // 2 if antithetic else n

    def innov(tq):
        z = rng.standard_normal((half, len(ids)))
        z = np.vstack([z, -z])[:n] if antithetic else z[:n]
        if idx is None:
            return z @ Ls[0].T
        u = np.empty_like(z)
        col = idx[:, tq]
        for m in np.unique(col):
            rows = col == m
            u[rows] = z[rows] @ Ls[int(m)].T
        return u

    F = np.empty((n, len(ids), quarters))
    F[:, :, 0] = innov(0)  # стационарный старт: F_0 ~ N(0, R)
    for tq in range(1, quarters):
        F[:, :, tq] = phi[None, :] * F[:, :, tq - 1] + np.sqrt(1 - phi ** 2)[None, :] * innov(tq)
    return ids, F


def is_phased(scenario: dict | None) -> bool:
    return bool(scenario and scenario.get("phases"))


def driver_shocks(spec: dict, drivers: list[str], n: int, quarters: int, seed: int, antithetic: bool = True,
                  scenario: dict | None = None):
    """dict driver → (n, quarters) стандартизированных шоков. Драйвер без mapping — чисто идиосинкратический.
    Сценарий: legacy (постоянные driver_overrides) или фазовый (scenario_schedule)."""
    sched = scenario_schedule(spec, scenario, drivers, n, quarters, seed) if is_phased(scenario) else None
    ids, F = root_paths(spec, n, quarters, seed, antithetic, (sched["corr_mats"], sched["corr_idx"]) if sched and sched["n_corr_states"] > 1 else None)
    ids_i = {k: i for i, k in enumerate(ids)}
    _, R, _ = root_correlation(spec)
    maps = (spec.get("driver_generation") or {}).get("mappings") or {}
    rng = np.random.default_rng(seed + 7919)  # отдельный поток для идиосинкратических шоков драйверов (детерминирован seed'ом)
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
            x = sched["mu"][d] + np.exp(sched["logvol"][d]) * x
        else:
            o = legacy.get(d) or {}
            if o.get("volatility_multiplier") is not None:
                x = x * float(o["volatility_multiplier"])
            if o.get("mean_shift_sigma") is not None:
                x = x + float(o["mean_shift_sigma"])
        out[d] = x
    return out


def persistence_diagnostics(spec: dict, scenario: dict, drivers: list[str], n: int, quarters: int, seed: int, warmup: int = 4) -> dict:
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


def scenario_diagnostics(spec: dict, scenario: dict, drivers: list[str], n: int, quarters: int, seed: int) -> dict:
    """Диагностика фаз для отчёта: квантили стартов, доли активных путь-кварталов, число матриц корреляций, неохваченные драйверы."""
    if not is_phased(scenario):
        return {"phased": False}
    sched = scenario_schedule(spec, scenario, drivers, n, quarters, seed)
    sdrv = sorted({d for ph in scenario.get("phases") or [] for d in (ph.get("driver_overrides") or {})})
    return {"phased": True, "scenario_id": scenario.get("scenario_id"),
            "phase_start_quantiles": {pid: {q: float(np.quantile(st, float(q))) for q in ("0.1", "0.5", "0.9")} for pid, st in sched["starts"].items()},
            "phase_active_share": sched["phase_share"], "n_corr_states": sched["n_corr_states"],
            "scenario_drivers_applicable": [d for d in sdrv if d in drivers], "scenario_drivers_unmapped": [d for d in sdrv if d not in drivers]}


def effective_shock(x: np.ndarray, lag_quarters: int = 0, decay_half_life_quarters: float | None = None) -> np.ndarray:
    """Эффект драйвера на параметр: сдвиг на lag и экспоненциальное сглаживание с half-life (память эффекта)."""
    n, T = x.shape
    y = np.zeros_like(x)
    if lag_quarters > 0:
        y[:, lag_quarters:] = x[:, :T - lag_quarters]
    else:
        y = x.copy()
    if decay_half_life_quarters and decay_half_life_quarters > 0:
        a = 0.5 ** (1.0 / float(decay_half_life_quarters))
        z = np.zeros_like(y); s = np.zeros(n)
        for t in range(T):
            s = a * s + (1 - a) * y[:, t]; z[:, t] = s
        # нормировка, чтобы стационарная дисперсия сглаженного шока ≈ 1 (эффект в «сигмах»)
        z = z / math.sqrt((1 - a) / (1 + a))
        return z
    return y
