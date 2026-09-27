from pathlib import Path
import yaml

# 1. подтверждение prior владельцем
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
old = "  owner_confirmation: pending   # список и веса воспроизведены другой LLM по прежней переписке; владелец подтверждает\n"
assert old in s
s = s.replace(old, '  owner_confirmation: {status: confirmed, date: "2026-09-20", note: "список и веса воспроизведены другой LLM по прежней переписке, владелец подтвердил"}\n')
p.write_text(s, encoding="utf-8")

# 2. пул кандидатов
Path("portfolio/_candidates.yaml").write_text('''# Пул кандидатов в портфель: кто на какой стадии конвейера
# Candidate → Company Model → Valuation → Conditional MC → MPC → Optimizer → Stability Test → Core/Challenger → target weights
# (methodology/Marginal_Portfolio_Contribution_Specification_v1.0.md, §1).
# Один дом у факта: веса prior — portfolio/_portfolio.yaml (initial_portfolio_hypothesis); тезисы и триггеры — portfolio/<папка>/;
# лист наблюдения и идей — portfolio/_ideas.yaml. Здесь только состав пула, происхождение и стадия.
# Решение владельца 20.09.2026: (1) сначала фактический портфель как есть — по тем же правилам; (2) затем пул кандидатов
# = prior Core-10 + корзина ИИ-инфраструктуры (онбординг 17.09) + ideas/watch; число бумаг в портфеле ограничено
# (лимит задаёт владелец), остальное интересное — постоянный мониторинг (stage watch).
version: "1.0"
as_of: "2026-09-20"
owner_limit_positions: null        # максимум бумаг в портфеле — решение владельца, пока не задано

stages: [candidate, company_model, valuation, conditional_mc, mpc, optimizer, stability_test, decided, watch, rejected]

pool:
  # --- prior Core-10 (portfolio/_portfolio.yaml → initial_portfolio_hypothesis; подтверждён владельцем 20.09) ---
  - {ticker: AVGO, exchange: NASDAQ, yahoo: AVGO,   currency: USD, sector_id: SEMICONDUCTORS,    origin: prior_core10, stage: candidate}
  - {ticker: NVDA, exchange: NASDAQ, yahoo: NVDA,   currency: USD, sector_id: SEMICONDUCTORS,    origin: prior_core10, stage: candidate}
  - {ticker: KLAC, exchange: NASDAQ, yahoo: KLAC,   currency: USD, sector_id: SEMICONDUCTORS,    origin: prior_core10, stage: candidate}
  - {ticker: ASML, exchange: NASDAQ, yahoo: ASML,   currency: USD, sector_id: SEMICONDUCTORS,    origin: prior_core10, stage: candidate}
  - {ticker: SPCX, exchange: NASDAQ, yahoo: SPCX,   currency: USD, sector_id: SPACE,             origin: prior_core10, stage: conditional_mc,
     folder: spacex, note: "единственный полигон: states/kpis v1.3, RV run …-ab1fb7, MC run …-861006; MPC — после MC v1.1"}
  - {ticker: SNPS, exchange: NASDAQ, yahoo: SNPS,   currency: USD, sector_id: SOFTWARE,          origin: prior_core10, stage: candidate,
     note: "парный эксперимент с CDNS после Flight 14; ось интеграции Ansys — слой состояния (LLM 20.09)"}
  - {ticker: RKLB, exchange: NASDAQ, yahoo: RKLB,   currency: USD, sector_id: SPACE,             origin: prior_core10, stage: candidate}
  - {ticker: CDNS, exchange: NASDAQ, yahoo: CDNS,   currency: USD, sector_id: SOFTWARE,          origin: prior_core10, stage: candidate,
     note: "парный эксперимент с SNPS"}
  - {ticker: MSFT, exchange: NASDAQ, yahoo: MSFT,   currency: USD, sector_id: SOFTWARE,          origin: prior_core10, stage: candidate}
  - {ticker: NBIS, exchange: NASDAQ, yahoo: NBIS,   currency: USD, sector_id: AI_INFRASTRUCTURE, origin: prior_core10, stage: candidate}
  # --- корзина «ИИ-инфраструктура» (онбординг 17.09, папки с тезисом/триггерами/дозором) ---
  - {ticker: ETN,  exchange: NYSE,   yahoo: ETN,    currency: USD, sector_id: AI_INFRASTRUCTURE, origin: aiinfra_basket, stage: candidate, folder: etn}
  - {ticker: SU,   exchange: EPA,    yahoo: SU.PA,  currency: EUR, sector_id: AI_INFRASTRUCTURE, origin: aiinfra_basket, stage: candidate, folder: su}
  - {ticker: NET,  exchange: NYSE,   yahoo: NET,    currency: USD, sector_id: SOFTWARE,          origin: aiinfra_basket, stage: candidate, folder: net}
  - {ticker: "6506", exchange: TSE,  yahoo: 6506.T, currency: JPY, sector_id: AI_INFRASTRUCTURE, origin: aiinfra_basket, stage: candidate, folder: "6506", name: "Yaskawa"}
  - {ticker: "6324", exchange: TSE,  yahoo: 6324.T, currency: JPY, sector_id: AI_INFRASTRUCTURE, origin: aiinfra_basket, stage: candidate, folder: "6324", name: "Harmonic Drive"}
  - {ticker: CRWD, exchange: NASDAQ, yahoo: CRWD,   currency: USD, sector_id: SOFTWARE,          origin: aiinfra_basket, stage: candidate, folder: crwd}
  # --- лист наблюдения и идей: portfolio/_ideas.yaml (watch: DDOG, OKTA, 6481, 6268, ABBN; ideas: HPS.A, POWERINDIA, GEV, ENR, PWR, VRT) ---
  - {ref: portfolio/_ideas.yaml, origin: ideas_registry, stage: watch,
     note: "в конвейер входят при выполнении return_condition или по решению владельца; до этого — мониторинг"}

sector_id_provenance: provisional   # привязка к секторам benchmark_registry сделана дозором, не владельцем; уточняется при выборе индексов
''', encoding="utf-8")

