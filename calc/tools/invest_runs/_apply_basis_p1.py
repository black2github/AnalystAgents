"""22.09: средние цены P1 (счёт США) → cost_basis; новая позиция SPOT; прогон 4 portfolio_regime; _candidates.yaml."""
import json, urllib.request
from pathlib import Path
import yaml

Q = json.load(open("_quotes_2026-09-20.json", encoding="utf-8"))
AVG = {"RKLB": (40, 83.53), "GLD": (4, 412.5), "SPCX": (8, 155.41), "ETN": (5.0102, 406.84), "ASML": (3.0085, 1382.67), "SPOT": (4, 261.97),
       "NET": (10, 223.66), "MSFT": (7.0205, 271.58), "LLY": (13.0276, 772.42), "META": (15.0101, 342.83), "HOOD": (105, 49.55), "NBIS": (80, 73.45), "NVDA": (175.1578, 88.50)}
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
tail = "      target: {weight: null, target_version: null, effective_from: null}\n"
rows = []
for tk, (q, avg) in AVG.items():
    if tk == "SPOT":
        continue
    import re
    mm = list(re.finditer(r"    - ticker: %s\n      account: P1[^\n]*\n" % re.escape(tk), s)); assert len(mm) == 1, tk
    i = mm[0].start(); blk_end = s.index(tail, i) + len(tail); blk = s[i:blk_end]
    assert f"quantity: {q}" in blk, (tk, q)
    basis = q * avg
    note = "лоты не переданы; средняя цена брокера, вероятно с комиссиями"
    if tk == "SPCX":
        note = "лоты 4×155.05 + 4×155.02 (средняя 155.035); брокерская средняя 155.41 — с комиссиями"
    cb = ('      cost_basis: {total_usd: %.2f, avg_price: %s, source: "owner (средняя цена брокера, сообщение 22.09.2026)", legacy_at_system_start: true, note: "%s"}\n' % (basis, avg, note))
    if "      cost_basis:" not in blk:
        s = s[:blk_end] + cb + s[blk_end:]
    rows.append((tk, q, avg, Q[tk]["price"], q * Q[tk]["price"], basis))
q, avg = AVG["SPOT"]; qd = Q["SPOT"]
spot = "\n".join([
    "    - ticker: SPOT",
    "      account: P1",
    "      exchange: NYSE",
    '      company: "%s"' % qd["name"],
    "      asset_class: equity",
    "      sector_id: INTERNET_PLATFORMS   # provisional — стриминг/платформа, ориентир XLC как у META",
    "      quantity: %s" % q,
    "      quantity_unit: shares",
    "      currency: USD",
    "      acquisition_lots: []          # средняя цена брокера, лоты не переданы",
    '      cost_basis: {total_usd: %.2f, avg_price: %s, source: "owner (сообщение 22.09.2026)", legacy_at_system_start: true}' % (q * avg, avg),
    '      market: {price: %s, price_date: "2026-09-18", price_source: "Yahoo chart", price_12m_max: %s, fx_to_base: 1.0}' % (qd["price"], qd["max_12m"]),
    "      role: {current: null, allowed: [Core, Challenger, Watch, Legacy]}",
    "      target: {weight: null, target_version: null, effective_from: null}",
    '      note: "не было в составе портфеля, переданном 21.09; добавлена по списку средних цен 22.09; модели компании нет"',
    "", ""])
assert "    - ticker: SPOT\n" not in s
s = s.replace("  positions_rule:", spot + "  positions_rule:", 1)
p.write_text(s, encoding="utf-8"); d = yaml.safe_load(s)
rows.append(("SPOT", q, avg, qd["price"], q * qd["price"], q * avg))

print("P1 (счёт США), закрытие 18.09:")
tot_mv = tot_b = 0
for tk, q, avg, px, mv, b in sorted(rows, key=lambda r: -r[4]):
    tot_mv += mv; tot_b += b
    print("  %-5s %10s x $%-8s = $%10.0f -> $%10.0f  %+7.1f%%" % (tk, q, avg, b, mv, (mv / b - 1) * 100))
print("  ИТОГО P1: вложено $%.0f -> $%.0f  %+.1f%%" % (tot_b, tot_mv, (tot_mv / tot_b - 1) * 100))
nbis2 = 15091.51
print("  известный basis: P1 $%.0f + NBIS P2 $%.0f + кэш 897.91 = $%.0f; NBIS всего basis $%.0f" % (tot_b, nbis2, tot_b + nbis2 + 897.91, AVG["NBIS"][0] * AVG["NBIS"][1] + nbis2))

# --- прогон 4 с SPOT ---
merged = {}
for e in d["portfolio"]["positions"]:
    m = merged.setdefault(e["ticker"], {"ticker": e["ticker"], "sector_id": e["sector_id"], "quantity": 0.0, "price": e["market"]["price"], "price_12m_max": e["market"]["price_12m_max"]})
    m["quantity"] += float(e["quantity"])
