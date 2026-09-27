"""22.09: утверждённые владельцем параметры Conviction Overlay → _portfolio.yaml; тема AI → _candidates.yaml; правило политики → AGENTS.md;
прогон conviction_overlay через сайдкар по утверждённым параметрам → machine_outputs."""
import json, urllib.request, re
from pathlib import Path
import yaml

APPROVED = {  # решение владельца 22.09.2026 (пп. 1–10)
    "L_max_standard": 0.10, "L_max_conviction": 0.25, "target_safety_buffer": 0.75,
    "plausible_drawdown_floor": 0.25, "plausible_drawdown_ceiling": 0.90,
    "standard_hard_cap_floor": 0.05, "standard_hard_cap_ceiling": 0.30, "conviction_hard_cap_floor": 0.05, "conviction_hard_cap_ceiling": 0.45,
    "invested_capital": {"standard_name_limit": 0.12, "conviction_name_limit": 0.20, "sector_limit": 0.30},
    "sector_market": {"soft_limit": 0.35, "hard_limit": 0.45},
    "conviction": {"max_active_tags": 3, "monitor_missed_runs_before_suspend": 2},
    "team_execution": {"owner_judgment_multiplier_bounds": [0.90, 1.10], "combined_bounds": [0.80, 1.20]},
    "prospective_review": {"horizon_months": 12},
    "archetype_fallback": {"mature_positive_margin": 0.55, "capital_intensive_transition": 0.75, "pre_service_or_milestone_driven": 0.85},
}
AI_THEME = ["NBIS", "CRWV", "NVDA", "ASML", "SPCX", "MSFT", "META", "PLTR", "NET", "CRWD", "ETN", "6506", "6324"]

# 1. _portfolio.yaml: параметры approved + прогон
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
old = "    status: pending_owner_approval # слой НЕ активен; движок и Optimizer его не применяют до утверждения владельцем\n"
assert s.count(old) == 1
s = s.replace(old, '    status: approved_2026_09_22    # владелец утвердил пп. 1–10 (L_max 10% / 25%, буфер 0.75, лимиты вложенного капитала 12/20/30%, сектор 35/45%, теги ≤3, судейский множитель 0.9–1.1, обзор 12 мес.); резервные просадки 55/75/85% — "начнём с этого"\n    approved_params: ' + json.dumps(APPROVED, ensure_ascii=False) + '\n    engine_model: conviction_overlay   # invest-calc 1.0.0; расчёт по утверждённым параметрам — machine_outputs.conviction_overlay\n    active_conviction_tags: []          # пометки «доверяю» владелец пока не назначал\n', 1)
p.write_text(s, encoding="utf-8"); d = yaml.safe_load(s)

cand = yaml.safe_load(Path("portfolio/_candidates.yaml").read_text(encoding="utf-8"))
arch = {c["ticker"]: c.get("mc_archetype") for c in cand["pool"] if c.get("ticker")}
agg = {}
for x in d["portfolio"]["positions"]:
    a = agg.setdefault(x["ticker"], {"ticker": x["ticker"], "sector_id": x["sector_id"], "market_value": 0.0, "cost_basis": 0.0, "conviction": False})
    a["market_value"] += float(x["quantity"]) * float(x["market"]["price"]); a["cost_basis"] += float(x["cost_basis"]["total_usd"])
    if arch.get(x["ticker"]): a["archetype"] = arch[x["ticker"]]
    if x["ticker"] in AI_THEME: a["theme"] = "AI"
cash = sum(float(c["amount"] or 0) for c in d["portfolio"]["cash"]["accounts"])
inputs = {"positions": list(agg.values()), "cash": cash, "params": APPROVED, "as_of": "2026-09-18",
          "note": "первый прогон по утверждённым параметрам; без пометок conviction; просадки — резервные по архетипам"}
