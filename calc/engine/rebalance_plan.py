"""План перекладки к утверждённым целевым весам: детерминированные шаги с оборотом ≤ лимита на сигнал (ACT-2026-10-01/execution).

Назначение: после решения владельца о целевых весах (portfolio/_portfolio.yaml → portfolio.target_weights, status approved) агент не
считает сделки сам — сайдкар строит последовательность шагов, каждый шаг = один сигнал владельцу. Сделок модель не совершает, не
оптимизирует и не оценивает рынок; стадия B (лоты, два счёта, комиссии, налоги) НЕ моделируется — это сказано в каждом сигнале.

inputs:
  workspace: каталог workspace (по умолчанию /data/workspace-invest) — читается portfolio/_portfolio.yaml: positions (quantity × market.price ×
    fx_to_base, суммируется по тикеру через счета), cash.accounts, portfolio.target_weights (только status: approved), лимит оборота
    approved_limits_v1_1.strategy_execution.turnover_cap_nav_per_signal и tranches / no_buy_first_trading_days (для текста сигнала)
  prices: {ticker: {price, price_date, source}} — свежие котировки агента поверх market.price файла (дата цены попадает в сигнал)
  current_values: {ticker: value_base}, cash_base — явные значения вместо файла (тесты / проверки); target_weights: {ticker: w} и
    target_dry_powder — переопределение целевых весов (иначе из файла); target_version, decision_ref — для текста сигнала
  step_cap: лимит оборота шага (доля NAV; иначе из файла; оборот шага = max(продажи, покупки) в долях NAV — то же, что
    0.5·Σ|Δw| с кэшем как позицией в portfolio_optimizer); min_trade_weight: 0.005 — сделки меньше не выдаются (model_assumption),
    закрытие позиции выдаётся всегда; min_partial_weight: 0.02 — частичная сделка (позиция делится между шагами) не меньше 2 % NAV,
    иначе позиция целиком уходит в следующий шаг (model_assumption); в шаге сначала продажи, покупки — на кэш до и внутри шага
  reduce_order / buy_order: [tickers] — приоритет сокращений / докупок (DR-2026-10-03-01 §3 — ориентир); остальные — по убыванию |Δ|
  step_index: int|None — вернуть signal_texts только для одного шага (1-based)
outputs: nav_base, price_dates, current_weights, target_weights, deltas, total_turnover, n_steps, steps[] ({step, sells[], buys[],
  turnover, cash_before, cash_after, remaining_turnover}), checks (кэш не отрицателен, шаги ≤ лимита, после последнего шага веса =
  цель), signal_texts[] — готовые тексты сигналов (формат Telegram: без таблиц, «Решение за владельцем» последней строкой).
Детерминированно; seed не используется.
"""
from __future__ import annotations

from pathlib import Path

import yaml

VERSION = "1.0.0"
DEFAULT_WS = "/data/workspace-invest"


def _load_portfolio(ws: str) -> dict:
    p = Path(ws) / "portfolio" / "_portfolio.yaml"
    if not p.exists():
        raise ValueError(f"portfolio/_portfolio.yaml не найден в {ws}")
    return yaml.safe_load(open(p, encoding="utf-8"))


def _fmt_money(x: float) -> str:
    s = f"{abs(x):,.0f}".replace(",", " ")
    return ("−" if x < 0 else "") + "$" + s


def _fmt_pct(w: float) -> str:
    return f"{100 * w:.1f} %"


