"""Тесты портфельного оптимизатора (стадия A): совместные пути трёх синтетических компаний, лексикографическая цель, жёсткие
ограничения без ослабления, полосы весов, разрывы к текущему портфелю, infeasible с минимальными ослаблениями."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from engine import portfolio_optimizer as po  # noqa: E402
from tests.test_company_mc import cal_mature, cal_capital, TRI  # noqa: E402
from tests.test_portfolio_paths import _joint, _run_store  # noqa: E402

LIMITS = {"sector_max": 0.60, "top3_aggregate_max": 0.95, "common_cause_effective_max": 0.60, "roles": {"Challenger_max_per_name": 0.08, "Challenger_aggregate_max": 0.25},
          "dry_powder": {"Normal": {"min": 0.05, "preferred_max": 0.10, "hard_max": 0.15}, "Stress": {"min": 0.05, "preferred_max": 0.15, "hard_max": 0.20}},
          "risk_5y": {"p_loss_gt_30_max": 0.20, "p_loss_gt_50_max": 0.10, "es5_min": -0.55}}


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("opt")
    strong = cal_mature(); strong["revenue_model"]["segments"]["Core"]["initial_growth"] = TRI(0.20, 0.30, 0.40)
    weak = cal_mature(); weak["revenue_model"]["segments"]["Core"]["initial_growth"] = TRI(-0.10, 0.02, 0.10); weak["valuation"]["Y5"]["multiple"] = TRI(10, 14, 18)
    a = _run_store(_joint(strong, "AAA"), tmp, paths=4000); b = _run_store(_joint(weak, "BBB"), tmp, paths=4000); c = _run_store(_joint(cal_capital(), "CCC"), tmp, paths=4000)
    return {"AAA": a["paths_file"], "BBB": b["paths_file"], "CCC": c["paths_file"]}


def _inputs(paths, **over):
    d = {"paths_files": paths, "weights_current": {"AAA": 0.10, "BBB": 0.40, "CCC": 0.30}, "fixed_weights": {"ZZZ": 0.05}, "dry_powder_current": 0.10,
         "dry_powder_return_annual": 0.04, "regime": "Normal", "limits": LIMITS, "per_name_caps": {"AAA": 0.40, "BBB": 0.40, "CCC": 0.30},
         "sectors": {"AAA": "S1", "BBB": "S1", "CCC": "S2", "ZZZ": "S3"}, "common_cause": {"CAUSE": {"AAA": 1.0, "CCC": 0.75}}}
    d.update(over); return d


def test_optimizer_prefers_strong_and_respects_hard_constraints(paths):
    out = po.run(_inputs(paths), 0)
    w = out["proposed_weights"]; dp = out["dry_powder_weight"]
    assert out["feasible"] and out["violations_at_optimum"] == [] and out["decision"] == "none"
    assert abs(sum(w.values()) + dp + 0.05 - 1.0) < 1e-6                                   # бюджет: оптимизируемые + dp + fixed = 1
    assert w["AAA"] >= w["BBB"]                                                            # сильная компания не ниже слабой
    assert w["AAA"] <= 0.40 + 1e-9 and w["CCC"] <= 0.30 + 1e-9 and 0.05 - 1e-9 <= dp <= 0.15 + 1e-9
    assert out["concentrations"]["sector"]["S1"] <= 0.60 + 1e-9 and out["concentrations"]["common_cause"]["CAUSE"] <= 0.60 + 1e-9
    assert out["portfolio_return_distribution"]["Y5"]["median_CAGR"] >= out["current_portfolio"]["return_distribution_Y5"]["median_CAGR"] - 0.005
    assert set(out["feasible_weight_bands"]) == {"AAA", "BBB", "CCC"} and all(b[0] <= w[t] + 1e-9 <= b[1] + 1e-9 for t, b in out["feasible_weight_bands"].items())
    assert "AAA" in out["marginal_curves"] and out["marginal_curves"]["AAA"][0]["weight"] == 0.0
    assert out["fixed_positions"]["total"] == 0.05 and out["scenario_concentration"] is None
    # детерминизм
    again = po.run(_inputs(paths), 0)
    assert again["proposed_weights"] == w and again["dry_powder_weight"] == dp


def test_constraint_gaps_and_infeasible_reporting(paths):
    out = po.run(_inputs(paths, weights_current={"AAA": 0.55, "BBB": 0.25, "CCC": 0.05}), 0)
    gaps = {g["constraint"] for g in out["constraint_gaps_vs_current"]}
    assert "per_name_cap:AAA" in gaps and any(g.startswith("sector_max:S1") for g in gaps)      # текущий портфель нарушает, оптимум — нет
    assert out["feasible"] and all(not g["constraint"].startswith("per_name_cap") for g in out["violations_at_optimum"])
    bad = po.run(_inputs(paths, limits={**LIMITS, "risk_5y": {"p_loss_gt_30_max": 0.0, "p_loss_gt_50_max": 0.0, "es5_min": -0.05}}), 0)
    assert not bad["feasible"] and bad["minimum_relaxations"] and any(k.startswith("risk_5y") for k in bad["minimum_relaxations"])   # без тихого ослабления


def test_lexicographic_tolerance_and_watch_role(paths):
    out = po.run(_inputs(paths, roles={"CCC": "Watch"}), 0)
    assert out["proposed_weights"]["CCC"] == 0.0 and out["per_name_caps"]["CCC"] == 0.0
    P = po._Problem(_inputs(paths))
    a = {"horizons": {"Y5": {"median_CAGR": 0.100, "expected_shortfall_5pct": -0.30}}, "turnover": 0.1}
    b = {"horizons": {"Y5": {"median_CAGR": 0.103, "expected_shortfall_5pct": -0.40}}, "turnover": 0.1}
    assert P.better(a, b) and not P.better(b, a)                                            # в пределах 0.5 п.п. решает ES5
    c = {"horizons": {"Y5": {"median_CAGR": 0.110, "expected_shortfall_5pct": -0.40}}, "turnover": 0.1}
    assert P.better(c, a)                                                                   # вне допуска решает медиана


def _shocked(src: str, dst: Path, factors: dict) -> str:
    """Сценарный файл путей: те же path_id/meta, r5 умножен на factor по тикеру (синтетический шок сценария)."""
    z = np.load(src, allow_pickle=False); d = {k: z[k] for k in z.files}
    d["r5"] = (d["r5"].astype(np.float64) * float(factors.get("f", 1.0))).astype(d["r5"].dtype)
    np.savez(dst, **d); return str(dst)


def test_hedge_instrument_and_scenario_constraints_v110(paths, tmp_path):
    # сценарные пути: S1 — сильный шок только по AAA (×0.15); S2 — лёгкий по всем (×0.9) ниже p_min → не применяется
    s1 = {"AAA": _shocked(paths["AAA"], tmp_path / "s1-AAA.npz", {"f": 0.15}), "BBB": _shocked(paths["BBB"], tmp_path / "s1-BBB.npz", {"f": 1.0}), "CCC": _shocked(paths["CCC"], tmp_path / "s1-CCC.npz", {"f": 1.0})}
    s2 = {t: _shocked(paths[t], tmp_path / f"s2-{t}.npz", {"f": 0.9}) for t in paths}
    hedge = {"HGD": {"max_weight": 0.10, "return_annual": 0.0}}
    base_inp = _inputs(paths, weights_current={"AAA": 0.10, "BBB": 0.40, "CCC": 0.30, "HGD": 0.02}, fixed_weights={"ZZZ": 0.03}, hedge_instruments=hedge,
                       sectors={"AAA": "S1", "BBB": "S1", "CCC": "S2", "ZZZ": "S3", "HGD": "GOLD"})
    free = po.run(base_inp, 0)
    assert free["feasible"] and "HGD" in free["companies"] and free["proposed_weights"]["HGD"] <= 0.10 + 1e-9
    assert free["hedge_instruments"]["HGD"]["current_weight"] == 0.02 and free["scenario_constraints"] is None
    assert abs(sum(free["proposed_weights"].values()) + free["dry_powder_weight"] + 0.03 - 1.0) < 1e-6
    # хедж с плоской доходностью 0 занимает место слабой BBB при заполненном dry powder (hard_max 15 %) — в пределах лимита владельца
    assert free["proposed_weights"]["HGD"] <= 0.10 + 1e-9 and free["per_name_caps"]["HGD"] == 0.10
    sc = {"p_min": 0.10, "es5_min": None, "p_loss_gt_30_max": None, "scenario_concentration_max": None,
          "scenarios": [{"id": "S1", "probability": 0.15, "paths_files": s1}, {"id": "S2", "probability": 0.05, "paths_files": s2}], "base_paths_files": paths}
    rep = po.run({**base_inp, "scenario_constraints": sc}, 0)                                   # только отчёт: пороги не заданы
    assert rep["proposed_weights"] == free["proposed_weights"] and rep["scenario_constraints"]["applied_scenarios"] == ["S1"]
    es5_free = rep["scenario_constraints"]["at_optimum"]["by_scenario"]["S1"]["expected_shortfall_5pct"]
    sc = {**sc, "es5_min": es5_free + 0.05, "p_loss_gt_30_max": 0.25}                          # порог чуть строже картины свободного оптимума → связывает
    con = po.run({**base_inp, "scenario_constraints": sc}, 0)
    blk = con["scenario_constraints"]
    assert blk["applied_scenarios"] == ["S1"] and blk["skipped_below_p_min"] == ["S2"]
    assert con["feasible"] and con["violations_at_optimum"] == []
    m1 = blk["at_optimum"]["by_scenario"]["S1"]
    assert m1["expected_shortfall_5pct"] >= sc["es5_min"] - 1e-9 and m1["P_loss_gt_30pct"] <= 0.25 + 1e-9
    assert blk["at_current"]["by_scenario"]["S1"]["expected_shortfall_5pct"] < m1["expected_shortfall_5pct"]        # текущие веса хуже под S1
    assert con["proposed_weights"]["AAA"] < free["proposed_weights"]["AAA"]                                          # ограничение связывает: AAA (шок ×0.35) сокращается
    assert any(v.startswith("scenario:S1") for v in con["binding_constraints"])
    scc = blk["at_optimum"]["scenario_concentration"]
    assert scc["status"] == "applicable" and set(blk["at_optimum"]["burdens_B"]) == {"S1", "S2"} and con["scenario_concentration"] == scc
    # лимит концентрации (вариант «а», |A| = 2): без лимита бремя S1 доминирует (> 0.60), с лимитом 0.60 оптимизатор уходит из AAA
    assert scc["value"] > 0.60
    conc = po.run({**base_inp, "scenario_constraints": {**sc, "scenario_concentration_max": 0.60}}, 0)
    assert conc["feasible"] and conc["scenario_concentration"]["value"] <= 0.60 + 1e-9 and conc["proposed_weights"]["AAA"] < con["proposed_weights"]["AAA"]
    # невыполнимый лимит концентрации 0.30: единственный выход — AAA = 0 (|A| = 1, лимит не применяется), но тогда кэш выше hard_max →
    # честный infeasible с названным минимальным ослаблением, без тихого ослабления
    conc0 = po.run({**base_inp, "scenario_constraints": {**sc, "scenario_concentration_max": 0.30}}, 0)
    assert not conc0["feasible"] and conc0["minimum_relaxations"]
    c0 = conc0["scenario_concentration"]
    assert "scenario_concentration_max" in conc0["minimum_relaxations"] or not c0["applicable"] or c0["value"] <= 0.30 + 1e-9
    # невыполнимый порог: (а) без base_paths_files гейт консервативный (все p_s ≥ p_min) → честный infeasible с минимальным ослаблением;
    # (б) с base_paths_files (contract v1.1, S_cond требует B_s > 0) оптимизатор уходит из AAA в ноль — S1 перестаёт быть adverse
    # для портфеля и гейт снимается (gated_at_optimum пуст); тихого ослабления порога нет
    bad = po.run({**base_inp, "scenario_constraints": {**sc, "es5_min": 0.50, "base_paths_files": None}}, 0)
    assert not bad["feasible"] and any(k.startswith("scenario:S1:es5_min") for k in bad["minimum_relaxations"])
    esc = po.run({**base_inp, "scenario_constraints": {**sc, "es5_min": 0.50}}, 0)
    assert esc["scenario_constraints"]["gated_at_optimum"] == [] and esc["proposed_weights"]["AAA"] == 0.0          # гейт S1 снят
    assert not any(k.startswith("scenario:") for k in esc["minimum_relaxations"])                                     # остаток — потолок кэша (геометрия фикстуры)
    assert esc["scenario_constraints"]["contract_version"] == "1.1"
    # поимённые пороги (вариант V3) переопределяют общие
    v3 = po.run({**base_inp, "scenario_constraints": {**sc, "thresholds": {"S1": {"es5_min": -0.90, "p_loss_gt_30_max": 0.9}}}}, 0)
    assert v3["scenario_constraints"]["config"]["thresholds"]["S1"]["es5_min"] == -0.90 and v3["feasible"]
    # хедж не может быть одновременно fixed
    with pytest.raises(ValueError):
        po.run({**base_inp, "fixed_weights": {"ZZZ": 0.03, "HGD": 0.02}}, 0)


def test_cardinality_and_min_position_weight_v120(paths):
    """1.2.0: лимит числа бумаг и минимальный вес позиции (DR-2026-10-02-01/В1): позиций ≤ max, каждая ≥ min или 0; ходы через запретную
    зону (закрыть/открыть позицию); честный infeasible при невыполнимом лимите; без лимита — прежний результат."""
    base = _inputs(paths)
    free = po.run(base, 0)
    assert free["cardinality"] is None
    # в фикстуре AAA и BBB в одном секторе (лимит 0.60), потолки 0.4/0.4/0.3, dry powder ≤ 0.15 → две бумаги не вмещают бюджет 0.95;
    # ослабляем сектор и кэш, чтобы допустимые 2-бумажные портфели существовали (AAA 0.4 + BBB 0.4 + dp 0.15 или AAA 0.4 + CCC 0.3 + dp 0.25)
    lim = {**LIMITS, "sector_max": 0.95, "dry_powder": {"Normal": {"min": 0.05, "preferred_max": 0.10, "hard_max": 0.30}},
           "cardinality": {"positions_min": 1, "positions_max": 2, "min_position_weight": 0.10, "excludes": []}}
    free = po.run({**base, "limits": {**LIMITS, "sector_max": 0.95, "dry_powder": lim["dry_powder"]}}, 0)
    out = po.run({**base, "limits": lim}, 0)
    w = out["proposed_weights"]; cd = out["cardinality"]
    assert out["feasible"] and out["violations_at_optimum"] == []
    assert cd["positions_count"] <= 2 and cd["positions_count"] >= 1 and cd["below_min"] == []
    assert all(x == 0.0 or x >= 0.10 - 1e-9 for x in w.values())
    assert sum(w.values()) + out["dry_powder_weight"] + 0.05 == pytest.approx(1.0, abs=1e-6)
    assert "cardinality:positions_max" in out["binding_constraints"] or cd["positions_count"] < 2
    # цена ограничения: медиана не выше свободного оптимума (с допуском на сетку)
    assert out["portfolio_return_distribution"]["Y5"]["median_CAGR"] <= free["portfolio_return_distribution"]["Y5"]["median_CAGR"] + 1e-6
    # минимальный вес выше потолка одной бумаги → позиция либо 0, либо невыполнима; позиций меньше min → честный infeasible
    bad = po.run({**base, "limits": {**LIMITS, "cardinality": {"positions_min": 3, "positions_max": 3, "min_position_weight": 0.35, "excludes": []}}}, 0)
    assert not bad["feasible"] and any(k.startswith(("cardinality", "min_position_weight", "per_name_cap", "dry_powder", "sector")) for k in bad["minimum_relaxations"])
    # прежние лимиты (сектор 0.60, dp ≤ 0.15) при positions_max 2 — допустимого портфеля нет: честный infeasible, лимит не ослабляется тихо
    nofit = po.run({**base, "limits": {**LIMITS, "cardinality": {"positions_max": 2, "min_position_weight": 0.10, "excludes": []}}}, 0)
    assert not nofit["feasible"] and nofit["minimum_relaxations"]
    # исключения не идут в счёт
    exc = po.run({**base, "limits": {**lim, "cardinality": {"positions_max": 1, "min_position_weight": 0.05, "excludes": ["AAA"]}}}, 0)
    assert exc["feasible"] and sum(1 for t, x in exc["proposed_weights"].items() if t != "AAA" and x > 0) <= 1
