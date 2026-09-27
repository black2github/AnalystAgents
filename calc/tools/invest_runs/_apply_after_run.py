"""После прогона: machine_outputs и nav_history в _portfolio.yaml; C-01 done в triggers.yaml; пул кандидатов; заказ моделей."""
import json
from pathlib import Path
import yaml

run = json.load(open("_regime_run1.json", encoding="utf-8")); o = run["outputs"]; rid = run["run_id"]
w = {x["ticker"]: x["weight_nav"] for x in o["positions"]}
dd = {x["ticker"]: x["drawdown_12m"] for x in o["positions"]}

# 1. _portfolio.yaml — machine_outputs + nav_history
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
m0 = s.index("\nmachine_outputs:") + 1
weights = "".join(f"    {t}: {w[t]}\n" for t in sorted(w, key=lambda k: -w[k]))
s = s[:m0] + f'''machine_outputs:                 # последний прогон portfolio_regime (portfolio/_runs/{rid}.json)
  run_id: "{rid}"
  model_version: "{run.get('version')}"
  as_of_prices: "2026-09-18"
  current_nav: {o['nav_base']}
  positions_value_base: {o['positions_value_base']}
  cash_value_base: {o['cash_value_base']}
  current_weights:
{weights}  drawdowns:
    portfolio: {o['drawdowns']['portfolio']}          # первый снимок: истории NAV нет, running max = текущий NAV
    weighted_sector: {o['drawdowns']['weighted_sector']}
    benchmark_coverage: {o['drawdowns']['benchmark_coverage']}   # доля NAV в секторах с утверждённым benchmark
    sectors: {json.dumps({k: v for k, v in o['drawdowns']['sectors'].items() if v is not None})}
  breadth: {json.dumps(o['breadth'])}
  regime: {o['regime']}
  regime_reason: "широта: 31% бумаг с просадкой ≥25% (порог 25%) и взвешенная секторная −19.3% (порог −20% не пройден); Shock нет: 19% бумаг ≥40% (порог 25%)"
  constraint_breaches: []
  dry_powder_status: null
  timestamp: "2026-09-21T00:02:00Z"
  caveats:
    - "кэш P2 не сообщён — NAV и веса занижены на его величину"
    - "счёт позиции SPCX не указан"
    - "benchmark утверждён для 35% NAV; NBIS/CRWV (AI_COMPUTE), META, LLY, HOOD, GLD — без секторного benchmark"
    - "просадка портфеля = 0 по построению (первый снимок); накапливается с этого прогона"
'''
n0 = s.index("  nav_history:\n"); n1 = s.index("  target_weights:\n")
s = s[:n0] + f'''  nav_history:
    - date: "2026-09-18"
      positions_value_base: {o['positions_value_base']}
      cash_value_base: {o['cash_value_base']}
      nav_base: {o['nav_base']}
      source_snapshot: "{rid}"
      note: "первый снимок; кэш P2 не учтён"

''' + s[n1:]
p.write_text(s, encoding="utf-8"); yaml.safe_load(s)

# 2. triggers.yaml SPCX: C-01 → done
t = Path("portfolio/spacex/triggers.yaml"); ts = t.read_text(encoding="utf-8")
i = ts.index("  - id: SPCX-C-01"); j = ts.index("  - id: SPCX-C-02")
blk = ts[i:j]; assert blk.count("    status: due\n") == 1
ts = ts[:i] + blk.replace("    status: due\n", "    status: done          # владелец 21.09.2026: закрыт покупкой 17.09 (8 акций), см. state.json\n").replace('notes: "На 2026-09-17 окно уже открыто. Владельцу проверить: сделан ли первый транш. Точную дату первого локапа уточнить"', 'notes: "Первый транш сделан 17.09.2026 (8 акций). Точную дату первого локапа уточнить"') + ts[j:]
t.write_text(ts, encoding="utf-8"); yaml.safe_load(ts)

# 3. _candidates.yaml — фактические позиции
c = Path("portfolio/_candidates.yaml"); cs = c.read_text(encoding="utf-8")
held = {"RKLB", "NVDA", "NET", "NBIS", "MSFT", "ETN", "ASML", "SPCX"}
for tk in held:
    line_start = cs.index(f"  - {{ticker: {tk},")
    line_end = cs.index("\n", line_start)
    line = cs[line_start:line_end]
    if "held:" not in line:
        cs = cs[:line_start] + line.rstrip("}") + f", held: true, weight_nav: {w[tk]}}}" + cs[line_end:]
