"""Тесты оценщика состояния сценариев (scenario_state 1.0.0): критерии по каталогу (операторы, окно, verified), события any_of / all_of /
k_of_n, блокировка source_conflict, фазы candidate → confirmed → exited, якорь условного прогона, набор (normal / ambiguous_set_conflict),
сигналы по контракту (confirmed со стратегией, candidate, ambiguous), apply=false не пишет файл, схема состояния."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import scenario_state as ss  # noqa: E402

CAT = {"events": [
    {"event_id": "EV-A", "assigned_member": "S1", "observable_logic": "any_of", "observable_criteria": [{"criterion_id": "A-C1", "operator": "verified_true", "threshold": True, "window_days": 30},
                                                                                                           {"criterion_id": "A-C2", "operator": "count_gte", "threshold": 3, "window_days": None}]},
    {"event_id": "EV-B", "assigned_member": "S1", "observable_logic": "all_of", "observable_criteria": [{"criterion_id": "B-C1", "operator": "gte", "threshold": 10}, {"criterion_id": "B-C2", "operator": "lte", "threshold": 5}]},
    {"event_id": "EV-X", "assigned_member": "S2", "observable_logic": "k_of_n", "required_count": 2, "observable_criteria": [{"criterion_id": "X-C1", "operator": "verified_true", "threshold": True}, {"criterion_id": "X-C2", "operator": "verified_true", "threshold": True}, {"criterion_id": "X-C3", "operator": "verified_true", "threshold": True}]}],
    "mutual_exclusion_sets": [{"set_id": "SET", "base_member_id": "BASE", "members": ["BASE", "S1", "S2"], "outcome_mapping": [
        {"outcome_id": "O-S1", "assigned_member": "S1", "defining_event_ids": ["EV-A"]}, {"outcome_id": "O-S2", "assigned_member": "S2", "defining_event_ids": ["EV-X"]}]}]}
SCEN = [{"scenario_id": "S1", "as_of": "2026-09-27", "phases": [{"phase_id": "P1", "entry_criteria": [{"event_id": "EV-A"}], "exit_criteria": [{"event_id": "EV-B"}]}, {"phase_id": "P2", "entry_criteria": [{"event_id": "EV-B"}], "exit_criteria": []}]},
        {"scenario_id": "S2", "as_of": "2026-09-27", "phases": [{"phase_id": "Q1", "entry_criteria": [{"event_id": "EV-X"}], "exit_criteria": []}]}]


def _phase():
    return {"status": "not_observed", "first_observed_at": None, "confirmed_at": None, "exited_at": None, "confirmed_quarter": None, "confirmed_event_ids": [], "confirmed_fact_ids": [], "evidence": [],
            "strategy_ref": None, "strategy_status": None, "last_signal_at": None, "last_signal_id": None}


def _scenario(phases, ref):
    return {"status": "not_observed", "current_phase_id": None, "probability": 0.1, "probability_status": "owner_judgment", "last_probability_review_at": "2026-09-27T00:00:00Z", "conditional_anchor": None,
            "phases": {p: _phase() for p in phases}, "strategy_ref": ref, "strategy_status": "draft" if ref else None, "last_signal_at": None, "last_signal_id": None, "strategy_review_required": False, "strategy_review_reason": None}


def _state():
    return {"schema_version": "1.1", "artifact": "scenario_state", "updated_at": "2026-09-27T00:00:00Z", "scenario_set_id": "SET", "event_catalog_ref": "cat",
            "set_state": {"classification": "BASE", "status": "normal", "last_probability_review_at": "2026-09-27T00:00:00Z"},
            "scenarios": {"S1": _scenario(["P1", "P2"], "strategies/S1.yaml"), "S2": _scenario(["Q1"], None)}}


STRAT = {"S1": {"phase_strategies": [{"phase_id": "P1", "status": {"state": "draft"}, "staleness": {"review_required": False, "max_abs_target_diff": 0.0},
                                      "actions": [{"action_id": "S1-P1-01-REDUCE-AAA", "action_type": "reduce", "target": {"kind": "ticker", "id": "AAA"}, "magnitude": {"kind": "delta_weight_nav", "amount": -0.05},
                                                   "timing": {"start_after_trading_days": 0, "tranches": 3, "tranche_interval_trading_days": 1, "no_buy_first_trading_days": 5}, "preconditions": []}]}]}}


def _item(eid, cid, val=True, status="verified", at="2026-10-03T08:00:00Z", fact="F1"):
    return {"event_id": eid, "criterion_id": cid, "fact_id": fact, "observed_at": at, "observed_value": val, "verification_status": status, "verification_run_id": "verify-X-1", "source_refs": ["https://src"]}


def _run(items, as_of="2026-10-03T09:00:00Z", state=None, tmp_path=None):
    return ss.run({"workspace": str(tmp_path or Path(".")), "catalog": CAT, "scenarios": SCEN, "state": state or _state(), "strategies": STRAT, "event_items": items, "as_of": as_of, "apply": False}, 0)


def test_events_logic_window_and_blocking():
    out = _run([_item("EV-A", "A-C1")])
    assert out["events"]["EV-A"]["status"] == "confirmed" and out["events"]["EV-B"]["status"] == "none"
    assert _run([_item("EV-A", "A-C1", status="pending_verification")])["events"]["EV-A"]["status"] == "none"       # pending не закрывает критерий
    assert _run([_item("EV-A", "A-C1", at="2026-08-01T00:00:00Z")])["events"]["EV-A"]["status"] == "none"            # окно 30 дней
    assert _run([_item("EV-A", "A-C2", val=2)])["events"]["EV-A"]["status"] == "none"
    assert _run([_item("EV-A", "A-C2", val=3)])["events"]["EV-A"]["status"] == "confirmed"
    e = _run([_item("EV-B", "B-C1", val=12)])["events"]["EV-B"]
    assert e["status"] == "partial" and e["missing_criteria"] == ["B-C2"]
    assert _run([_item("EV-B", "B-C1", val=12), _item("EV-B", "B-C2", val=4)])["events"]["EV-B"]["status"] == "confirmed"
    assert _run([_item("EV-X", "X-C1"), _item("EV-X", "X-C2")])["events"]["EV-X"]["status"] == "confirmed"
    assert _run([_item("EV-X", "X-C1")])["events"]["EV-X"]["status"] == "partial"
    b = _run([_item("EV-A", "A-C1"), _item("EV-A", "A-C2", val=5, status="source_conflict")])["events"]["EV-A"]
    assert b["status"] == "blocked" and b["blocked"]


def test_phase_transitions_signal_and_anchor(tmp_path):
    out = _run([_item("EV-A", "A-C1")], tmp_path=tmp_path)
    tr = [(t["scenario_id"], t["phase_id"], t["to"]) for t in out["transitions"]]
    assert ("S1", "P1", "confirmed") in tr and out["set_state"]["classification"] == "S1" and out["set_state"]["status"] == "normal"
    st = out["state_after"]["scenarios"]["S1"]
    assert st["status"] == "confirmed" and st["current_phase_id"] == "P1" and st["conditional_anchor"]["phase_id"] == "P1" and st["phases"]["P1"]["confirmed_quarter"] == 1   # as_of калибровки 2026Q3 → подтверждение 2026Q4 = +1
    sig = [s for s in out["signals"] if s["kind"] == "confirmed"][0]
    assert sig["text"].startswith("AG: invest\nСЦЕНАРИЙ: S1\nФАЗА: P1 — CONFIRMED") and "S1-P1-01-REDUCE-AAA: reduce ticker:AAA delta_weight_nav=-0.05" in sig["text"]
    assert sig["text"].rstrip().endswith("Решение за владельцем. Автоисполнение запрещено.") and "probability_review_due: true" in sig["text"]
    assert out["applied"] is False and out["schema_errors"] == [] and out["decision"] == "none"
    c = _run([_item("EV-B", "B-C1", val=12)], tmp_path=tmp_path)                                                   # candidate: частичное событие
    assert c["state_after"]["scenarios"]["S1"]["phases"]["P2"]["status"] == "candidate"
    assert any(s["kind"] == "candidate" and "Торговые действия не выдаются" in s["text"] for s in c["signals"])
    e = _run([_item("EV-B", "B-C1", val=12), _item("EV-B", "B-C2", val=4)], state=out["state_after"], as_of="2026-11-15T09:00:00Z", tmp_path=tmp_path)   # P1 → exited, P2 → confirmed
    s1 = e["state_after"]["scenarios"]["S1"]
    assert s1["phases"]["P1"]["status"] == "exited" and s1["phases"]["P2"]["status"] == "confirmed" and s1["conditional_anchor"]["phase_id"] == "P2" and s1["current_phase_id"] == "P2"


def test_ambiguous_set_conflict(tmp_path):
    out = _run([_item("EV-A", "A-C1"), _item("EV-X", "X-C1"), _item("EV-X", "X-C2")], tmp_path=tmp_path)
    assert out["set_state"]["status"] == "ambiguous_set_conflict"
    sig = [s for s in out["signals"] if s["kind"] == "confirmed" and s["scenario_id"] == "S1"][0]
    assert "СТАТУС НАБОРА: AMBIGUOUS_SET_CONFLICT" in sig["text"].splitlines()[1]
    assert out["state_after"]["scenarios"]["S1"]["strategy_review_required"] is True
    sig2 = [s for s in out["signals"] if s["kind"] == "confirmed" and s["scenario_id"] == "S2"][0]                 # без стратегии — только распознавание
    assert "СТРАТЕГИЯ: отсутствует (strategy_ref = null)" in sig2["text"]
