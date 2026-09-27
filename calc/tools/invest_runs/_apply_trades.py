from pathlib import Path
import yaml

# --- _portfolio.yaml: позиция SPCX по данным владельца 20.09 + ограничения владельца ---
p = Path("portfolio/_portfolio.yaml"); s = p.read_text(encoding="utf-8")
old_pos = '''  positions:
    - ticker: null
      exchange: null
      company: null
      asset_class: equity
      sector_id: null
      quantity: null
      quantity_unit: shares
      currency: null
      acquisition_lots:
        - date: null
          quantity: null
          price: null
          currency: null
          source: "owner/broker"
'''
new_pos = '''  positions:
    - ticker: SPCX
      exchange: NASDAQ
      company: "Space Exploration Technologies Corp."
      asset_class: equity
      sector_id: SPACE            # provisional — привязка дозора, см. _candidates.yaml
      quantity: 8                 # по данным владельца 20.09.2026: только сделки 17.09; если были более ранние лоты — дополнить
      quantity_unit: shares
      currency: USD
      acquisition_lots:
        - date: "2026-09-17"
          quantity: 4
          price: 155.05
          currency: USD
          source: "owner (сообщение 20.09.2026), сигнал SPCX-C-02"
        - date: "2026-09-17"
          quantity: 4
          price: 155.02
          currency: USD
          source: "owner (сообщение 20.09.2026), сигнал SPCX-C-02"
'''
assert s.count(old_pos) == 1
s = s.replace(old_pos, new_pos, 1)
# остальные поля позиции (market/calculated/role/target/refs) остаются null — заполняет дозор при прогоне portfolio_regime
old_c = '''  total_wealth_context:
    enabled: true
'''
new_c = '''  owner_constraints:            # вход владельца 20.09.2026; числовой лимит числа бумаг — решение отложено
    positions_count_limit: null
    positions_count_note: >
      Субъективно: частному инвестору сложно ментально следить за большим числом бумаг; число может вырасти,
      когда система докажет работоспособность. Объективно: ограниченный капитал не позволяет грамотно хеджировать
      (например, пут-опцион — лот 100 акций, а выделенная на SPCX сумма может не позволить купить 100 акций);
      рост числа бумаг усугубляет это. Учитывать в MPC §3.7 (implementation constraints) и в Portfolio Optimizer.
    options_hedging:
      min_lot_shares: 100
      feasible_note: "хедж опционами доступен только по позициям ≥ 100 акций; иначе — только через размер позиции/кэш"
  total_wealth_context:
    enabled: true
'''
assert s.count(old_c) == 1
s = s.replace(old_c, new_c, 1)
p.write_text(s, encoding="utf-8")

# --- _candidates.yaml: пометка лимита ---
c = Path("portfolio/_candidates.yaml"); t = c.read_text(encoding="utf-8")
old_l = "owner_limit_positions: null        # максимум бумаг в портфеле — решение владельца, пока не задано\n"
assert old_l in t
t = t.replace(old_l, "owner_limit_positions: null        # решение владельца отложено (20.09); ограничения см. _portfolio.yaml → constraints.owner_constraints\n")
c.write_text(t, encoding="utf-8")

for f in ["portfolio/_portfolio.yaml", "portfolio/_candidates.yaml"]:
    d = yaml.safe_load(Path(f).read_text(encoding="utf-8"))
d = yaml.safe_load(Path("portfolio/_portfolio.yaml").read_text(encoding="utf-8"))
pos = d["portfolio"]["positions"][0]
assert pos["quantity"] == sum(l["quantity"] for l in pos["acquisition_lots"]) == 8
print("portfolio/candidates ok")
