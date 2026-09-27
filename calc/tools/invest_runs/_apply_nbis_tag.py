"""22.09: пометка «доверяю» на NBIS с исключением (ось Capacity_Secured pending_verification — нераскрытие факта, не ухудшение);
журнал portfolio/_conviction_journal.yaml по Conviction_Journal_Schema_v1.0; прогон overlay с пометкой → machine_outputs."""
import json, urllib.request
from pathlib import Path
import yaml

TODAY = "2026-09-22"
d = yaml.safe_load(Path("portfolio/_portfolio.yaml").read_text(encoding="utf-8"))
ov = d["constraints"]["conviction_overlay_v1_0"]; params = ov["approved_params"]
run1 = json.load(open("_conviction_run1.json", encoding="utf-8"))["outputs"]
a1 = next(a for a in run1["assets"] if a["ticker"] == "NBIS")
nb = json.loads(Path("portfolio/nbis/state.json").read_text(encoding="utf-8")) if Path("portfolio/nbis/state.json").exists() else None
kp = yaml.safe_load(Path("portfolio/nbis/kpis.yaml").read_text(encoding="utf-8"))
tr = yaml.safe_load(Path("portfolio/nbis/triggers.yaml").read_text(encoding="utf-8"))
neg = [t["id"] for t in tr["triggers"] if t.get("transition") and t["transition"]["from"] > t["transition"]["to"]]
active_neg = [t["id"] for t in tr["triggers"] if t.get("status") == "active" and t["id"] in neg]

entry = {
    "decision_id": "CONV-2026-09-22-NBIS-01", "ticker": "NBIS", "status": "active", "activated_at": TODAY,
    "market_snapshot": {"price": 223.54, "price_source": "Yahoo chart, закрытие 2026-09-18", "portfolio_nav": run1["nav_base"],
                        "market_weight": a1["market_weight"], "sector_weight": run1["sectors"]["AI_COMPUTE"]["market_weight"], "portfolio_regime": "Stress"},
    "basis_snapshot": {"consolidated_open_cost_basis": 20967.51, "invested_capital_share": a1["invested_share"], "legacy_basis_share": a1["invested_share"],
                       "post_system_incremental_basis_share": 0.0},
    "model_snapshot": {"scenario_state_hash": None, "all_axes_verified": False,
                       "axes": {k: {"state": v["state"], "verified": v.get("verified", False)} for k, v in (nb or {}).get("scenario_state", {}).items()},
                       "critical_kpis": [k["id"] for k in kp["critical_kpis"]],
                       "active_negative_triggers": active_neg, "planned_negative_triggers": [t for t in neg if t not in active_neg],
                       "active_X_triggers": [], "company_MC_run_id": None, "plausible_drawdown": 0.75, "plausible_drawdown_source": "archetype_fallback capital_intensive_transition",
                       "team_execution_state": None},
    "conviction_parameters": {"L_max_standard": params["L_max_standard"], "L_max_conviction": params["L_max_conviction"],
                              "target_market_cap_standard": a1["target_cap"], "target_market_cap_conviction": round(0.75 * min(params["L_max_conviction"] / 0.75, 0.45), 4),
                              "hard_loss_budget_cap_standard": a1["hard_cap"], "hard_loss_budget_cap_conviction": round(min(params["L_max_conviction"] / 0.75, 0.45), 4),
                              "owner_judgment_multiplier": 1.0},
    "rationale": {
        "owner_text": "Решение владельца 22.09.2026: NBIS — пометка «доверяю». Основание: основатель построил Яндекс с нуля, ключевая команда сохранена; вход с $45 вопреки консенсусу «дорого», сейчас +181%; готовность на больший риск по этой бумаге.",
        "falsifiable_claims": ["AI cloud revenue растёт ≥100% г/г (KPI-01 green) минимум ещё 2 квартала", "AI cloud adjusted EBITDA margin ≥35% (KPI-04)", "финансирование расширения без liquidity stress (ось Funding_Liquidity не хуже F2)"],
        "what_would_change_my_mind": ["подтверждённый переход вниз по любой оси (E2/E3)", "два подряд квартала ухудшения Critical KPI", "срабатывание X-триггера / thesis break", "превышение бюджета потери 25% NAV"],
    },
    "exception": {
        "rule_waived": "qualification_required: all_state_axes_verified / no_pending_verification_material_axis",
        "axis": "Capacity_Secured", "current": "pending_verification (prior C3)",
        "reason": "Компания раскрыла только цель 5 GW на конец 2026 (KPI-08, guidance); факт законтрактованной мощности на дату (KPI-11) не раскрыт. Это пробел раскрытия, а не ухудшение бизнеса (поправка LLM 21.09). Владелец сознательно принимает исключение.",
        "expires": "при раскрытии факта KPI-11 (ожидается в отчёте Q3 2026) — исключение снимается автоматически; если факт < 3 GW → ось C1/C2 и пересмотр пометки",
        "approved_by": "owner", "approved_at": TODAY,
    },
    "coverage_caveats": ["квартальные негативные переходы NBIS-E-02/E-04/E-06/E-08/E-09 — status planned (models-report-check не заведён); дозор новостей models-news-watch активен (E-06)",
                         "standalone MC NBIS ещё нет — просадка по резерву архетипа 75%"],
    "counterfactual": {"optimizer_run_without_override": None, "weight_without_override": None, "portfolio_metrics_without_override": {},
                       "frozen_at_activation": True, "note": "Optimizer ещё не реализован; контрфакт для сравнения — прогон conviction_overlay без пометки (run 20260921T220020Z-conviction_overlay-ad4f40: hard breach, weight_to_restore 13.3%)"},
    "review_due_at": "2027-09-22",
}
jp = Path("portfolio/_conviction_journal.yaml")
journal = {"version": "1.0", "artifact": "conviction_journal", "schema_ref": "methodology/Conviction_Journal_Schema_v1.0.yaml",
           "rules": "Запись создаётся ДО применения пометки; контрфакт замораживается; обзор через 12 месяцев; лестница навык/удача — спецификация §8.",
           "entries": [entry], "reviews_12m": []}