# 3. шаблон ввода фактических позиций
Path("inbox/positions-input.template.yaml").write_text('''# Шаблон для владельца: фактический портфель «как есть». Заполнить и вернуть; дозор перенесёт в portfolio/_portfolio.yaml (positions, cash)
# и запишет решения по триггерам (например, SPCX-C-02 «сделано частично» с датой и количеством).
# Цена и дата покупки — факт истории, не якорь оценки (source_policy.purchase_history). Точность до цента не нужна:
# достаточно количества, валюты и даты; текущие цены дозор возьмёт сам.
as_of: "2026-09-__"
currency_base: USD               # базовая валюта отчёта NAV; если другая — указать
broker_note: ""                  # брокер / рынок доступа (влияет на лоты и доступность бумаг), по желанию

positions:
  - ticker: SPCX
    exchange: NASDAQ
    quantity: null               # всего акций на счёте сейчас
    currency: USD
    lots:                        # покупки; можно одной строкой с общим количеством, если история не нужна
      - {date: "2026-09-__", quantity: null, price: null, note: "докупка по SPCX-C-02 (частично)"}
    trigger_decisions:           # какие сигналы дозора исполнены этой покупкой (id из triggers.yaml)
      - {id: SPCX-C-02, decision: "сделано частично", date: "2026-09-__"}
  - ticker: ""
    exchange: ""
    quantity: null
    currency: ""
    lots:
      - {date: "", quantity: null, price: null}

cash:
  - {account: "основной", currency: USD, amount: null}
  - {account: "", currency: "", amount: null}

dry_powder_note: ""              # какая часть кэша — резерв под просадки (если выделен)
non_portfolio_assets_note: ""    # внешние активы в NAV не входят; упомянуть только если влияют на лимиты риска
''', encoding="utf-8")

for f in ["portfolio/_portfolio.yaml", "portfolio/_candidates.yaml", "inbox/positions-input.template.yaml"]:
    yaml.safe_load(Path(f).read_text(encoding="utf-8"))
print("files ok, yaml valid")