req = json.dumps({"model": "conviction_overlay", "inputs": inputs, "seed": 0, "save": True}).encode("utf-8")
r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:18791/run", data=req, headers={"Content-Type": "application/json"}), timeout=60))
o = r["outputs"]; rid = r["run_id"]; json.dump(r, open("_conviction_run1.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("run:", rid, "| NAV", o["nav_base"], "| risk capital", o["risk_capital_basis"])
print("  breaches:", o["summary"]["hard_loss_budget_breaches"], "| soft:", o["summary"]["soft_concentration_gaps"], "| buys blocked:", o["summary"]["new_buys_blocked"])
for a in sorted(o["assets"], key=lambda x: -x["market_weight"]):
    if a.get("hard_cap") is None:
        print("  %-5s w=%5.1f%% inv=%5.1f%% (лимит %.0f%%) — потолок не считается" % (a["ticker"], a["market_weight"]*100, a["invested_share"]*100, a["invested_limit"]*100)); continue
    print("  %-5s w=%5.1f%% target %5.1f%% hard %5.1f%% → %-24s | inv %5.1f%% (лимит %2.0f%%) cap $%7.0f | loss@dd %4.1f%%" % (
        a["ticker"], a["market_weight"]*100, a["target_cap"]*100, a["hard_cap"]*100, a["concentration_gap"], a["invested_share"]*100, a["invested_limit"]*100, a["incremental_buy_capacity_usd"], a["expected_loss_at_dd_NAV"]*100))
print("  sectors:", {k: (v["market_gap"], round(v["market_weight"], 3), round(v["invested_share"], 3)) for k, v in o["sectors"].items()})

s = p.read_text(encoding="utf-8")
old = "  constraint_breaches: []\n  dry_powder_status: null\n"
assert s.count(old) == 1
mo = "".join("      - %s\n" % json.dumps({k: a[k] for k in ("ticker", "market_weight", "target_cap", "hard_cap", "concentration_gap", "invested_share", "invested_limit", "incremental_buy_capacity_usd", "decision_request") if k in a}, ensure_ascii=False) for a in sorted(o["assets"], key=lambda x: -x["market_weight"]))
s = s.replace(old, old + '  conviction_overlay:            # прогон conviction_overlay 1.0.0 по утверждённым параметрам (portfolio/_runs/%s.json)\n    run_id: "%s"\n    hard_loss_budget_breaches: %s\n    soft_concentration_gaps: %s\n    new_buys_blocked: %s\n    sectors: %s\n    assets:\n%s' % (
    rid, rid, json.dumps(o["summary"]["hard_loss_budget_breaches"]), json.dumps(o["summary"]["soft_concentration_gaps"]), json.dumps(o["summary"]["new_buys_blocked"]),
    json.dumps({k: {"market_gap": v["market_gap"], "market_weight": v["market_weight"], "invested_share": v["invested_share"]} for k, v in o["sectors"].items()}), mo), 1)
p.write_text(s, encoding="utf-8"); yaml.safe_load(s)

# 2. _candidates.yaml: тема AI
c = Path("portfolio/_candidates.yaml"); cs = c.read_text(encoding="utf-8")
for tk in AI_THEME:
    m = re.search(r"  - \{ticker: %s,[^\n]*" % re.escape(tk), cs)
    if not m: print("  тема: нет записи", tk); continue
    line = m.group(0)
    if "theme:" in line: continue
    if line.rstrip().endswith("}"):
        line2 = line.rstrip()[:-1] + ", theme: AI}"
    else:
        line2 = line.rstrip() + " theme: AI,"
    cs = cs.replace(line, line2, 1)
if "owner_policy_ai_theme" not in cs:
    cs = cs.replace("sector_id_provenance: provisional", 'owner_policy_ai_theme: "с 21.09.2026 позиции темы AI (theme: AI) не наращиваются — сигналы докупки помечаются строкой политики (AGENTS.md); список темы подтверждён владельцем 22.09"\nsector_id_provenance: provisional', 1)
c.write_text(cs, encoding="utf-8"); yaml.safe_load(cs)

# 3. AGENTS.md: правило политики
a = Path("AGENTS.md"); t = a.read_text(encoding="utf-8")
if "тема ИИ не наращивается" not in t:
    anchor = "**Формат уведомления (общие правила):**"
    assert t.count(anchor) == 1
    rule = ("**Политика владельца (с 21.09.2026): тема ИИ не наращивается.** Компании темы помечены `theme: AI` в "
            "`portfolio/_candidates.yaml` (NBIS, CRWV, NVDA, ASML, SPCX, MSFT, META, PLTR, NET, CRWD, ETN, 6506, 6324). В любом "
            "уведомлении с действием «купить / докупить / очередной транш / увеличить» по такой компании после строки с действием "
            "добавляй строку: `Политика: тема ИИ не наращивается с 21.09.2026 — сигнал справочный, решение за владельцем`. Сигнал "
            "не подавлять и не переводить в [СПРАВОЧНО]: он остаётся в fired/pending_owner, владелец закрывает его сам.\n\n")
    t = t.replace(anchor, rule + anchor, 1); a.write_text(t, encoding="utf-8")
print("params/candidates/AGENTS ok")
