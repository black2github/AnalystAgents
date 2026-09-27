"""Заполнение _portfolio.yaml фактическими позициями (два счёта), принятые benchmark'и, прогон portfolio_regime."""
import json, urllib.request
from pathlib import Path
import yaml

Q = json.load(open("_quotes_2026-09-20.json", encoding="utf-8"))
PRICE_DATE = "2026-09-18"   # закрытие пятницы; источник Yahoo chart
OWNER_DATE = "2026-09-21"

# --- факт владельца (сообщение 21.09.2026): тикер → количество по счетам ---
P1 = {"RKLB": 40, "NVDA": 175.1578, "NET": 10, "NBIS": 80, "MSFT": 7.0205, "META": 15.0101, "LLY": 13.0276,
      "HOOD": 105, "GLD": 4, "ETN": 5.0102, "ASML": 3.0085}
P2 = {"RKLB": 24, "UFO": 7, "ASTS": 32, "GLD": 6, "CRWV": 11, "PLTR": 18, "NBIS": 190, "HOOD": 112}
CASH = [{"account": "P1", "currency": "USD", "amount": 897.91}, {"account": "P2", "currency": "USD", "amount": None}]

META_ = {  # sector_id (для benchmark просадки, provisional) / asset_class / exchange
    "RKLB": ("SPACE", "equity", "NASDAQ"), "NVDA": ("SEMICONDUCTORS", "equity", "NASDAQ"), "NET": ("SOFTWARE", "equity", "NYSE"),
    "NBIS": ("AI_COMPUTE", "equity", "NASDAQ"), "MSFT": ("SOFTWARE", "equity", "NASDAQ"), "META": ("INTERNET_PLATFORMS", "equity", "NASDAQ"),
    "LLY": ("HEALTHCARE", "equity", "NYSE"), "HOOD": ("FINTECH", "equity", "NASDAQ"), "GLD": ("GOLD", "commodity_etf", "NYSE"),
    "ETN": ("ELECTRIFICATION", "equity", "NYSE"), "ASML": ("SEMICONDUCTORS", "equity", "NASDAQ"), "UFO": ("SPACE", "sector_etf", "NASDAQ"),
    "ASTS": ("SPACE", "equity", "NASDAQ"), "CRWV": ("AI_COMPUTE", "equity", "NASDAQ"), "PLTR": ("SOFTWARE", "equity", "NASDAQ"),
    "SPCX": ("SPACE", "equity", "NASDAQ"),
}

def pos_block():
    rows = []
    entries = [("P1", t, q) for t, q in P1.items()] + [("P2", t, q) for t, q in P2.items()]
    for acc, t, q in entries:
        sec, ac, ex = META_[t]; qd = Q[t]
        rows.append(f'''    - ticker: {t}
      account: {acc}
      exchange: {ex}
      company: "{qd['name']}"
      asset_class: {ac}
      sector_id: {sec}
      quantity: {q}
      quantity_unit: shares
      currency: USD
      acquisition_lots: []          # владелец: портфель формировался много лет, история покупок не нужна — важна доля (21.09.2026)
      market: {{price: {qd['price']}, price_date: "{PRICE_DATE}", price_source: "Yahoo chart", price_12m_max: {qd['max_12m']}, fx_to_base: 1.0}}
      role: {{current: null, allowed: [Core, Challenger, Watch, Legacy]}}
      target: {{weight: null, target_version: null, effective_from: null}}
''')
    # SPCX — 8 акций из сделок 17.09; счёт не указан
    qd = Q["SPCX"]
    rows.append(f'''    - ticker: SPCX
      account: null                 # владелец не указал, в каком из двух портфелей (уточнить)
      exchange: NASDAQ
      company: "Space Exploration Technologies Corp."
      asset_class: equity
      sector_id: SPACE
      quantity: 8
      quantity_unit: shares
      currency: USD
      acquisition_lots:
        - {{date: "2026-09-17", quantity: 4, price: 155.05, currency: USD, source: "owner (сообщение 20.09.2026), сигналы SPCX-C-01/C-02"}}
        - {{date: "2026-09-17", quantity: 4, price: 155.02, currency: USD, source: "owner (сообщение 20.09.2026), сигналы SPCX-C-01/C-02"}}
      market: {{price: {qd['price']}, price_date: "{PRICE_DATE}", price_source: "Yahoo chart", price_12m_max: {qd['max_12m']}, fx_to_base: 1.0}}
      role: {{current: null, allowed: [Core, Challenger, Watch, Legacy]}}
      target: {{weight: null, target_version: null, effective_from: null}}
      state_vector_ref: portfolio/spacex/states.yaml
      company_rules_ref: portfolio/spacex/triggers.yaml
''')
    return "  positions:\n" + "".join(rows)

