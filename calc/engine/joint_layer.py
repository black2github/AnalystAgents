"""Joint Simulation Layer v1.0 (Joint_Simulation_Layer_Specification_v1.0, 21.09.2026) — срез 2 company_mc.

Root-факторы: стационарные AR(1) N(0,1), квартальный шаг: F_t = phi·F_{t-1} + sqrt(1−phi²)·u_t, u ~ MVN(0, R_root).
Драйверы: Raw_d,t = Σ_k λ_dk F_k,t + σ_idio,d ε_d,t → стандартизация к unit variance (теоретическая, стационарная).
Общий путь: одна и та же пара (global_seed, path_index) даёт один и тот же набор root/driver шоков для любой компании —
массивы не передаются между вызовами, а воспроизводятся детерминированно (инвариант «same factor path for all companies»).
Сценарий (Scenario Engine): driver_overrides {mean_shift_sigma, volatility_multiplier}; без него — BASE.
Фазы (1.1.0, ЧЕРНОВИК до спецификации Scenario Engine v1.0 IMMA): scenario.phases = [{phase_id, effective_from: квартал от t0
(число) или распределение {distribution: uniform|triangular, min, mode, max} (розыгрыш на путь), after_phase: id предыдущей фазы
(+ offset — число/распределение — от конца её плато), ramp_quarters, duration_quarters|null (до конца), decay_quarters,
driver_overrides}]. Профиль m_i(t) ∈ [0,1] на путь: 0 до начала, линейный подъём ramp, плато duration, линейный спад decay.
Сдвиг: x += shift·m(t); волатильность: x *= 1 + (vm − 1)·m(t); фазы суммируются (сдвиги) и перемножаются (волатильность).
Legacy top-level driver_overrides без phases = одна фаза с t0 до конца (m ≡ 1) — прежние результаты не меняются.
root_correlation_overrides по фазам — НЕ реализовано (ждём спецификацию).
"""
from __future__ import annotations

import math

import numpy as np

VERSION = "1.1.0"


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


def root_paths(spec: dict, n: int, quarters: int, seed: int, antithetic: bool = True):
    """(n, K, quarters) стационарные AR(1) траектории root-факторов; детерминированно по seed."""
    ids, R, _ = root_correlation(spec)
    phi = np.array([float(spec["root_factors"]["factors"][k].get("phi", 0.0)) for k in ids])
    L = np.linalg.cholesky(R)
    rng = np.random.default_rng(seed)
    half = n // 2 if antithetic else n
    def mvn(m):
        z = rng.standard_normal((m, len(ids)))
        return z @ L.T
    F = np.empty((n, len(ids), quarters))
    u0 = mvn(half); u0 = np.vstack([u0, -u0])[:n] if antithetic else u0[:n]
    F[:, :, 0] = u0  # стационарный старт: F_0 ~ N(0, R)
    for t in range(1, quarters):
        u = mvn(half); u = np.vstack([u, -u])[:n] if antithetic else u[:n]
        F[:, :, t] = phi[None, :] * F[:, :, t - 1] + np.sqrt(1 - phi ** 2)[None, :] * u
    return ids, F


def _draw_quarters(spec_v, n: int, rng: np.random.Generator) -> np.ndarray:
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
    for d in drivers:
        m = maps.get(d)
        if m:
            lam = np.zeros(len(ids))
            for k, v in (m.get("roots") or {}).items():
                lam[ids_i[k]] = float(v)
            idio = float(m.get("idio_weight", 0.0))
            raw = np.einsum("k,nkt->nt", lam, F) + idio * rng.standard_normal((n, quarters))
            var = float(lam @ R @ lam) + idio ** 2
        else:
            raw = rng.standard_normal((n, quarters)); var = 1.0
        x = raw / math.sqrt(var) if var > 0 else raw
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
    return out


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