bm = {"SEMICONDUCTORS": "^SOX", "SOFTWARE": "IGV", "SPACE": "UFO", "ELECTRIFICATION": "GRID", "ROBOTICS": "ROBO", "INTERNET_PLATFORMS": "XLC", "HEALTHCARE": "XLV", "FINTECH": "ARKF"}
sb = {k: {"index": Q[v]["price"], "index_12m_max": Q[v]["max_12m"], "quality": "external"} for k, v in bm.items()}
sb["AI_COMPUTE"] = {"index": 1222.6995, "index_12m_max": 1641.3701, "quality": "provisional_low_breadth", "benchmark_id": "AI_COMPUTE_BASKET_V1", "basket_run_id": "20260921T135229Z-synthetic_basket-95de5e"}
ov = [{"sector_id": "AI_COMPUTE", "min_weight": 0.20, "dd_threshold": -0.25, "regime_floor": "Stress", "provenance": "model_assumption"},
      {"sector_id": "AI_COMPUTE", "min_weight": 0.25, "dd_threshold": -0.40, "regime_floor": "Shock", "provenance": "model_assumption"}]
inputs = {"positions": list(merged.values()), "cash": [{"amount": 897.91}, {"amount": 0.0}], "nav_running_max": None,
          "sector_benchmarks": sb, "sector_overrides": ov, "as_of": "2026-09-18",
          "note": "прогон 4: добавлена позиция SPOT (P1), обнаруженная по списку средних цен 22.09; цены 18.09; running max сброшен — состав изменился"}
req = json.dumps({"model": "portfolio_regime", "inputs": inputs, "seed": 0, "save": True}).encode("utf-8")
r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:18791/run", data=req, headers={"Content-Type": "application/json"}), timeout=60))
o = r["outputs"]; rid = r["run_id"]; json.dump(r, open("_regime_run4.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
w = {x["ticker"]: x["weight_nav"] for x in o["positions"]}
print("run4:", rid, "NAV", o["nav_base"], "regime", o["regime"], "| SPOT weight", w["SPOT"], "| coverage", o["drawdowns"]["benchmark_coverage"])

s = p.read_text(encoding="utf-8")
weights = "".join("    %s: %s\n" % (t, w[t]) for t in sorted(w, key=lambda k: -w[k]))
m0 = s.index("\nmachine_outputs:") + 1
mo = "\n".join([
    "machine_outputs:                 # последний прогон portfolio_regime 1.1.0 (portfolio/_runs/%s.json); корзина AI_COMPUTE — 20260921T135229Z-synthetic_basket-95de5e" % rid,
    '  run_id: "%s"' % rid,
    '  model_version: "%s"' % r.get("version"),
    '  basket_run_id: "20260921T135229Z-synthetic_basket-95de5e"',
    '  as_of_prices: "2026-09-18"',
    "  current_nav: %s" % o["nav_base"],
    "  positions_value_base: %s" % o["positions_value_base"],
    "  cash_value_base: %s" % o["cash_value_base"],
    "  current_weights:",
    weights.rstrip("\n"),
    "  drawdowns:",
    "    portfolio: %s          # первый снимок; running max = текущий NAV (состав дополнен SPOT 22.09)" % o["drawdowns"]["portfolio"],
    "    weighted_sector: %s" % o["drawdowns"]["weighted_sector"],
    "    benchmark_coverage: %s" % o["drawdowns"]["benchmark_coverage"],
    "    sectors: %s" % json.dumps({k: v for k, v in o["drawdowns"]["sectors"].items() if v is not None}),
    "  benchmark_quality: %s" % json.dumps(o["benchmark_quality"]),
    "  breadth: %s" % json.dumps(o["breadth"]),
    "  regime_base: %s" % o["regime_base"],
    "  regime: %s" % o["regime"],
    "  regime_floors_applied: %s" % json.dumps(o["regime_floors_applied"], ensure_ascii=False),
    '  regime_reason: "база: широта %.0f%% бумаг с просадкой >=25%% (порог 25%%), взвешенная секторная %.1f%%; floor по AI_COMPUTE (вес %.0f%%, просадка корзины %.1f%%)"' % (
        o["breadth"]["fraction_positions_dd_le_stress"] * 100, o["drawdowns"]["weighted_sector"] * 100, o["sector_weights"]["AI_COMPUTE"] * 100, o["drawdowns"]["sectors"]["AI_COMPUTE"] * 100),
    "  constraint_breaches: []",
    "  dry_powder_status: null",
    '  timestamp: "2026-09-22T06:30:00Z"',
    "  caveats:",
    '    - "без секторного benchmark: только GLD (не акция)"',
    '    - "AI_COMPUTE_BASKET_V1 — provisional_low_breadth (2 компонента, совпадают с позициями)"',
    '    - "просадка портфеля = 0 по построению; SPOT добавлен 22.09 по списку средних цен"',
    ""])
s = s[:m0] + mo
s = s.replace('      source_snapshot: "20260921T135230Z-portfolio_regime-28b2b3"\n', '      source_snapshot: "%s"\n' % rid)
p.write_text(s, encoding="utf-8"); yaml.safe_load(s)
c = Path("portfolio/_candidates.yaml"); cs = c.read_text(encoding="utf-8")
if "ticker: SPOT" not in cs:
    anchor = "  # --- лист наблюдения и идей"
    line = '  - {ticker: SPOT, exchange: NYSE, yahoo: SPOT, currency: USD, sector_id: INTERNET_PLATFORMS, origin: actual_holding, stage: candidate, held: true, weight_nav: %s, note: "обнаружена 22.09 по списку средних цен; модели компании нет — заказать"}\n' % w["SPOT"]
    cs = cs.replace(anchor, line + anchor, 1); c.write_text(cs, encoding="utf-8"); yaml.safe_load(cs)
print("portfolio + candidates updated")