p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
i0 = s.index("  positions:\n"); i1 = s.index("  positions_rule:")
s = s[:i0] + pos_block() + "\n" + s[i1:]
# accounts: два портфеля у разных брокеров (разные страны)
s = s.replace('  portfolio_id: "MAIN"\n', '  portfolio_id: "MAIN"\n  accounts:                     # владелец 21.09.2026: де-факто два портфеля через разных брокеров (разные страны); NAV считается совокупно\n    - {id: P1, note: "брокер 1"}\n    - {id: P2, note: "брокер 2"}\n', 1)
# cash
c0 = s.index("  cash:\n    accounts:\n"); c1 = s.index("    dry_powder:")
s = s[:c0] + '''  cash:
    accounts:
      - {id: P1, currency: USD, amount: 897.91, fx_to_base: 1.0, source: "owner 2026-09-21"}
      - {id: P2, currency: USD, amount: null, fx_to_base: 1.0, source: "owner — сумма не сообщена"}
''' + s[c1:]
# benchmark_registry.sectors — решение владельца 21.09: IGV / UFO / GRID / ROBO
b0 = s.index("  sectors:\n    SEMICONDUCTORS:"); b1 = s.index('  rule: "Не подменять')
s = s[:b0] + f'''  sectors:
    # Сектор здесь = с чем движется цена (benchmark просадки), а НЕ инвестиционная тема. Темы (ИИ-инфраструктура и т. п.)
    # живут в driver_exposure_vector MPC (methodology/Marginal_Portfolio_Contribution_Schema_v1.0.yaml → driver_taxonomy).
    SEMICONDUCTORS:
      benchmark_id: SOX
      yahoo: "^SOX"
      name: "PHLX Semiconductor Sector Index"
      source: "Nasdaq"
    SOFTWARE:
      benchmark_id: IGV
      yahoo: IGV
      name: "iShares Expanded Tech-Software Sector ETF"
      type: proxy_etf
      approved_by_owner: "{OWNER_DATE}"
    SPACE:
      benchmark_id: UFO
      yahoo: UFO
      name: "Procure Space ETF"
      type: proxy_etf
      approved_by_owner: "{OWNER_DATE}"
      note: "UFO одновременно есть в портфеле (P2) — для этой позиции секторная просадка совпадает с собственной"
    ELECTRIFICATION:
      benchmark_id: GRID
      yahoo: GRID
      name: "First Trust NASDAQ Clean Edge Smart Grid Infrastructure Index Fund"
      type: proxy_etf
      approved_by_owner: "{OWNER_DATE}"
      note: "бывший AI_INFRASTRUCTURE разбит на ELECTRIFICATION и ROBOTICS (решение владельца)"
    ROBOTICS:
      benchmark_id: ROBO
      yahoo: ROBO
      name: "Robo Global Robotics and Automation Index ETF"
      type: proxy_etf
      approved_by_owner: "{OWNER_DATE}"
    AI_COMPUTE:                     # NBIS, CRWV — «неооблака» ИИ-вычислений; чистого индекса нет
      benchmark_id: AI_COMPUTE_BENCHMARK_PENDING
      status: pending_owner_selection
      candidates_note: "нет чистого ETF; варианты — равновзвешенная корзина NBIS/CRWV (совпадает с позициями) или SOX как прокси"
    INTERNET_PLATFORMS:             # META
      benchmark_id: INTERNET_BENCHMARK_PENDING
      status: pending_owner_selection
      proposed: {{yahoo: XLC, name: "Communication Services Select Sector SPDR"}}
    HEALTHCARE:                     # LLY
      benchmark_id: HEALTHCARE_BENCHMARK_PENDING
      status: pending_owner_selection
      proposed: {{yahoo: XLV, name: "Health Care Select Sector SPDR"}}
    FINTECH:                        # HOOD
      benchmark_id: FINTECH_BENCHMARK_PENDING
      status: pending_owner_selection
      proposed: {{yahoo: ARKF, name: "ARK Fintech Innovation ETF"}}
    GOLD:                           # GLD — не акция; в секторный слой просадок не входит, собственная просадка считается
      benchmark_id: none
      excluded_from_sector_layer: true
''' + s[b1:]
p.write_text(s, encoding="utf-8")
d = yaml.safe_load(s)
positions = d["portfolio"]["positions"]
assert len(positions) == len(P1) + len(P2) + 1

