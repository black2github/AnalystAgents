"""Тесты rebalance_plan 1.0.0: шаги ≤ лимита, кэш не отрицателен, итог = цель, продажи раньше покупок, приоритеты, правило частичных
сделок (≥ min_partial и остаток ≥ min_partial), пренебрежимые сделки, чтение _portfolio.yaml (status approved обязателен), тексты сигналов."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import rebalance_plan as rp  # noqa: E402

CUR = {"AAA": 40_000.0, "BBB": 30_000.0, "CCC": 20_000.0, "DDD": 9_000.0}      # NAV 100 000 с кэшем 1 000
TGT = {"AAA": 0.25, "BBB": 0.10, "EEE": 0.30, "DDD": 0.09}                      # кэш 0.26; продажи 0.55, покупки 0.30


def _run(**kw):
    inp = {"current_values": CUR, "cash_base": 1_000.0, "target_weights": TGT, "step_cap": 0.15, "prices": {"EEE": {"price": 50.0, "price_date": "2026-10-03"}}}
    inp.update(kw)
    return rp.run(inp, 0)


def test_steps_cap_cash_and_final():
    o = _run()
    assert o["nav_base"] == 100_000.0 and o["total_turnover"] == pytest.approx(0.55) and o["checks"]["ok"]
    assert all(st["turnover"] <= 0.15 + 1e-9 for st in o["steps"]) and all(st["cash_after"] >= 0 for st in o["steps"])
    assert o["final_weights"]["AAA"] == pytest.approx(0.25, abs=1e-6) and o["final_weights"]["CCC"] == pytest.approx(0.0, abs=1e-9) and o["final_dry_powder"] == pytest.approx(0.26, abs=1e-6)
    assert o["n_steps"] == 4                                                    # 0.55 продаж при лимите 0.15 → 4 шага
    first = o["steps"][0]
    assert first["sells"] and first["sells"][0]["action"] == "sell" and first["sells"][0]["from_w"] > first["sells"][0]["to_w"]
    assert sum(-t["delta_w"] for st in o["steps"] for t in st["sells"]) == pytest.approx(0.55, abs=1e-6)
    assert sum(t["delta_w"] for st in o["steps"] for t in st["buys"]) == pytest.approx(0.30, abs=1e-6)
    eee = [t for st in o["steps"] for t in st["buys"] if t["ticker"] == "EEE"]
    assert eee and eee[0]["approx_shares"] == pytest.approx(abs(eee[0]["delta_value_base"]) / 50.0, rel=1e-6)


def test_reduce_order_and_partial_rule():
    o = _run(reduce_order=["DDD", "CCC"], buy_order=["EEE"])
    s1 = o["steps"][0]["sells"]
    assert s1[0]["ticker"] == "CCC"                                             # DDD: Δ −0.0 (0.09 → 0.09) — не сделка; CCC первым по приоритету
    for st in o["steps"]:                                                       # частичная сделка и её остаток — не меньше 2 % NAV
        for t in st["sells"] + st["buys"]:
            assert abs(t["delta_w"]) >= 0.02 - 1e-9 or t["to_w"] == 0.0 or abs(t["delta_w"]) == pytest.approx(abs(TGT.get(t["ticker"], 0.0) - CUR.get(t["ticker"], 0.0) / 100_000.0), abs=1e-6)


def test_negligible_trades_and_zero_delta():
    o = _run(target_weights={"AAA": 0.399, "BBB": 0.30, "CCC": 0.20, "DDD": 0.09}, target_dry_powder=0.011)
    assert o["n_steps"] == 0 and o["checks"]["ok"] and o["signal_texts"] == []   # Δ AAA −0.001 < min_trade → нечего делать
    o2 = _run(target_weights={"AAA": 0.40, "BBB": 0.30, "CCC": 0.0, "DDD": 0.09}, target_dry_powder=0.21)
    assert o2["n_steps"] == 2 and [t["ticker"] for t in o2["steps"][0]["sells"]] == ["CCC"]   # закрытие 20 % при лимите 15 % → 2 шага (15 + 5)


def test_signal_text_format():
    o = _run(target_version="1.0", decision_ref="decisions/DR-X.md", step_index=1)
    assert len(o["signal_texts"]) == 1
    t = o["signal_texts"][0]["text"]
    assert t.startswith("AG: invest, ПЕРЕКЛАДКА: шаг 1 из 4 (от текущих позиций) к целевым весам v1.0 (решение DR-X, NAV $100 000, цены на 2026-10-03)")
    assert "Продать:" in t and "Купить:" in t and "лимит 15.0 %" in t and t.rstrip().endswith("Решение за владельцем. Автоисполнение запрещено.")


def test_reads_portfolio_yaml_and_requires_approved(tmp_path):
    ws = tmp_path; (ws / "portfolio").mkdir()
    doc = {"portfolio": {"positions": [{"ticker": "AAA", "quantity": 10, "market": {"price": 100.0, "price_date": "2026-09-18", "fx_to_base": 1.0}},
                                       {"ticker": "AAA", "quantity": 5, "market": {"price": 100.0, "price_date": "2026-09-18", "fx_to_base": 1.0}},
                                       {"ticker": "BBB", "quantity": 10, "market": {"price": 50.0, "price_date": "2026-09-18", "fx_to_base": 1.0}}],
                         "cash": {"accounts": [{"amount": 500.0, "fx_to_base": 1.0}]},
                         "target_weights": {"status": "draft", "weights": []},
                         "approved_limits_v1_1": {"strategy_execution": {"turnover_cap_nav_per_signal": 0.10, "tranches": 3}}}}
    yaml.safe_dump(doc, open(ws / "portfolio" / "_portfolio.yaml", "w", encoding="utf-8"), allow_unicode=True)
    with pytest.raises(ValueError, match="не утверждены"):
        rp.run({"workspace": str(ws)}, 0)
    doc["portfolio"]["target_weights"] = {"status": "approved", "version": "1.0", "weights": [{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.3}], "dry_powder_weight": 0.2, "decision_ref": "decisions/DR-Y.md"}
    yaml.safe_dump(doc, open(ws / "portfolio" / "_portfolio.yaml", "w", encoding="utf-8"), allow_unicode=True)
    o = rp.run({"workspace": str(ws), "prices": {"AAA": {"price": 120.0, "price_date": "2026-10-03"}}}, 0)
    assert o["nav_base"] == pytest.approx(15 * 120.0 + 500.0 + 500.0) and o["current_weights"]["AAA"] == pytest.approx(1800.0 / 2800.0)   # две строки AAA суммируются; цена агента поверх файла
    assert o["step_cap"] == 0.10 and o["price_date_text"] == "2026-09-18…2026-10-03" and o["checks"]["ok"]
    assert "решение DR-Y" in o["signal_texts"][0]["text"]
