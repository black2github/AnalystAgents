"""Прогон 3 portfolio_regime (1.1.0): корзина AI_COMPUTE_BASKET_V1 через synthetic_basket + concentration override; цены 18.09."""
import json, urllib.request
from pathlib import Path
import yaml

Q = json.load(open("_quotes_2026-09-20.json", encoding="utf-8"))
closes = json.load(open("_closes_ai_compute.json", encoding="utf-8"))
AS_OF = "2026-09-18"
def post(model, inputs, save=True):
    req = json.dumps({"model": model, "inputs": inputs, "seed": 0, "save": save}).encode("utf-8")
    return json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:18791/run", data=req, headers={"Content-Type": "application/json"}), timeout=60))

# 1. корзина: ряды до 18.09 включительно (снимок портфеля на закрытие пятницы)
cons = [{"ticker": t, "weight": 0.5, "series": [r for r in closes[t] if r[0] <= AS_OF]} for t in ("NBIS", "CRWV")]
b = post("synthetic_basket", {"constituents": cons, "initial_level": 1000, "rebalance": "quarterly", "lookback_days": 365, "max_carry_forward_days": 1, "tail": 5,
                              "benchmark_id": "AI_COMPUTE_BASKET_V1", "note": "первый расчёт корзины AI_COMPUTE (NBIS 50 / CRWV 50)"})
bo = b["outputs"]
print("basket:", b["run_id"], "| index", bo["index_last"], "max12m", bo["index_12m_max"], "dd", bo["drawdown_12m"], "| status", bo["benchmark_status"], "| rebalances", bo["rebalances"])

# 2. режим
d = yaml.safe_load(Path("portfolio/_portfolio.yaml").read_text(encoding="utf-8"))
merged = {}
for e in d["portfolio"]["positions"]:
    m = merged.setdefault(e["ticker"], {"ticker": e["ticker"], "sector_id": e["sector_id"], "quantity": 0.0, "price": e["market"]["price"], "price_12m_max": e["market"]["price_12m_max"]})
    m["quantity"] += float(e["quantity"])
bm = {"SEMICONDUCTORS": "^SOX", "SOFTWARE": "IGV", "SPACE": "UFO", "ELECTRIFICATION": "GRID", "ROBOTICS": "ROBO", "INTERNET_PLATFORMS": "XLC", "HEALTHCARE": "XLV", "FINTECH": "ARKF"}
sb = {k: {"index": Q[v]["price"], "index_12m_max": Q[v]["max_12m"], "quality": "external"} for k, v in bm.items()}
sb["AI_COMPUTE"] = {"index": bo["index_last"], "index_12m_max": bo["index_12m_max"], "quality": "provisional_low_breadth", "benchmark_id": "AI_COMPUTE_BASKET_V1", "basket_run_id": b["run_id"]}
ov = [{"sector_id": "AI_COMPUTE", "min_weight": 0.20, "dd_threshold": -0.25, "regime_floor": "Stress", "provenance": "model_assumption"},
      {"sector_id": "AI_COMPUTE", "min_weight": 0.25, "dd_threshold": -0.40, "regime_floor": "Shock", "provenance": "model_assumption"}]
inputs = {"positions": list(merged.values()), "cash": [{"amount": 897.91}, {"amount": 0.0}], "nav_running_max": d["machine_outputs"]["current_nav"],
          "sector_benchmarks": sb, "sector_overrides": ov, "as_of": AS_OF,
          "note": "прогон 3: добавлен AI_COMPUTE_BASKET_V1 (synthetic_basket) и concentration override (спецификация AI_COMPUTE §8)"}
r = post("portfolio_regime", inputs); o = r["outputs"]; rid = r["run_id"]
json.dump(r, open("_regime_run3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("regime:", rid, "| NAV", o["nav_base"], "| base", o["regime_base"], "→", o["regime"], "| floors", o["regime_floors_applied"])
print("weighted_sector", o["drawdowns"]["weighted_sector"], "coverage", o["drawdowns"]["benchmark_coverage"], "| AI_COMPUTE dd", o["drawdowns"]["sectors"]["AI_COMPUTE"], "weight", o["sector_weights"]["AI_COMPUTE"])

# 3. запись в _portfolio.yaml (machine_outputs — замена; nav_history — тот же as_of → обновить source_snapshot)
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
w = {x["ticker"]: x["weight_nav"] for x in o["positions"]}
weights = "".join(f"    {t}: {w[t]}\n" for t in sorted(w, key=lambda k: -w[k]))
m0 = s.index("\nmachine_outputs:") + 1
s = s[:m0] + f'''machine_outputs:                 # последний прогон portfolio_regime 1.1.0 (portfolio/_runs/{rid}.json); корзина AI_COMPUTE — {b['run_id']}
  run_id: "{rid}"
  model_version: "{r.get('version')}"
  basket_run_id: "{b['run_id']}"
  as_of_prices: "{AS_OF}"
  current_nav: {o['nav_base']}
  positions_value_base: {o['positions_value_base']}
  cash_value_base: {o['cash_value_base']}
  current_weights:
{weights}  drawdowns:
    portfolio: {o['drawdowns']['portfolio']}          # первый снимок: истории NAV нет, running max = текущий NAV
    weighted_sector: {o['drawdowns']['weighted_sector']}
    benchmark_coverage: {o['drawdowns']['benchmark_coverage']}   # доля NAV в секторах с benchmark (AI_COMPUTE теперь покрыт корзиной)
    sectors: {json.dumps({k: v for k, v in o['drawdowns']['sectors'].items() if v is not None})}
  benchmark_quality: {json.dumps(o['benchmark_quality'])}
  breadth: {json.dumps(o['breadth'])}
  regime_base: {o['regime_base']}
  regime: {o['regime']}
  regime_floors_applied: {json.dumps(o['regime_floors_applied'], ensure_ascii=False)}
  regime_reason: "база: широта {o['breadth']['fraction_positions_dd_le_stress']:.0%} бумаг с просадкой ≥25% (порог 25%), взвешенная секторная {o['drawdowns']['weighted_sector']:.1%}; floor по AI_COMPUTE (вес {o['sector_weights']['AI_COMPUTE']:.0%}, просадка корзины {o['drawdowns']['sectors']['AI_COMPUTE']:.1%})"
  constraint_breaches: []
  dry_powder_status: null
  timestamp: "2026-09-21T09:30:00Z"
  caveats:
    - "без секторного benchmark: только GLD (не акция)"
    - "AI_COMPUTE_BASKET_V1 — provisional_low_breadth (2 компонента, совпадают с позициями)"
    - "просадка портфеля = 0 по построению (первый снимок); накапливается с этого прогона"
'''
s = s.replace('      note: "первый снимок (пересчитан 21.09: кэш P2 = 0, 8 benchmark\'ов; первичный прогон …-b472bc)"\n',
              f'      note: "первый снимок (пересчитан 21.09 дважды: кэш P2 = 0 и 8 benchmark\'ов — …-fe89a2; корзина AI_COMPUTE + override — {rid}; первичный прогон …-b472bc)"\n')
s = s.replace('      source_snapshot: "20260920T212852Z-portfolio_regime-fe89a2"\n', f'      source_snapshot: "{rid}"\n')
p.write_text(s, encoding="utf-8"); yaml.safe_load(s); print("portfolio.yaml updated")