# --- вход движка: позиции слиты по тикеру (широта просадок считается по бумагам, не по счетам) ---
merged = {}
for e in positions:
    m = merged.setdefault(e["ticker"], {"ticker": e["ticker"], "sector_id": e["sector_id"], "quantity": 0.0,
                                         "price": e["market"]["price"], "price_12m_max": e["market"]["price_12m_max"]})
    m["quantity"] += float(e["quantity"])
inputs = {
    "positions": list(merged.values()),
    "cash": [{"amount": 897.91}],
    "nav_running_max": None,   # истории NAV нет — первый снимок; просадка портфеля = 0 по построению
    "sector_benchmarks": {
        "SEMICONDUCTORS": {"index": Q["^SOX"]["price"], "index_12m_max": Q["^SOX"]["max_12m"]},
        "SOFTWARE": {"index": Q["IGV"]["price"], "index_12m_max": Q["IGV"]["max_12m"]},
        "SPACE": {"index": Q["UFO"]["price"], "index_12m_max": Q["UFO"]["max_12m"]},
        "ELECTRIFICATION": {"index": Q["GRID"]["price"], "index_12m_max": Q["GRID"]["max_12m"]},
        "ROBOTICS": {"index": Q["ROBO"]["price"], "index_12m_max": Q["ROBO"]["max_12m"]},
    },
    "as_of": PRICE_DATE, "note": "первый снимок фактического портфеля владельца (P1+P2), цены закрытия 18.09.2026, кэш P2 неизвестен",
}
req = json.dumps({"model": "portfolio_regime", "inputs": inputs, "seed": 0, "save": True}).encode("utf-8")
r = urllib.request.Request("http://127.0.0.1:18791/run", data=req, headers={"Content-Type": "application/json"})
out = json.load(urllib.request.urlopen(r, timeout=60))
json.dump(out, open("_regime_run1.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
o = out.get("outputs", out)
print("run_id:", out.get("run_id"))
print("NAV:", round(o["nav_base"], 2), "regime:", o["regime"])
print("dd:", json.dumps(o["drawdowns"], ensure_ascii=False))
print("breadth:", json.dumps(o["breadth"], ensure_ascii=False))
rows = sorted(o["positions"], key=lambda x: -x["weight_nav"])
for x in rows:
    print(f"{x['ticker']:5} w={x['weight_nav']:.1%} dd={x['drawdown_12m']:+.1%} {x.get('severity')}")
print("breaches:", o["constraint_breaches"])
