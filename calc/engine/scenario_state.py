"""Оценщик состояния сценариев и сигнал агента v1.0 (Scenario Engine v1.1 §17–§20, Dozor_Scenario_Action_Contract v1.0, Agent_Scenario_Signal_Contract
v1.0, Scenario Action Layer v1.0 §3, §10–§12; ROADMAP п. 3, 03.10.2026). Детерминированно, без LLM:
1) критерии каталога событий против подтверждённых дозором наблюдений (event_items по контракту §2: event_id, criterion_id, fact_id,
   observed_at, observed_value, verification_status, verification_run_id, source_refs) — оператор/порог/окно берутся из КАТАЛОГА, не из
   наблюдения; satisfied только при verification_status = verified; pending_verification / not_disclosed / source_unavailable_technical не
   закрывают критерий; source_conflict блокирует подтверждение события;
2) события: any_of / all_of / k_of_n(required_count) → confirmed | partial | none | blocked;
3) фазы: entry_criteria все confirmed → confirmed (дата = as_of, квартал — календарный), часть → candidate, все exit_criteria → exited (из
   confirmed); статус сценария = самая продвинутая фаза; conditional_anchor — на подтверждённую фазу (t0 = её квартал, §21);
4) набор: defining-события исходов (outcome_mapping) подтверждены у ≥ 2 разных non-BASE членов → ambiguous_set_conflict; один → classification
   этого члена; OUTSIDE_SET-исход → outside_set_review; иначе BASE / normal;
5) сигналы владельцу (русский текст дословно по контракту): confirmed со стратегией (действия ДОСЛОВНО из файла стратегии, статус,
   проверка актуальности), confirmed без стратегии (только распознавание и условная картина), candidate (только свидетельства и
   недостающие критерии; решение владельца 01.10 — без подготовительных действий), ambiguous_set_conflict (первая строка — блокировка);
   пересмотр вероятностей: дата последнего review, новые defining-события после него, probability_review_due по сроку.
Ничего не исполняет: Trigger ≠ Decision. apply=true — записать state.json целиком (после проверки по Scenario_State_Schema v1.1).

inputs: {"workspace": путь (по умолчанию /data/workspace-invest) ИЛИ явные "catalog", "scenarios": [dict], "state": dict, "strategies": {sid: dict},
         "event_items": [...], "as_of": ISO date-time, "apply": false, "probability_review_days": 90,
         "conditional_pictures": {"SID|PHASE": {"conditional_run_ref", "conditional_optimum_ref", "median_CAGR_5Y", "ES5", "P_loss_gt_30pct",
                                                 "optimum_median_CAGR_5Y", "optimum_ES5"}} (из части B; по желанию)}
outputs: events{event_id: {status, satisfied_criteria, missing_criteria, blocked}}, transitions[], state_after, set_state, signals[{scenario_id,
  phase_id, kind, text}], applied, schema_errors, decision: none.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

import yaml

VERSION = "1.0.0"
SATISFIED = "verified"
BLOCKING = "source_conflict"


def _load(p: Path):
    txt = p.read_text(encoding="utf-8")
    return json.loads(txt) if p.suffix == ".json" else yaml.safe_load(txt)


def _dt_parse(s: str) -> _dt.datetime:
    s = str(s).replace("Z", "+00:00")
    d = _dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def _quarter(d: _dt.datetime, t0: _dt.datetime | None = None) -> int:
    """Квартал подтверждения как целое смещение от t0 калибровки (Scenario_State_Schema: integer); без t0 — абсолютный индекс год·4+кв."""
    q = (d.month - 1) // 3 + 1
    if t0 is None:
        return d.year * 4 + q - 1
    return (d.year - t0.year) * 4 + (q - ((t0.month - 1) // 3 + 1))


def _criterion_ok(crit: dict, items: list, as_of: _dt.datetime) -> tuple[bool, bool, list]:
    """(satisfied, blocked, used_items) — по наблюдениям данного criterion_id."""
    op = crit.get("operator"); thr = crit.get("threshold"); win = crit.get("window_days")
    sat = False; blocked = False; used = []
    for it in items:
        st = it.get("verification_status")
        if st == BLOCKING:
            blocked = True; used.append(it.get("verification_run_id")); continue
        if st != SATISFIED:
            continue
        if win is not None and it.get("observed_at"):
            if (as_of - _dt_parse(it["observed_at"])).days > int(win):
                continue
        v = it.get("observed_value")
        ok = False
        try:
            if op == "verified_true":
                ok = bool(v) is True or v in (True, 1, "true", "True")
            elif op in ("count_gte", "gte", "change_gte_pct", "sustained_for_days"):
                ok = v is not None and float(v) >= float(thr)
            elif op == "lte":
                ok = v is not None and float(v) <= float(thr)
            else:
                ok = False
        except (TypeError, ValueError):
            ok = False
        if ok:
            sat = True; used.append(it.get("verification_run_id"))
    return sat, blocked, used


def evaluate_events(catalog: dict, items: list, as_of: _dt.datetime) -> dict:
    by_crit: dict = {}
    for it in items:
        by_crit.setdefault(str(it.get("criterion_id")), []).append(it)
    out = {}
    for ev in (catalog.get("events") or []) + (catalog.get("external_events") or []):
        crits = ev.get("observable_criteria") or []
        sat_ids, miss_ids, blocked, runs = [], [], False, []
        for cr in crits:
            s, b, used = _criterion_ok(cr, by_crit.get(str(cr.get("criterion_id")), []), as_of)
            blocked = blocked or b; runs += [u for u in used if u]
            (sat_ids if s else miss_ids).append(cr.get("criterion_id"))
        logic = ev.get("observable_logic") or "any_of"; need = int(ev.get("required_count") or 1)
        n = len(sat_ids)
        if logic == "any_of":
            done = n >= 1
        elif logic == "all_of":
            done = n == len(crits) and n > 0
        else:
            done = n >= need
        status = "blocked" if (blocked and not done) else ("confirmed" if done and not blocked else ("partial" if n > 0 else "none"))
        if done and blocked:
            status = "blocked"
        out[ev["event_id"]] = {"status": status, "logic": logic, "required_count": need if logic == "k_of_n" else None, "satisfied_criteria": sat_ids, "missing_criteria": miss_ids,
                               "blocked": blocked, "assigned_member": ev.get("assigned_member"), "verification_run_ids": sorted(set(runs))}
    return out


def _phase_status(ph: dict, events: dict) -> tuple[str, list, list]:
    entry = [c.get("event_id") for c in ph.get("entry_criteria") or []]
    exit_ = [c.get("event_id") for c in ph.get("exit_criteria") or []]
    st = lambda e: (events.get(e) or {}).get("status", "none")  # noqa: E731
    entry_ok = [e for e in entry if st(e) == "confirmed"]; entry_partial = [e for e in entry if st(e) in ("partial", "confirmed")]
    exit_ok = [e for e in exit_ if st(e) == "confirmed"]
    if entry and len(entry_ok) == len(entry):
        if exit_ and len(exit_ok) == len(exit_):
            return "exited", entry_ok, exit_ok
        return "confirmed", entry_ok, exit_ok
    if entry_partial:
        return "candidate", entry_ok, exit_ok
    return "not_observed", entry_ok, exit_ok


ORDER = {"not_observed": 0, "candidate": 1, "confirmed": 2, "exited": 3}


def _signal_confirmed(sid: str, pid: str, ph_state: dict, events: dict, strategy: dict | None, pic: dict | None, scen_state: dict, review: dict) -> str:  # noqa: F821
    lines = ["AG: invest", f"СЦЕНАРИЙ: {sid}", f"ФАЗА: {pid} — CONFIRMED {ph_state.get('confirmed_at')}", "", "ПОДТВЕРЖДАЮЩИЕ ФАКТЫ:"]
    for eid in ph_state.get("confirmed_event_ids") or []:
        ev = events.get(eid) or {}
        for e in ph_state.get("evidence") or []:
            if e.get("event_id") == eid:
                lines += [f"- {eid} / {e.get('fact_id')}: критерии {', '.join(ev.get('satisfied_criteria') or [])}", f"  Источник: {e.get('source_ref')}", f"  Дата: {e.get('observed_at')}",
                          f"  Проверка: {e.get('verification_status')} / {e.get('verification_run_id')}"]
    lines += ["", "УСЛОВНАЯ КАРТИНА ПОРТФЕЛЯ:"]
    if pic:
        lines += [f"Run: {pic.get('conditional_run_ref')}", f"Median CAGR 5Y: {_pct(pic.get('median_CAGR_5Y'))}", f"P(loss>30%) 5Y: {_pct(pic.get('P_loss_gt_30pct'))}", f"ES5 5Y: {_pct(pic.get('ES5'))}",
                  f"Условный оптимум: {pic.get('conditional_optimum_ref')} (медиана {_pct(pic.get('optimum_median_CAGR_5Y'))}, ES5 {_pct(pic.get('optimum_ES5'))})"]
    else:
        lines += ["Run: условный прогон для этой фазы не найден — запросить расчёт у интегратора"]
    lines.append("")
    if strategy:
        phs = next((p for p in strategy.get("phase_strategies") or [] if p.get("phase_id") == pid), None)
        lines.append(f"СТРАТЕГИЯ: {scen_state.get('strategy_ref')}")
        if phs:
            stt = (phs.get("status") or {}).get("state"); sl = phs.get("staleness") or {}
            lines += [f"Статус: {stt}", f"Проверка актуальности: D_inf={sl.get('max_abs_target_diff')}; review_required={str(bool(sl.get('review_required'))).lower()}", "", "ДЕЙСТВИЯ ИЗ СТРАТЕГИИ (ДОСЛОВНО):"]
            if sl.get("review_required"):
                lines.append("Стратегия требует пересмотра (review_required=true) — активация невозможна, нужен пересмотр и повторное одобрение владельца.")
            acts = phs.get("actions") or []
            if not acts:
                lines.append("(торговых действий в стратегии фазы нет)")
            for i, a in enumerate(acts, 1):
                mag = a.get("magnitude") or {}; tm = a.get("timing") or {}; pre = a.get("preconditions") or []
                lines.append(f"{i}. {a.get('action_id')}: {a.get('action_type')} {(a.get('target') or {}).get('kind')}:{(a.get('target') or {}).get('id')} {mag.get('kind')}={mag.get('amount')}; "
                             f"timing=start_after_trading_days {tm.get('start_after_trading_days')}, tranches {tm.get('tranches')}, interval {tm.get('tranche_interval_trading_days')}, no_buy_first_trading_days {tm.get('no_buy_first_trading_days')}; "
                             f"preconditions={[p.get('condition_id') for p in pre] or 'нет'}")
        else:
            lines.append(f"Статус: стратегия не содержит фазу {pid}")
    else:
        lines.append("СТРАТЕГИЯ: отсутствует (strategy_ref = null). Торговые действия не сформированы.")
    lines += ["", "ПЕРЕСМОТР ВЕРОЯТНОСТЕЙ:", f"Последний review: {review.get('last_review')}", f"Новые defining events после review: {', '.join(review.get('new_defining_events') or []) or 'нет'}",
              f"probability_review_due: {str(bool(review.get('due'))).lower()}", "", "Решение за владельцем. Автоисполнение запрещено."]
    return "\n".join(lines)


def _pct(x):
    return "n/a" if x is None else f"{100 * float(x):+.1f}%"


def _signal_candidate(sid: str, pid: str, ph: dict, events: dict) -> str:
    lines = ["AG: invest", f"СЦЕНАРИЙ: {sid}", f"ФАЗА: {pid} — CANDIDATE", "", "СВИДЕТЕЛЬСТВА:"]
    for c in ph.get("entry_criteria") or []:
        ev = events.get(c.get("event_id")) or {}
        lines.append(f"- {c.get('event_id')}: {ev.get('status')}; выполнены критерии {ev.get('satisfied_criteria') or []}; недостающие {ev.get('missing_criteria') or []}" + ("; БЛОКИРОВАНО source_conflict" if ev.get("blocked") else ""))
    lines += ["", "Торговые действия не выдаются (стадия candidate — только уведомление, решение владельца 01.10.2026).", "Решение за владельцем. Автоисполнение запрещено."]
    return "\n".join(lines)


def run(inputs: dict, seed: int) -> dict:
    ws = Path(inputs.get("workspace") or os.environ.get("CALC_DATA", "/data/workspace-invest"))
    catalog = inputs.get("catalog") or _load(ws / "methodology" / "Scenario_Event_Catalog_v1.0.yaml")
    scenarios = inputs.get("scenarios")
    if scenarios is None:
        scenarios = [_load(p) for p in sorted((ws / "portfolio" / "_scenarios").glob("*_v1.*.yaml")) if "strateg" not in p.name]
        # оставить последнюю версию на scenario_id
        latest = {}
        for s in scenarios:
            sid = s.get("scenario_id")
            if sid and (sid not in latest or str(s.get("as_of", "")) >= str(latest[sid].get("as_of", ""))):
                latest[sid] = s
        scenarios = list(latest.values())
    state = inputs.get("state")
    if state is None:
        state = _load(ws / "portfolio" / "_scenarios" / "state.json")
    state = json.loads(json.dumps(state))
    strategies = inputs.get("strategies")
    if strategies is None:
        strategies = {}
        for sid, sc in (state.get("scenarios") or {}).items():
            ref = sc.get("strategy_ref")
            if ref and (ws / ref).exists():
                strategies[sid] = _load(ws / ref)
    items = inputs.get("event_items") or []
    as_of = _dt_parse(inputs.get("as_of") or _dt.datetime.now(_dt.timezone.utc).isoformat())
    as_of_s = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
    review_days = int(inputs.get("probability_review_days", 90))
    pics = inputs.get("conditional_pictures") or {}
    events = evaluate_events(catalog, items, as_of)
    # defining-события исходов → классификация набора
    mes = (catalog.get("mutual_exclusion_sets") or [{}])[0]
    confirmed_members = {}
    for oc in mes.get("outcome_mapping") or []:
        defs = oc.get("defining_event_ids") or []
        if defs and all((events.get(e) or {}).get("status") == "confirmed" for e in defs):
            confirmed_members.setdefault(oc.get("assigned_member"), []).append(oc.get("outcome_id"))
    non_base = [m for m in confirmed_members if m not in ("BASE", None)]
    set_state = state.setdefault("set_state", {})
    prev_set = dict(set_state)
    if "OUTSIDE_SET" in confirmed_members:
        set_state["status"] = "outside_set_review"; set_state["classification"] = "OUTSIDE_SET"
    elif len(non_base) >= 2:
        set_state["status"] = "ambiguous_set_conflict"; set_state["classification"] = "AMBIGUOUS"
    elif len(non_base) == 1:
        set_state["status"] = "normal"; set_state["classification"] = non_base[0]
    else:
        set_state["status"] = "normal"; set_state["classification"] = "BASE"
    transitions = []; signals = []
    last_review = set_state.get("last_probability_review_at")
    due = (as_of - _dt_parse(last_review)).days >= review_days if last_review else True
    new_defs = sorted({e for oc in mes.get("outcome_mapping") or [] for e in (oc.get("defining_event_ids") or []) if (events.get(e) or {}).get("status") == "confirmed"})
    review = {"last_review": last_review, "new_defining_events": new_defs, "due": bool(due or new_defs)}
    for sc in scenarios:
        sid = sc.get("scenario_id")
        if sid not in (state.get("scenarios") or {}):
            continue
        ss = state["scenarios"][sid]
        best_status, best_pid = "not_observed", None
        for ph in sc.get("phases") or []:
            pid = ph.get("phase_id"); ps = ss["phases"].setdefault(pid, {"status": "not_observed", "first_observed_at": None, "confirmed_at": None, "exited_at": None, "confirmed_quarter": None,
                                                                            "confirmed_event_ids": [], "confirmed_fact_ids": [], "evidence": [], "strategy_ref": ss.get("strategy_ref"), "strategy_status": ss.get("strategy_status"),
                                                                            "last_signal_at": None, "last_signal_id": None})
            new, entry_ok, exit_ok = _phase_status(ph, events)
            old = ps.get("status") or "not_observed"
            if old == "confirmed":                                               # вход уже подтверждён ранее: оценивается только выход
                exit_ids = [c.get("event_id") for c in ph.get("exit_criteria") or []]
                new = "exited" if exit_ids and all((events.get(e) or {}).get("status") == "confirmed" for e in exit_ids) else "confirmed"
            if ORDER[new] > ORDER[old] or (old == "confirmed" and new == "exited"):
                ps["status"] = new
                if new in ("candidate", "confirmed") and not ps.get("first_observed_at"):
                    ps["first_observed_at"] = as_of_s
                if new == "confirmed":
                    t0 = sc.get("t0") or (sc.get("meta") or {}).get("t0") or sc.get("as_of")
                    ps["confirmed_at"] = as_of_s; ps["confirmed_quarter"] = _quarter(as_of, _dt_parse(str(t0)) if t0 else None)
                    ps["confirmed_event_ids"] = sorted(set(entry_ok)); ps["confirmed_fact_ids"] = sorted({str(it.get("fact_id")) for it in items if it.get("event_id") in entry_ok and it.get("fact_id")})
                    if not ss.get("conditional_anchor"):
                        ss["conditional_anchor"] = {"phase_id": pid, "confirmed_at": as_of_s, "t0_definition": "confirmed_phase_quarter"}
                    else:
                        ss["conditional_anchor"] = {"phase_id": pid, "confirmed_at": as_of_s, "t0_definition": "confirmed_phase_quarter"}
                if new == "exited":
                    ps["exited_at"] = as_of_s
                # свидетельства по событиям фазы
                for it in items:
                    if it.get("event_id") in (entry_ok + exit_ok) and it.get("verification_status") == SATISFIED:
                        ev_rec = {"event_id": it.get("event_id"), "fact_id": it.get("fact_id"), "observed_at": it.get("observed_at"), "source_ref": (it.get("source_refs") or ["n/a"])[0] if isinstance(it.get("source_refs"), list) else str(it.get("source_ref") or "n/a"),
                                  "verification_status": it.get("verification_status"), "verification_run_id": it.get("verification_run_id")}
                        if ev_rec not in ps["evidence"]:
                            ps["evidence"].append(ev_rec)
                transitions.append({"scenario_id": sid, "phase_id": pid, "from": old, "to": new, "at": as_of_s, "entry_events_confirmed": entry_ok, "exit_events_confirmed": exit_ok})
                if new == "confirmed":
                    text = _signal_confirmed(sid, pid, ps, events, strategies.get(sid), pics.get(f"{sid}|{pid}"), ss, review)
                    if set_state["status"] == "ambiguous_set_conflict":
                        text = text.replace("AG: invest\n", "AG: invest\nСТАТУС НАБОРА: AMBIGUOUS_SET_CONFLICT — автоматическая активация всех стратегий заблокирована.\n", 1)
                    sig_id = f"SIG-{sid}-{pid}-{as_of.strftime('%Y%m%dT%H%M%SZ')}"
                    ps["last_signal_at"] = as_of_s; ps["last_signal_id"] = sig_id; ss["last_signal_at"] = as_of_s; ss["last_signal_id"] = sig_id
                    signals.append({"scenario_id": sid, "phase_id": pid, "kind": "confirmed", "signal_id": sig_id, "text": text})
                elif new == "candidate":
                    signals.append({"scenario_id": sid, "phase_id": pid, "kind": "candidate", "signal_id": None, "text": _signal_candidate(sid, pid, ph, events)})
                elif new == "exited":
                    signals.append({"scenario_id": sid, "phase_id": pid, "kind": "exited", "signal_id": None,
                                    "text": f"AG: invest\nСЦЕНАРИЙ: {sid}\nФАЗА: {pid} — EXITED {as_of_s}\nВыход из фазы не разворачивает позиции автоматически (Action Layer §7); exit_rule стратегии — пересмотр/перерасчёт по решению владельца.\nРешение за владельцем. Автоисполнение запрещено."})
        # статус сценария и текущая фаза: активная (confirmed) фаза важнее вышедшей; exited — только если нет confirmed/candidate
        statuses = [(pid_, (ss["phases"][pid_] or {}).get("status", "not_observed")) for pid_ in [ph_.get("phase_id") for ph_ in sc.get("phases") or []]]
        for want in ("confirmed", "candidate", "exited"):
            hit = [pid_ for pid_, st_ in statuses if st_ == want]
            if hit:
                best_status, best_pid = want, hit[-1]
                break
        ss["status"] = best_status; ss["current_phase_id"] = best_pid
        if set_state["status"] == "ambiguous_set_conflict":
            ss["strategy_review_required"] = True; ss["strategy_review_reason"] = "ambiguous_set_conflict"
    state["updated_at"] = as_of_s
    if prev_set.get("status") != set_state.get("status") or prev_set.get("classification") != set_state.get("classification"):
        transitions.append({"scenario_id": None, "phase_id": None, "from": f"set:{prev_set.get('classification')}/{prev_set.get('status')}", "to": f"set:{set_state.get('classification')}/{set_state.get('status')}", "at": as_of_s})
    schema_errors = []
    sch_p = ws / "methodology" / f"Scenario_State_Schema_v{state.get('schema_version', '1.1')}.yaml"
    if sch_p.exists():
        try:
            from jsonschema import Draft202012Validator
            schema_errors = [{"path": "/".join(str(x) for x in e.path), "message": e.message[:200]} for e in sorted(Draft202012Validator(_load(sch_p)).iter_errors(state), key=lambda e: list(e.path))]
        except ImportError:
            schema_errors = []
    applied = False
    if inputs.get("apply") and not schema_errors:
        (ws / "portfolio" / "_scenarios" / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); applied = True
    return {"model_version": VERSION, "as_of": as_of_s, "events": events, "set_state": set_state, "transitions": transitions, "signals": signals, "state_after": state,
            "schema_errors": schema_errors, "applied": applied, "probability_review": review, "decision": "none",
            "rule": "Trigger ≠ Decision: статусы фаз — по entry/exit_criteria и каталогу; сигналы — текст владельцу; сделок и активации стратегий нет"}
