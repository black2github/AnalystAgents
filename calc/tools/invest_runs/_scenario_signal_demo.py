"""Демонстрация сигнала слоя действий (03.10): синтетическое подтверждение дозором события EV-TW-FULL-BLOCKADE (критерий C01, первоисточник)
→ оценщик scenario_state (apply=false, state.json не трогается) → переходы и текст сигнала по контракту. Результат: notes/signal-demo-<дата>.md.
Запуск: python _scenario_signal_demo.py"""
import datetime
import json
from pathlib import Path

import yaml

import _portfolio_run7_lib as L

S = Path(__file__).parent; WS = L.WS; date = datetime.date.today().isoformat()
R = json.load(open(S / "_conditional_runs_partB.json", encoding="utf-8")); pics = {}
for k, b in R.items():
    if "|" in k and b.get("optimum"):
        o = b["optimum"]; pics[k] = {"conditional_run_ref": f"portfolio/_runs/_conditional_runs_partB.json#{k}", "conditional_optimum_ref": o["run_id"], "median_CAGR_5Y": o["current_under_phase"]["median_CAGR_5Y"], "ES5": o["current_under_phase"]["ES5"],
                                  "P_loss_gt_30pct": o["current_under_phase"]["P_loss_gt_30pct"], "optimum_median_CAGR_5Y": o["median_CAGR_5Y"], "optimum_ES5": o["ES5"]}
cat = yaml.safe_load((WS / "methodology/Scenario_Event_Catalog_v1.0.yaml").read_text(encoding="utf-8"))
ev = next(e for e in cat["events"] if e["event_id"] == "EV-TW-FULL-BLOCKADE"); crit = ev["observable_criteria"][0]
items = [{"event_id": "EV-TW-FULL-BLOCKADE", "criterion_id": crit["criterion_id"], "fact_id": (crit.get("fact_ids") or ["TW-F02"])[0], "observed_at": f"{date}T08:00:00Z", "observed_value": True,
          "verification_status": "verified", "verification_run_id": f"verify-SCEN-DEMO-{date}", "source_refs": ["СИНТЕТИЧЕСКИЙ ПРИМЕР — не факт; демонстрация формата сигнала"]}]
r = L.post({"model": "scenario_state", "inputs": {"event_items": items, "as_of": f"{date}T09:00:00Z", "apply": False, "conditional_pictures": pics}, "seed": 0, "save": True}); o = r["outputs"]
md = [f"# Демонстрация сигнала слоя действий — {date} (scenario_state {o['model_version']}, run {r['run_id']})\n",
      "ВНИМАНИЕ: событие синтетическое (демонстрация формата), state.json не изменялся (apply=false).\n",
      f"Переходы: {[(t['scenario_id'], t['phase_id'], t['from'], t['to']) for t in o['transitions']]}\n", f"Набор: {o['set_state']}\n"]
for s_ in o["signals"]:
    md += [f"## Сигнал ({s_['kind']}, {s_['scenario_id']} / {s_['phase_id']})\n", "```", s_["text"], "```", ""]
(WS / "notes" / f"signal-demo-{date}.md").write_text("\n".join(md), encoding="utf-8")
print("run", r["run_id"], "| переходов", len(o["transitions"]), "| сигналов", len(o["signals"]), "| schema_errors", o["schema_errors"], f"| notes/signal-demo-{date}.md")