jp.write_text("# Журнал пометок «доверяю» (Conviction Journal). Проспективная проверка суждений владельца.\n" + yaml.safe_dump(journal, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")

# _portfolio.yaml: active tag + прогон
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
old = "    active_conviction_tags: []          # пометки «доверяю» владелец пока не назначал\n"; assert s.count(old) == 1
s = s.replace(old, '    active_conviction_tags: [NBIS]      # владелец 22.09.2026, с исключением по оси Capacity_Secured — portfolio/_conviction_journal.yaml CONV-2026-09-22-NBIS-01\n', 1)
p.write_text(s, encoding="utf-8")
cand = yaml.safe_load(Path("portfolio/_candidates.yaml").read_text(encoding="utf-8"))
arch = {c["ticker"]: c.get("mc_archetype") for c in cand["pool"] if c.get("ticker")}
agg = {}
for x in d["portfolio"]["positions"]:
    a = agg.setdefault(x["ticker"], {"ticker": x["ticker"], "sector_id": x["sector_id"], "market_value": 0.0, "cost_basis": 0.0, "conviction": x["ticker"] == "NBIS"})
    a["market_value"] += float(x["quantity"]) * float(x["market"]["price"]); a["cost_basis"] += float(x["cost_basis"]["total_usd"])
    if arch.get(x["ticker"]): a["archetype"] = arch[x["ticker"]]
cash = sum(float(c["amount"] or 0) for c in d["portfolio"]["cash"]["accounts"])
inputs = {"positions": list(agg.values()), "cash": cash, "params": params, "as_of": "2026-09-18", "note": "прогон по утверждённым параметрам с активной пометкой NBIS (журнал CONV-2026-09-22-NBIS-01)"}
req = json.dumps({"model": "conviction_overlay", "inputs": inputs, "seed": 0, "save": True}).encode("utf-8")
r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:18791/run", data=req, headers={"Content-Type": "application/json"}), timeout=60))
o = r["outputs"]; rid = r["run_id"]; json.dump(r, open("_conviction_run3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("run:", rid, "| breaches:", o["summary"]["hard_loss_budget_breaches"], "| soft:", o["summary"]["soft_concentration_gaps"], "| buys blocked:", o["summary"]["new_buys_blocked"])
s = p.read_text(encoding="utf-8")
i = s.index("  conviction_overlay:            # прогон conviction_overlay"); j = s.index("\n  dry_powder_status: null", i) if "\n  dry_powder_status: null" in s[i:] else None
# блок conviction_overlay вставлен ПОСЛЕ dry_powder_status → найти его конец по следующему ключу верхнего уровня machine_outputs (timestamp)
k = s.index("  timestamp:", i)
mo = "".join("      - %s\n" % json.dumps({kk: a[kk] for kk in ("ticker", "conviction", "market_weight", "target_cap", "hard_cap", "concentration_gap", "invested_share", "invested_limit", "incremental_buy_capacity_usd", "decision_request") if kk in a}, ensure_ascii=False) for a in sorted(o["assets"], key=lambda x: -x["market_weight"]))
block = '  conviction_overlay:            # прогон conviction_overlay 1.0.0 по утверждённым параметрам, пометка NBIS активна (portfolio/_runs/%s.json)\n    run_id: "%s"\n    active_conviction_tags: ["NBIS"]\n    hard_loss_budget_breaches: %s\n    soft_concentration_gaps: %s\n    new_buys_blocked: %s\n    sectors: %s\n    assets:\n%s' % (
    rid, rid, json.dumps(o["summary"]["hard_loss_budget_breaches"]), json.dumps(o["summary"]["soft_concentration_gaps"]), json.dumps(o["summary"]["new_buys_blocked"]),
    json.dumps({kk: {"market_gap": v["market_gap"], "market_weight": v["market_weight"], "invested_share": v["invested_share"]} for kk, v in o["sectors"].items()}), mo)
s = s[:i] + block + s[k:]
p.write_text(s, encoding="utf-8"); yaml.safe_load(s)
# NBIS state.json: пометка
sp = Path("portfolio/nbis/state.json"); st = json.loads(sp.read_text(encoding="utf-8"))
st["conviction"] = {"status": "active", "since": TODAY, "journal_id": "CONV-2026-09-22-NBIS-01", "L_max": params["L_max_conviction"], "exception": "Capacity_Secured pending_verification (нераскрытие факта)"}
st["info_log"].append({"timestamp": TODAY + "T07:30:00Z", "kind": "owner_decision", "summary": "Пометка «доверяю» активирована владельцем (журнал CONV-2026-09-22-NBIS-01) с исключением по оси Capacity_Secured; L_max 25% NAV; докупки заблокированы лимитом вложенного капитала (22.4% > 20%)"})
st["updated"] = TODAY + "T07:30:00Z"
sp.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("journal + tag ok")
