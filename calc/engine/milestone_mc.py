"""Архетип C — pre_service_or_milestone_driven (MC_Calibration_Archetypes v1.0 §5), срез 3 company_mc.

Слой вех: каждая веха — Bernoulli(p) при выполненных предпосылках, срок = max(срок предпосылок) + собственная задержка
(распределение, кварталы); отказ — terminal_failure (веха и всё, что от неё зависит, не достигаются) либо delay_retry
(повтор с retry_probability через retry_delay_quarters). Веха `service_onset` открывает сервисную выручку.
Денежный слой: до запуска сервиса — квартальное сжигание (распределение), после — FCF сервиса по маржинальной траектории
от старта (mean reversion от current_margin_at_onset к terminal) плюс FCF существующего ядра (постоянная маржа).
Если кэш уходит в минус — недостаток считается привлечённым капиталом, стоимость держателей уменьшается на
привлечённое × (1 + dilution_penalty) (интерпретация движка C1).
Кусочная оценка на горизонте (valuation_basis на путь): terminal_failure → failure_residual (net cash + reference ×
residual_on_failure); сервис не запущен → milestone_conditioned_EV (net cash + reference × Σ uplift достигнутых вех);
сервис запущен, FCF-маржа сервиса за последний год < fcf_maturity_margin → revenue_bridge; иначе → FCF_multiple.
Коды basis: 0 multiple, 1 revenue_bridge, 2 fallback, 3 milestone_conditioned_EV, 4 failure_residual.

Схема калибровки (дополнительно к общей):
milestone_model:
  service_onset_milestone: <id>
  reference_value: <dist>            # $; стоимость при достижении всех вех (model_assumption; не из цены)
  residual_on_failure: 0.1           # доля reference при terminal_failure
  milestones:
    - {id, probability, requires: [ids], timing: <dist кварталов задержки>, value_uplift: 0..1,
       on_failure: {branch: terminal_failure | delay_retry, retry_probability, retry_delay_quarters}}
revenue_model:
  existing_segments: {<Имя>: {как в A/B}}   (может быть пусто)
  service_segments: {<Имя>: {initial_annual_revenue: <dist>, post_service_growth: <dist>, long_run_growth_y8: <dist>, growth_half_life_years}}
cash_model:
  net_cash_0: <$>; pre_service_burn_quarterly: <dist $>; dilution_penalty: 0.2
  core_margin: <dist> (FCF-маржа существующего ядра); service_margin: {current_margin_at_onset, terminal_margin_Y5: <dist>, half_life_years}
valuation:
  fcf_maturity_margin: 0.10; multiple_fcf: <dist>; multiple_revenue_bridge: <dist>
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import ndtr

QUARTERS = 32
HORIZON_Q = {"Y3": 11, "Y5": 19, "Y8": 31}
BASIS = {"multiple": 0, "revenue_bridge": 1, "fallback": 2, "milestone_conditioned_EV": 3, "failure_residual": 4}


def _order(milestones: list[dict]) -> list[dict]:
    """Топологический порядок по requires."""
    by_id = {m["id"]: m for m in milestones}
    out, seen = [], set()
    def visit(mid, stack=()):
        if mid in seen:
            return
        if mid in stack:
            raise ValueError(f"цикл в requires у вехи {mid}")
        m = by_id[mid]
        for r in m.get("requires") or []:
            if r not in by_id:
                raise ValueError(f"веха {mid} требует неизвестную {r}")
            visit(r, stack + (mid,))
        seen.add(mid); out.append(m)
    for m in milestones:
        visit(m["id"])
    return out


def simulate_milestones(draw, cal: dict, eff: dict):
    """Возвращает (achieved_q: dict id→(n,) квартал достижения или INF, failed: dict id→(n,) bool терминального отказа)."""
    from engine.company_mc import dist_ppf  # локальный импорт — избегаем циклического
    mm = cal["milestone_model"]; n = draw.n; rng = draw.rng
    INF = 10 ** 6
    ach, failed = {}, {}
    padj = eff.get("milestone_prob_logit", {}); tadj = eff.get("milestone_timing", {})
    for m in _order(mm["milestones"]):
        mid = m["id"]
        req = m.get("requires") or []
        prereq_q = np.zeros(n)
        prereq_fail = np.zeros(n, dtype=bool)
        for r in req:
            prereq_q = np.maximum(prereq_q, ach[r]); prereq_fail |= failed[r]
        p = float(m["probability"])
        logit = math.log(p / (1 - p)) if 0 < p < 1 else (30.0 if p >= 1 else -30.0)
        if mid in padj:
            pv = 1 / (1 + np.exp(-(logit + padj[mid])))
        else:
            pv = np.full(n, p)
        u = draw.u("growth", (m.get("latent_loading") or {}).get("execution"))  # общая «исполнительская» неопределённость через фактор роста
        ok = u < pv
        delay = dist_ppf(rng.random(n), m["timing"])
        if mid in tadj:
            delay = delay + tadj[mid]
        delay = np.maximum(delay, 0.0)
        of = m.get("on_failure") or {"branch": "terminal_failure"}
        if of.get("branch") == "delay_retry":
            retry = rng.random(n) < float(of.get("retry_probability", 0.5))
            delay = np.where(ok, delay, delay + float(of.get("retry_delay_quarters", 4)))
            ok2 = ok | retry
            fail = ~ok2
        else:
            ok2 = ok; fail = ~ok
        q = np.where(ok2 & ~prereq_fail & (prereq_q < INF), prereq_q + delay, INF)
        fail_all = fail | prereq_fail | (prereq_q >= INF)
        ach[mid] = np.where(fail_all, INF, q); failed[mid] = fail_all
    return ach, failed


def simulate_chunk(draw, cal: dict, E0: float, P: dict, eff: dict):
    from engine.company_mc import dist_ppf, _max_drawdown
    n = draw.n; rng = draw.rng; INF = 10 ** 6
    mm = cal["milestone_model"]; cm_ = cal["cash_model"]; vm = cal["valuation"]
    ach, failed = simulate_milestones(draw, cal, eff)
    onset_id = mm["service_onset_milestone"]
    onset_q = ach[onset_id]                      # квартал запуска сервиса (INF — не запущен)
    term_fail = failed[onset_id]                 # терминальный отказ по цепочке до сервиса
    t_idx = np.arange(QUARTERS)[None, :]
    t_years = (np.arange(1, QUARTERS + 1) / 4.0)[None, :]
    # существующее ядро
    rev_core = np.zeros((n, QUARTERS))
    for name, seg in (cal["revenue_model"].get("existing_segments") or {}).items():
        ll = (seg.get("latent_loading") or {}).get("growth")
        g0 = dist_ppf(draw.u("growth", ll), seg["initial_growth"], shift=P["growth_shift"]); g8 = dist_ppf(draw.u("growth", ll), seg["long_run_growth_y8"], shift=P["growth_shift"])
        g = g8[:, None] + (g0 - g8)[:, None] * np.power(2.0, -t_years / float(seg["growth_half_life_years"]))
        if name in eff["growth_add"]: g = g + eff["growth_add"][name]
        if name in eff["growth_mul"]: g = g * eff["growth_mul"][name]
        rev_core += float(seg["base_revenue_quarterly"]) * np.cumprod(np.power(1.0 + np.maximum(g, -0.95), 0.25), axis=1)
    # сервисная выручка от запуска
    rev_srv = np.zeros((n, QUARTERS))
    since = t_idx - onset_q[:, None]             # кварталов с запуска (отрицательно до)
    active = (since >= 0) & (onset_q[:, None] < INF)
    for name, seg in (cal["revenue_model"].get("service_segments") or {}).items():
        ll = (seg.get("latent_loading") or {}).get("growth")
        r0 = dist_ppf(draw.u("growth", ll), seg["initial_annual_revenue"]) / 4.0
        g0 = dist_ppf(draw.u("growth", ll), seg["post_service_growth"], shift=P["growth_shift"]); g8 = dist_ppf(draw.u("growth", ll), seg["long_run_growth_y8"], shift=P["growth_shift"])
        sy = np.clip(since, 0, None) / 4.0
        g = g8[:, None] + (g0 - g8)[:, None] * np.power(2.0, -sy / float(seg["growth_half_life_years"]))
        if name in eff["growth_add"]: g = g + eff["growth_add"][name]
        if name in eff["growth_mul"]: g = g * eff["growth_mul"][name]
        qf = np.where(active, np.power(1.0 + np.maximum(g, -0.95), 0.25), 1.0)
        # рост начинается со второго квартала после запуска
        qf = np.where(since <= 0, 1.0, qf)
        rev_srv += np.where(active, r0[:, None] * np.cumprod(qf, axis=1), 0.0)
    rev_q = rev_core + rev_srv
    # денежный слой
    ms = P["margin_shift"]
    core_m = dist_ppf(draw.u("margin"), cm_["core_margin"], shift=ms) if "core_margin" in cm_ else np.zeros(n)
    sm = cm_["service_margin"]
    m0 = float(sm["current_margin_at_onset"]) + ms
    m5 = dist_ppf(draw.u("margin"), sm["terminal_margin_Y5"], shift=ms)
    if "terminal_margin_Y5" in eff["margin_add"]: m5 = m5 + eff["margin_add"]["terminal_margin_Y5"]
    hl = float(sm["half_life_years"])
    srv_m = m5[:, None] + (m0 - m5)[:, None] * np.power(2.0, -np.clip(since, 0, None) / 4.0 / hl)
    burn = dist_ppf(rng.random(n), cm_["pre_service_burn_quarterly"])   # $/квартал до запуска (положительное число)
    fcf_q = np.where(active, rev_srv * srv_m, -burn[:, None]) + rev_core * core_m[:, None]
    cash = float(cm_["net_cash_0"]) + np.cumsum(fcf_q, axis=1)
    raised = np.maximum(0.0, -np.minimum.accumulate(cash, axis=1))   # накопленный дефицит = привлечённый капитал
    net_cash = np.maximum(cash, 0.0)
    pen = float(cm_.get("dilution_penalty", 0.2))
    ref = dist_ppf(draw.u("valuation"), mm["reference_value"], scale=P["mult_factor"])
    resid = float(mm.get("residual_on_failure", 0.0))
    up = {m["id"]: float(m.get("value_uplift", 0.0)) for m in mm["milestones"]}
    from engine.company_mc import crossover_mode, crossover_value, CROSSOVER_PARITY
    mult_fcf = dist_ppf(draw.u("valuation"), vm["multiple_fcf"], scale=P["mult_factor"])
    mult_rb = dist_ppf(draw.u("valuation"), vm["multiple_revenue_bridge"], scale=P["mult_factor"])
    mat = float(vm.get("fcf_maturity_margin", 0.10))
    parity_mode = crossover_mode(cal) == CROSSOVER_PARITY   # v1.1.3 §16.6: m_elig = fcf_maturity_margin, далее parity-gated blend
    rev_y = rev_q.reshape(n, 8, 4).sum(axis=2); fcf_y = fcf_q.reshape(n, 8, 4).sum(axis=2)
    srv_y = rev_srv.reshape(n, 8, 4).sum(axis=2)
    E, B, MS, PM = {}, {}, {}, {}
    for h, q in HORIZON_Q.items():
        yi = (q + 1) // 4 - 1
        achieved_up = np.zeros(n)
        for mid, u_ in up.items():
            achieved_up += np.where(ach[mid] <= q, u_, 0.0)
        for h2 in (h,):
            if h2 in eff["mult_mul"]:
                pass
        started = onset_q <= q
        srv_margin_ttm = np.where(srv_y[:, yi] > 0, fcf_y[:, yi] / np.where(rev_y[:, yi] > 0, rev_y[:, yi], 1.0), -1.0)
        mm_h = eff["mult_mul"].get(h, 1.0)
        v_fail = net_cash[:, q] + ref * resid
        v_pre = net_cash[:, q] + ref * achieved_up
        v_rb = rev_y[:, yi] * mult_rb * mm_h + net_cash[:, q]
        v_fcf = fcf_y[:, yi] * mult_fcf * mm_h + net_cash[:, q]
        pm = np.full(n, np.nan)
        if parity_mode:
            # сервис запущен: margin < m_elig → bridge (код 1); m_elig ≤ m < m_start → bridge (5); смесь (6); FCF-база (0)
            v_x, code_x, pm_x = crossover_value(srv_margin_ttm, rev_y[:, yi] * mult_rb * mm_h, fcf_y[:, yi] * mult_fcf * mm_h, mult_rb, mult_fcf, mat, BASIS["revenue_bridge"])
            basis = np.where(term_fail, BASIS["failure_residual"], np.where(~started, BASIS["milestone_conditioned_EV"], code_x))
            val = np.where(term_fail, v_fail, np.where(~started, v_pre, v_x + net_cash[:, q]))
            pm = np.where(started & ~term_fail, pm_x, np.nan)
        else:
            mature = started & (srv_margin_ttm >= mat) & (fcf_y[:, yi] > 0)
            basis = np.where(term_fail, BASIS["failure_residual"], np.where(~started, BASIS["milestone_conditioned_EV"], np.where(mature, BASIS["multiple"], BASIS["revenue_bridge"])))
            val = np.where(term_fail, v_fail, np.where(~started, v_pre, np.where(mature, v_fcf, v_rb)))
        val = np.maximum(val - raised[:, q] * (1.0 + pen), 1.0)
        E[h], B[h] = val, basis
        PM[h] = pm
        MS[h] = np.where(term_fail, 2, np.where(started, 1, 0))   # 0 pre-service, 1 service, 2 failed
    dd = _max_drawdown(rng, n, cal, E0, E["Y3"], E["Y5"], E["Y8"])
    base_annual = 4.0 * (sum(float(s["base_revenue_quarterly"]) for s in (cal["revenue_model"].get("existing_segments") or {}).values()) or 0.0)
    return {"E3": E["Y3"], "E5": E["Y5"], "E8": E["Y8"], "maxdd5": dd, "b3": B["Y3"], "b5": B["Y5"], "b8": B["Y8"],
            "pm3": PM["Y3"], "pm5": PM["Y5"], "pm8": PM["Y8"],
            "rev5": rev_y[:, 4], "m5": np.where(rev_y[:, 4] > 0, fcf_y[:, 4] / np.where(rev_y[:, 4] > 0, rev_y[:, 4], 1.0), 0.0),
            "base_annual": base_annual if base_annual > 0 else np.nan,
            "ms3": MS["Y3"], "ms5": MS["Y5"], "ms8": MS["Y8"], "onset_q": np.where(onset_q >= INF, -1, onset_q).astype(float),
            "warnings": eff["warnings"]}


def summarize_extra(acc: dict) -> dict:
    out = {"milestone_state_share": {}, "service_onset": {}}
    for h, key in (("Y3", "ms3"), ("Y5", "ms5"), ("Y8", "ms8")):
        m = acc[key]
        out["milestone_state_share"][h] = {"pre_service": float((m == 0).mean()), "service_started": float((m == 1).mean()), "terminal_failure": float((m == 2).mean())}
    oq = acc["onset_q"]; ok = oq >= 0
    out["service_onset"] = {"P_onset_within_8Y": float(ok.mean()),
                            "median_onset_quarter": float(np.median(oq[ok])) if ok.any() else None,
                            "P_onset_by_Y3": float((ok & (oq <= HORIZON_Q["Y3"])).mean()), "P_onset_by_Y5": float((ok & (oq <= HORIZON_Q["Y5"])).mean())}
    return out
