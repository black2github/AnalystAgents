"""Conviction Overlay v1.0: лимит вложенного капитала, индивидуальные потолки из бюджета потери, мягкий/жёсткий разрыв,
секторные пороги (Conviction_Overlay_Specification_v1.0, 21.09.2026). Детерминированно; не торговый сигнал (trigger ≠ decision).

inputs:
  positions: [{ticker, sector_id, market_value, cost_basis, archetype | plausible_drawdown, conviction (bool), theme (опц.)}]
    (позиции одного тикера на разных счетах — суммировать до вызова)
  cash: float — кэш и эквиваленты (входит в risk capital basis, не в позиции)
  params: {L_max_standard, L_max_conviction, target_safety_buffer, plausible_drawdown_floor/ceiling,
           standard_hard_cap_floor/ceiling, conviction_hard_cap_floor/ceiling,
           invested_capital: {standard_name_limit, conviction_name_limit, sector_limit},
           sector_market: {soft_limit, hard_limit}, archetype_fallback: {archetype: dd}}
outputs: per asset — invested_share, invested_limit, invested_gap, incremental_buy_capacity, plausible_drawdown, hard_cap,
  target_cap, market_weight, expected_loss_at_dd, concentration_gap (none|soft|hard_loss_budget_breach), block_new_buys,
  decision_request, weight_to_restore_budget; sectors — invested_share vs limit, market_weight vs soft/hard; summary.
"""
from __future__ import annotations

VERSION = "1.0.0"
SPEC_VERSION = "1.0"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def run(inputs: dict, seed: int) -> dict:
    pos = inputs.get("positions") or []
    cash = float(inputs.get("cash") or 0.0)
    P = inputs.get("params") or {}
    ic = P.get("invested_capital") or {}
    sm = P.get("sector_market") or {}
    fb = P.get("archetype_fallback") or {}
    if not pos:
        raise ValueError("positions пуст")
    for p in pos:
        if float(p.get("market_value", 0)) < 0 or float(p.get("cost_basis", 0)) < 0:
            raise ValueError(f"{p.get('ticker')}: market_value/cost_basis должны быть неотрицательными")
    nav = sum(float(p["market_value"]) for p in pos) + cash
    risk_capital = sum(float(p["cost_basis"]) for p in pos) + cash
    if nav <= 0 or risk_capital <= 0:
        raise ValueError("NAV и risk capital basis должны быть положительными")

    out_assets = []
    sec_inv: dict[str, float] = {}
    sec_mv: dict[str, float] = {}
    for p in pos:
        tk = p.get("ticker"); conv = bool(p.get("conviction", False))
        mv, cb = float(p["market_value"]), float(p["cost_basis"])
        w = mv / nav; ish = cb / risk_capital
        sid = p.get("sector_id")
        if sid:
            sec_inv[sid] = sec_inv.get(sid, 0.0) + ish
            sec_mv[sid] = sec_mv.get(sid, 0.0) + w
        # лимит вложенного капитала (только новые покупки)
        ilim = float(ic.get("conviction_name_limit" if conv else "standard_name_limit", 1.0))
        igap = max(0.0, ish - ilim)
        cap_usd = max(0.0, ilim * risk_capital - cb)   # приближение: докупка на X увеличивает и числитель, и знаменатель
        # правдоподобная просадка
        dd_src = "input"
        dd = p.get("plausible_drawdown")
        if dd is None:
            dd = fb.get(p.get("archetype")); dd_src = "archetype_fallback"
        if dd is None:
            entry = {"ticker": tk, "sector_id": sid, "market_weight": round(w, 4), "invested_share": round(ish, 4),
                     "invested_limit": ilim, "invested_gap": round(igap, 4), "incremental_buy_capacity_usd": round(cap_usd, 2),
                     "plausible_drawdown": None, "note": "нет архетипа/просадки — потолок не считается (не компания?)",
                     "conviction": conv, "concentration_gap": "not_applicable", "block_new_buys": igap > 0, "decision_request": None}
            out_assets.append(entry); continue
        dd = _clamp(abs(float(dd)), float(P.get("plausible_drawdown_floor", 0.0)), float(P.get("plausible_drawdown_ceiling", 1.0)))
        L = float(P["L_max_conviction" if conv else "L_max_standard"])
        lo = float(P.get("conviction_hard_cap_floor" if conv else "standard_hard_cap_floor", 0.0))
        hi = float(P.get("conviction_hard_cap_ceiling" if conv else "standard_hard_cap_ceiling", 1.0))
        hard = _clamp(L / dd, lo, hi)
        target = float(P.get("target_safety_buffer", 1.0)) * hard
        loss = w * dd
        if w > hard:
            gap = "hard_loss_budget_breach"; dr = "MANDATORY_RISK_REDUCTION_REVIEW"
        elif w > target:
            gap = "soft"; dr = None
        else:
            gap = "none"; dr = None
        out_assets.append({
            "ticker": tk, "sector_id": sid, "conviction": conv, "market_weight": round(w, 4), "invested_share": round(ish, 4),
            "invested_limit": ilim, "invested_gap": round(igap, 4), "incremental_buy_capacity_usd": round(cap_usd, 2),
            "plausible_drawdown": round(dd, 4), "plausible_drawdown_source": dd_src, "L_max": L,
            "hard_cap": round(hard, 4), "target_cap": round(target, 4), "expected_loss_at_dd_NAV": round(loss, 4),
            "concentration_gap": gap, "block_new_buys": bool(gap != "none" or igap > 0), "decision_request": dr,
            "weight_to_restore_budget": round(L / dd, 4) if gap == "hard_loss_budget_breach" else None,
        })
    sectors = {}
    for sid in set(list(sec_inv) + list(sec_mv)):
        inv, mv = sec_inv.get(sid, 0.0), sec_mv.get(sid, 0.0)
        soft, hard = float(sm.get("soft_limit", 1.0)), float(sm.get("hard_limit", 1.0))
        st = "hard" if mv > hard else ("soft" if mv > soft else "none")
        sectors[sid] = {"invested_share": round(inv, 4), "invested_limit": float(ic.get("sector_limit", 1.0)),
                        "invested_gap": round(max(0.0, inv - float(ic.get("sector_limit", 1.0))), 4),
                        "market_weight": round(mv, 4), "market_soft_limit": soft, "market_hard_limit": hard, "market_gap": st,
                        "block_new_buys": bool(st != "none" or inv > float(ic.get("sector_limit", 1.0))),
                        "decision_request": "SECTOR_CONCENTRATION_REVIEW" if st == "hard" else None}
    breaches = [a["ticker"] for a in out_assets if a.get("concentration_gap") == "hard_loss_budget_breach"]
    softs = [a["ticker"] for a in out_assets if a.get("concentration_gap") == "soft"]
    blocked = [a["ticker"] for a in out_assets if a.get("block_new_buys")]
    return {
        "model_version": VERSION, "spec_version": SPEC_VERSION,
        "nav_base": round(nav, 2), "risk_capital_basis": round(risk_capital, 2), "cash_weight": round(cash / nav, 4),
        "assets": out_assets, "sectors": sectors,
        "summary": {"hard_loss_budget_breaches": breaches, "soft_concentration_gaps": softs, "new_buys_blocked": blocked,
                    "conviction_active": [a["ticker"] for a in out_assets if a.get("conviction")]},
        "decision": "none",
        "note": "trigger ≠ decision: разрывы и запросы — материал для Decision Request владельцу, не сделки (спецификация §1.3, §5)",
    }