new_rows = '''  # --- фактические позиции владельца вне prior/корзины (21.09.2026): в пул как held; модель компании требуется ---
  - {ticker: META, exchange: NASDAQ, yahoo: META, currency: USD, sector_id: INTERNET_PLATFORMS, origin: actual_holding, stage: candidate, held: true, weight_nav: %s}
  - {ticker: LLY,  exchange: NYSE,   yahoo: LLY,  currency: USD, sector_id: HEALTHCARE,         origin: actual_holding, stage: candidate, held: true, weight_nav: %s}
  - {ticker: HOOD, exchange: NASDAQ, yahoo: HOOD, currency: USD, sector_id: FINTECH,            origin: actual_holding, stage: candidate, held: true, weight_nav: %s}
  - {ticker: PLTR, exchange: NASDAQ, yahoo: PLTR, currency: USD, sector_id: SOFTWARE,           origin: actual_holding, stage: candidate, held: true, weight_nav: %s}
  - {ticker: ASTS, exchange: NASDAQ, yahoo: ASTS, currency: USD, sector_id: SPACE,              origin: actual_holding, stage: candidate, held: true, weight_nav: %s}
  - {ticker: CRWV, exchange: NASDAQ, yahoo: CRWV, currency: USD, sector_id: AI_COMPUTE,         origin: actual_holding, stage: candidate, held: true, weight_nav: %s}
  - {ticker: GLD,  exchange: NYSE,   yahoo: GLD,  currency: USD, sector_id: GOLD,               origin: actual_holding, stage: candidate, held: true, weight_nav: %s, asset_class: commodity_etf, note: "не компания — модель компании не нужна; роль резерва/хеджа решает владелец"}
  - {ticker: UFO,  exchange: NASDAQ, yahoo: UFO,  currency: USD, sector_id: SPACE,              origin: actual_holding, stage: candidate, held: true, weight_nav: %s, asset_class: sector_etf, note: "секторный ETF, он же benchmark SPACE"}
''' % tuple(w[k] for k in ["META", "LLY", "HOOD", "PLTR", "ASTS", "CRWV", "GLD", "UFO"])
anchor = "  # --- лист наблюдения и идей"
cs = cs.replace(anchor, new_rows + anchor, 1)
cs = cs.replace('as_of: "2026-09-20"', 'as_of: "2026-09-21"', 1)
c.write_text(cs, encoding="utf-8"); yaml.safe_load(cs)

# 4. заказ моделей компаний для другой LLM — партия 1: фактические позиции по убыванию веса
order = [k for k in sorted(w, key=lambda k: -w[k]) if k not in ("GLD", "UFO", "SPCX")]
rows = "\n".join(f"| {i+1} | {k} | {w[k]:.1%} | {dd[k]:+.1%} |" for i, k in enumerate(order))
Path("inbox/company-models-batch1.request.md").write_text(f'''# Для передачи другой LLM: заказ моделей компаний, партия 1 — фактический портфель владельца

Вставляется одним сообщением от «=== НАЧАЛО ===» до «=== КОНЕЦ ===».

=== НАЧАЛО ===

Владелец 21.09.2026 передал фактический портфель (два брокерских счёта, совокупный NAV ≈ $181 тыс. без учёта кэша
второго счёта) и подтвердил: этот портфель проходит тот же конвейер, что и кандидаты — Company Model → Valuation →
Conditional MC → MPC → Optimizer → Stability Test. Прежний Core-10 записан как prior (`_portfolio.yaml` v1.1,
`initial_portfolio_hypothesis`, подтверждён владельцем). Секторные benchmark'и приняты: SOFTWARE→IGV, SPACE→UFO,
AI_INFRASTRUCTURE разбит на ELECTRIFICATION→GRID и ROBOTICS→ROBO.

Первый прогон `portfolio_regime` (run {rid}, цены закрытия 18.09.2026): режим **Stress** — 31% бумаг с просадкой
≥25% за 12 мес. (порог 25%); взвешенная секторная просадка −19.3% при покрытии benchmark 35% NAV. Концентрация:
три бумаги = 69% NAV (NBIS 33%, NVDA 22%, HOOD 14%).

## Заказ: слой состояния и KPI для каждой бумаги (по образцу SPCX states/kpis v1.3)
Порядок — по весу в портфеле; первые три — приоритет, так как определяют риск портфеля.

| # | Тикер | Вес NAV | Просадка 12М |
|---|---|---|---|
{rows}

Для каждой компании нужны, в том же формате и с теми же правилами, что для SPCX:
1. `states.yaml` — оси состояния (3–5 осей, состояния с проверяемыми критериями), текущий снимок с источником.
2. `kpis.yaml` — 6–10 KPI с зонами G/Y/R, источник (10-Q/10-K/пресс-релиз IR), периодичность.
3. Триггеры переходов состояний (id `<ТИКЕР>-E-NN`, transition from→to, kpis, level E1/E2/E3).
4. Известные failure modes с `common_cause_id` (по таксономии MPC §3.5) и `driver_exposure_vector` по таксономии
   16 драйверов (MPC Schema v1.0) — это вход для MPC.
Калибровки reverse valuation и условного MC — отдельной партией после MC v1.1 (как договорились).

Ограничения: числа — только из первичных источников (SEC/IR); всё остальное `model_assumption`. Для NBIS и CRWV
(AI_COMPUTE) чистого секторного benchmark нет — если у вас есть обоснованный вариант, предложите отдельно.
GLD и UFO — не компании, модели не нужны. SPCX уже смоделирован.

Просьба: если партия велика, начните с NBIS, NVDA, HOOD и скажите, сколько компаний за раз для вас разумно.

=== КОНЕЦ ===
''', encoding="utf-8")
print("after-run ok; order:", order)