def run(inputs: dict, seed: int) -> dict:  # noqa: ARG001 — детерминированно
    ws = inputs.get("workspace") or DEFAULT_WS
    doc = None
    prices = {k: dict(v) for k, v in (inputs.get("prices") or {}).items()}
    price_dates: dict[str, str] = {}
    # --- текущие стоимости позиций и кэш -------------------------------------------------------------------------------------
    if inputs.get("current_values") is not None:
        values = {k: float(v) for k, v in inputs["current_values"].items()}
        cash = float(inputs.get("cash_base") or 0.0)
        unit_prices = {k: float(prices[k]["price"]) for k in prices if "price" in prices[k]}
    else:
        doc = _load_portfolio(ws)
        values, unit_prices = {}, {}
        for pos in (doc.get("portfolio") or {}).get("positions") or []:
            tk = pos["ticker"]; mk = pos.get("market") or {}
            px = float(prices.get(tk, {}).get("price") or mk.get("price") or 0.0); fx = float(mk.get("fx_to_base") or 1.0)
            if px <= 0:
                raise ValueError(f"позиция {tk}: нет цены (market.price или inputs.prices)")
            values[tk] = values.get(tk, 0.0) + float(pos.get("quantity") or 0.0) * px * fx
            unit_prices[tk] = px * fx
            price_dates[tk] = str(prices.get(tk, {}).get("price_date") or mk.get("price_date") or "?")
        cash = sum(float(a.get("amount") or 0.0) * float(a.get("fx_to_base") or 1.0) for a in ((doc.get("portfolio") or {}).get("cash") or {}).get("accounts") or [])
    for tk, pv in prices.items():
        if pv.get("price_date"):
            price_dates[tk] = str(pv["price_date"])
    nav = sum(values.values()) + cash
    if nav <= 0:
        raise ValueError("NAV ≤ 0")
    cur = {tk: v / nav for tk, v in values.items()}
    cur_dp = cash / nav
    # --- целевые веса ---------------------------------------------------------------------------------------------------------
    if inputs.get("target_weights") is not None:
        tgt = {k: float(v) for k, v in inputs["target_weights"].items()}
        tgt_dp = float(inputs.get("target_dry_powder") if inputs.get("target_dry_powder") is not None else max(0.0, 1.0 - sum(tgt.values())))
        tw_meta = {"version": inputs.get("target_version"), "decision_ref": inputs.get("decision_ref"), "effective_from": inputs.get("effective_from")}
    else:
        doc = doc or _load_portfolio(ws)
        tw = ((doc.get("portfolio") or {}).get("target_weights") or {})
        if tw.get("status") != "approved" or not tw.get("weights"):
            raise ValueError("целевые веса не утверждены (portfolio.target_weights.status != approved) — план перекладки не строится")
        tgt = {w["ticker"]: float(w["weight"]) for w in tw["weights"]}
        tgt_dp = float(tw.get("dry_powder_weight") if tw.get("dry_powder_weight") is not None else max(0.0, 1.0 - sum(tgt.values())))
        tw_meta = {"version": tw.get("version"), "decision_ref": tw.get("decision_ref"), "effective_from": tw.get("effective_from")}
    if abs(sum(tgt.values()) + tgt_dp - 1.0) > 1e-6:
        raise ValueError(f"целевые веса + кэш ≠ 1: {sum(tgt.values()) + tgt_dp:.6f}")
    exe = {}
    if doc is not None:
        exe = (((doc.get("portfolio") or {}).get("approved_limits_v1_1") or {}).get("strategy_execution") or {})
    cap = float(inputs.get("step_cap") if inputs.get("step_cap") is not None else exe.get("turnover_cap_nav_per_signal") or 0.15)
    min_trade = float(inputs.get("min_trade_weight") if inputs.get("min_trade_weight") is not None else 0.005)
    min_partial = float(inputs.get("min_partial_weight") if inputs.get("min_partial_weight") is not None else 0.02)
    tranches = int(exe.get("tranches") or 3)
    reduce_order = list(inputs.get("reduce_order") or []); buy_order = list(inputs.get("buy_order") or [])
    # --- дельты ---------------------------------------------------------------------------------------------------------------
    tickers = sorted(set(cur) | set(tgt))
    deltas = {tk: tgt.get(tk, 0.0) - cur.get(tk, 0.0) for tk in tickers}
    sells_all = {tk: -d for tk, d in deltas.items() if d < -1e-12}
    buys_all = {tk: d for tk, d in deltas.items() if d > 1e-12}
    for tk in list(sells_all):                                                   # пренебрежимые сделки не выдаются; закрытие позиции — всегда
        if sells_all[tk] < min_trade and tgt.get(tk, 0.0) > 0:
            del sells_all[tk]
    for tk in list(buys_all):
        if buys_all[tk] < min_trade:
            del buys_all[tk]
    total_turnover = max(sum(sells_all.values()), sum(buys_all.values()))

    def _partial(rem: float, room: float, floor: float) -> float:
        """Сколько взять из rem при запасе room: целиком, если влезает; иначе частично — и сама часть, и остаток не меньше floor."""
        if rem <= room + 1e-12:
            return rem
        amt = min(room, rem - floor)
        return amt if amt >= floor - 1e-12 else 0.0

    def _order(cands: dict, pref: list) -> list:
        rank = {tk: i for i, tk in enumerate(pref)}
        return sorted(cands, key=lambda tk: (rank.get(tk, len(pref)), -cands[tk], tk))

    # --- шаги -----------------------------------------------------------------------------------------------------------------
    rem_s, rem_b = dict(sells_all), dict(buys_all)
    cash_w = cur_dp
    steps = []
    guard = 0
    while (rem_s or rem_b) and guard < 100:
        guard += 1
        step_sells, step_buys = [], []
        budget = cap
        for tk in _order(rem_s, reduce_order):
            if budget <= 1e-12:
                break
            amt = _partial(rem_s[tk], budget, min_partial)
            if amt <= 0:
                continue
            step_sells.append((tk, amt)); budget -= amt; rem_s[tk] -= amt
            if rem_s[tk] <= 1e-12:
                del rem_s[tk]
        sold = sum(a for _, a in step_sells)
        cash_after_sells = cash_w + sold
        budget = cap
        for tk in _order(rem_b, buy_order):
            if budget <= 1e-12 or cash_after_sells <= 1e-12:
                break
            amt = _partial(rem_b[tk], min(budget, cash_after_sells), min_partial)
            if amt <= 0:
                continue
            step_buys.append((tk, amt)); budget -= amt; cash_after_sells -= amt; rem_b[tk] -= amt
            if rem_b[tk] <= 1e-12:
                del rem_b[tk]
        bought = sum(a for _, a in step_buys)
        if sold <= 1e-12 and bought <= 1e-12:
            break                                                                # нечего делать (нет кэша на покупки и нечего продавать)
        cash_before = cash_w; cash_w = cash_after_sells
        steps.append({"step": len(steps) + 1, "sells": [{"ticker": tk, "delta_w": -amt} for tk, amt in step_sells], "buys": [{"ticker": tk, "delta_w": amt} for tk, amt in step_buys],
                      "turnover": round(max(sold, bought), 6), "cash_before": round(cash_before, 6), "cash_after": round(cash_w, 6),
                      "remaining_turnover": round(max(sum(rem_s.values()), sum(rem_b.values())), 6)})
    # веса до/после каждого шага и денежные суммы
    w_run = {tk: cur.get(tk, 0.0) for tk in tickers}
    for st in steps:
        for t in st["sells"] + st["buys"]:
            tk = t["ticker"]; t["from_w"] = round(w_run[tk], 6); w_run[tk] = w_run[tk] + t["delta_w"]; t["to_w"] = round(max(0.0, w_run[tk]), 6)
            t["delta_value_base"] = round(t["delta_w"] * nav, 2)
            t["approx_shares"] = round(abs(t["delta_w"] * nav) / unit_prices[tk], 2) if unit_prices.get(tk) else None
            t["action"] = "sell" if t["delta_w"] < 0 else "buy"; t["delta_w"] = round(t["delta_w"], 6)
    final_w = {tk: round(w, 6) for tk, w in w_run.items()}
    checks = {"cash_never_negative": all(st["cash_after"] >= -1e-9 for st in steps), "steps_within_cap": all(st["turnover"] <= cap + 1e-9 for st in steps),
              "final_matches_target": all(abs(final_w.get(tk, 0.0) - tgt.get(tk, 0.0)) <= max(min_trade, 1e-6) for tk in tickers) and abs(cash_w - tgt_dp) <= max(min_trade, 1e-6),
              "unfinished": bool(rem_s or rem_b)}
    checks["ok"] = checks["cash_never_negative"] and checks["steps_within_cap"] and not checks["unfinished"]
    # --- тексты сигналов --------------------------------------------------------------------------------------------------------
    dates = sorted(set(price_dates.values())) if price_dates else []
    date_txt = (dates[0] if len(dates) == 1 else f"{dates[0]}…{dates[-1]}") if dates else "дата цен не указана"
    n = len(steps)
    texts = []
    for st in steps:
        if inputs.get("step_index") is not None and st["step"] != int(inputs["step_index"]):
            continue

        def line(items, verb):
            if not items:
                return f"{verb}: нет"
            parts = [f"{t['ticker']} {_fmt_pct(t['from_w'])} → {_fmt_pct(t['to_w'])} ({_fmt_money(t['delta_value_base'])}" + (f", ≈ {t['approx_shares']:g} акц.)" if t["approx_shares"] is not None else ")") for t in items]
            return f"{verb}: " + "; ".join(parts)

        head = f"AG: invest, ПЕРЕКЛАДКА: шаг {st['step']} из {n} (от текущих позиций) к целевым весам" + (f" v{tw_meta['version']}" if tw_meta.get("version") else "") + (f" (решение {tw_meta['decision_ref'].split('/')[-1].replace('.md', '')}" if tw_meta.get("decision_ref") else " (") + f", NAV {_fmt_money(nav)}, цены на {date_txt})"
        body = [head, line(st["sells"], "Продать"), line(st["buys"], "Купить"),
                f"Кэш после шага: {_fmt_pct(st['cash_after'])} · оборот шага {_fmt_pct(st['turnover'])} NAV (лимит {_fmt_pct(cap)}) · исполнение: {tranches} транша по торговым дням (ACT-2026-10-01)",
                f"После шага до цели: оборот {_fmt_pct(st['remaining_turnover'])} NAV" + (f", шагов ещё {n - st['step']}" if st["step"] < n else " — цель достигнута"),
                "Лоты, два счёта, комиссии и налоги не моделировались — учитывать вручную. Порядок — ориентир, не приказ.",
                "Решение за владельцем. Автоисполнение запрещено."]
        texts.append({"step": st["step"], "text": "\n".join(body)})
    return {"version": VERSION, "nav_base": round(nav, 2), "price_dates": price_dates, "price_date_text": date_txt, "current_weights": {tk: round(w, 6) for tk, w in cur.items()}, "current_dry_powder": round(cur_dp, 6),
            "target_weights": tgt, "target_dry_powder": tgt_dp, "target_meta": tw_meta, "deltas": {tk: round(d, 6) for tk, d in deltas.items()}, "step_cap": cap, "min_trade_weight": min_trade, "min_partial_weight": min_partial,
            "total_turnover": round(total_turnover, 6), "n_steps": n, "steps": steps, "final_weights": final_w, "final_dry_powder": round(cash_w, 6), "checks": checks, "signal_texts": texts,
            "notes": ["оборот шага = max(продажи, покупки) в долях NAV (= 0.5·Σ|Δw| с кэшем как позицией)", "стадия B исполнения (лоты, счета, издержки, налоги) не моделируется", "не торговый сигнал: решение за владельцем"]}
