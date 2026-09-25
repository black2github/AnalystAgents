"""Агрегация портфеля по совместным путям v1.0 (Portfolio_Optimizer_Specification_v1.0 §7): срез 4 company_mc.

PortfolioValue_h = Σ_i w_i · RelativeValue_i,h + w_dp · (1 + r_dp)^h — по одному и тому же path_id у всех компаний.
Файлы путей пишет company_mc (inputs.paths_out) в формате .npz: r3, r5, r8, maxdd5 (float32, относительная стоимость
к E0 и просадка), b3/b5/b8 (int8, basis), path_id (int64) и meta (JSON: ticker, model_version, global_seed, chunk, paths,
joint). Совместимость путей проверяется по meta: одинаковые global_seed, chunk, paths и joint=true у всех.

inputs: {"paths_files": {ticker: путь .npz}, "weights": {ticker: w}, "dry_powder_weight": w_dp,
         "dry_powder_return_annual": r_dp (model_assumption; например доходность T-bills), "allow_unaligned": false}
Смесь сценариев (1.2.0, Scenario_Engine_Specification_v1.0): вместо paths_files — "scenarios": [{"id", "probability",
"paths_files": {ticker: .npz}}]; обязателен BASE (вероятность — остаток 1 − Σp, §2); non-BASE с probability null →
pending_owner_judgment: только метрики по сценариям и дельты к BASE. При вероятностях — взвешенная эмпирическая смесь (вес
p_s/N на исход, §6; общие path_id), MedianImpact/ES5Impact/B_s и ScenarioConcentration = max B_s / Σ B_s (§7; warning >50 %,
hard >60 %).
outputs: медианный CAGR 3/5/8Y портфеля, P(2x), P(loss>30/50%), ES5, квантили CAGR 5Y, вклад компаний в медиану Y5,
  корреляции относительных стоимостей Y5 между компаниями, alignment.
"""
from __future__ import annotations

import json
import math

import numpy as np

VERSION = "1.2.0"


def load_paths(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    return {"meta": meta, "r3": z["r3"], "r5": z["r5"], "r8": z["r8"], "maxdd5": z["maxdd5"], "path_id": z["path_id"]}


def _metrics_for(data: dict, w: dict, wdp: float, rdp: float, n: int) -> dict:
    out = {}
    for h, key, yrs in (("Y3", "r3", 3), ("Y5", "r5", 5), ("Y8", "r8", 8)):
        pv = np.zeros(n)
        for t, wt in w.items():
            pv += wt * data[t][key][:n].astype(float)
        pv += wdp * (1.0 + rdp) ** yrs
        cagr = np.power(np.clip(pv, 1e-12, None), 1.0 / yrs) - 1.0; ret = pv - 1.0; k = max(1, int(math.ceil(0.05 * n)))
        out[h] = {"median_CAGR": float(np.median(cagr)), "P_2x": float((pv >= 2).mean()), "P_loss_gt_30pct": float((pv < 0.7).mean()),
                  "P_loss_gt_50pct": float((pv < 0.5).mean()), "expected_shortfall_5pct": float(np.sort(ret)[:k].mean()),
                  "CAGR_quantiles": {str(q): float(np.quantile(cagr, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}}
    return out


def run(inputs: dict, seed: int) -> dict:
    if inputs.get("scenarios"):
        return _run_mixture(inputs, seed)
    files = inputs.get("paths_files") or {}
    w = {k: float(v) for k, v in (inputs.get("weights") or {}).items()}
    wdp = float(inputs.get("dry_powder_weight", 0.0)); rdp = float(inputs.get("dry_powder_return_annual", 0.0))
    if not files:
        raise ValueError("paths_files пуст")
    missing = [t for t in w if t not in files]
    if missing:
        raise ValueError(f"нет файлов путей для {missing}")
    tot = sum(w.values()) + wdp
    if abs(tot - 1.0) > 1e-6:
        raise ValueError(f"веса + dry powder должны давать 1.0, получено {tot:.6f}")
    data = {t: load_paths(files[t]) for t in w}
    metas = {t: d["meta"] for t, d in data.items()}
    ref = next(iter(metas.values()))
    aligned = all(m.get("global_seed") == ref.get("global_seed") and m.get("chunk") == ref.get("chunk") and m.get("paths") == ref.get("paths") for m in metas.values())
    joint_all = all(bool(m.get("joint")) for m in metas.values())
    if not aligned and not inputs.get("allow_unaligned"):
        raise ValueError("пути не выровнены (разные global_seed/chunk/paths) — совместный портфель не считается; allow_unaligned=true только для диагностики")
    n = min(len(d["r5"]) for d in data.values())
    for t, d in data.items():
        if not np.array_equal(d["path_id"][:n], next(iter(data.values()))["path_id"][:n]):
            raise ValueError(f"path_id не совпадают у {t}")
    out_h = {}
    contrib = {}
    for h, key, yrs in (("Y3", "r3", 3), ("Y5", "r5", 5), ("Y8", "r8", 8)):
        pv = np.zeros(n)
        for t, wt in w.items():
            pv += wt * data[t][key][:n].astype(float)
        pv += wdp * (1.0 + rdp) ** yrs
        cagr = np.power(np.clip(pv, 1e-12, None), 1.0 / yrs) - 1.0
        ret = pv - 1.0
        k = max(1, int(math.ceil(0.05 * n)))
        out_h[h] = {"median_CAGR": float(np.median(cagr)), "P_2x": float((pv >= 2).mean()), "P_loss_gt_30pct": float((pv < 0.7).mean()),
                    "P_loss_gt_50pct": float((pv < 0.5).mean()), "expected_shortfall_5pct": float(np.sort(ret)[:k].mean()),
                    "CAGR_quantiles": {str(q): float(np.quantile(cagr, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}}
        if h == "Y5":
            med = float(np.median(pv))
            contrib = {t: float(wt * np.median(data[t][key][:n])) for t, wt in w.items()}
            contrib["dry_powder"] = wdp * (1.0 + rdp) ** yrs
            out_h[h]["median_portfolio_value_rel"] = med
    # корреляции относительных стоимостей Y5 (диагностика совместного слоя)
    tick = list(w)
    corr = {}
    if len(tick) >= 2:
        M = np.stack([np.log(np.clip(data[t]["r5"][:n].astype(float), 1e-9, None)) for t in tick])
        C = np.corrcoef(M)
        corr = {f"{a}__{b}": float(C[i, j]) for i, a in enumerate(tick) for j, b in enumerate(tick) if i < j}
    return {"model_version": VERSION, "paths": int(n), "alignment": {"aligned": aligned, "joint_layer_all": joint_all,
            "global_seed": ref.get("global_seed"), "chunk": ref.get("chunk"), "companies": {t: {"model_version": m.get("model_version"), "joint": bool(m.get("joint"))} for t, m in metas.items()}},
            "weights": w, "dry_powder_weight": wdp, "dry_powder_return_annual": rdp,
            "horizons": out_h, "median_contribution_Y5": contrib, "log_value_correlation_Y5": corr,
            "decision": "none", "note": "не торговый сигнал; вход для MPC (P0 vs P1(w)) и Optimizer; без joint-слоя корреляции между компаниями — только через общий seed идиосинкратики (диагностика)"}


def _wquantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    """Взвешенный эмпирический квантиль: первый исход с накопленной массой ≥ q; при точном попадании массы в q — среднее с
    следующим исходом положительного веса (при равных весах совпадает с np.median/np.quantile для медианы)."""
    o = np.argsort(x, kind="stable"); xs = x[o]; ws = w[o]; cw = np.cumsum(ws); cw /= cw[-1]
    k = int(np.searchsorted(cw, q - 1e-12, side="left").clip(0, len(xs) - 1))
    if abs(cw[k] - q) < 1e-12:
        nxt = k + 1
        while nxt < len(xs) and ws[nxt] <= 0:
            nxt += 1
        if nxt < len(xs):
            return float(0.5 * (xs[k] + xs[nxt]))
    return float(xs[k])


def _wmetrics(pv: np.ndarray, w: np.ndarray, years: int) -> dict:
    """Метрики по взвешенной эмпирической распределённости (Scenario Engine §6): медиана/квантили, P(loss), ES5 — по массе 5 %."""
    cagr = np.power(np.clip(pv, 1e-12, None), 1.0 / years) - 1.0; ret = pv - 1.0
    o = np.argsort(ret, kind="stable"); cw = np.cumsum(w[o]); tail = cw <= 0.05 * cw[-1] * (1.0 + 1e-9)   # допуск на границу массы (float)
    if not tail.any():
        tail[0] = True
    es5 = float(np.average(ret[o][tail], weights=w[o][tail]))
    return {"median_CAGR": _wquantile(cagr, w, 0.5), "P_2x": float(np.average(pv >= 2, weights=w)), "P_loss_gt_30pct": float(np.average(pv < 0.7, weights=w)),
            "P_loss_gt_50pct": float(np.average(pv < 0.5, weights=w)), "expected_shortfall_5pct": es5,
            "CAGR_quantiles": {str(q): _wquantile(cagr, w, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}}


def _run_mixture(inputs: dict, seed: int) -> dict:
    """Смесь сценариев (Scenario_Engine_Specification_v1.0 §2, §6, §7): scenario-specific пути с общими path_id объединяются как
    взвешенная эмпирическая распределённость (вес p_s/N на исход); BASE = остаток 1 − Σp; при pending-вероятностях — только
    метрики по сценариям (смесь, impacts и ScenarioConcentration — not_testable_pending_owner_probability)."""
    scen = inputs["scenarios"]
    w = {k: float(v) for k, v in (inputs.get("weights") or {}).items()}
    wdp = float(inputs.get("dry_powder_weight", 0.0)); rdp = float(inputs.get("dry_powder_return_annual", 0.0))
    if abs(sum(w.values()) + wdp - 1.0) > 1e-6:
        raise ValueError("веса + dry powder должны давать 1.0")
    ids = [sc["id"] for sc in scen]
    if len(set(ids)) != len(ids) or "BASE" not in ids:
        raise ValueError("scenarios: id уникальны и обязателен BASE")
    base_i = ids.index("BASE")
    pend = [sc["id"] for sc in scen if sc["id"] != "BASE" and sc.get("probability") is None]
    probs = None
    if not pend:
        pn = {sc["id"]: float(sc["probability"]) for sc in scen if sc["id"] != "BASE"}
        if any(v < 0 for v in pn.values()) or sum(pn.values()) > 1.0 + 1e-12:
            raise ValueError(f"вероятности non-BASE сценариев должны быть ≥0 и в сумме ≤1: {pn}")
        probs = {**pn, "BASE": 1.0 - sum(pn.values())}
        if scen[base_i].get("probability") is not None and abs(float(scen[base_i]["probability"]) - probs["BASE"]) > 1e-12:
            raise ValueError("probability BASE задана и не равна остатку 1 − Σp")
    loaded = []
    for sc in scen:
        files = sc.get("paths_files") or {}
        missing = [t for t in w if t not in files]
        if missing:
            raise ValueError(f"сценарий {sc['id']}: нет файлов путей для {missing}")
        loaded.append({t: load_paths(files[t]) for t in w})
    n = min(len(d[t]["r5"]) for d in loaded for t in w)
    ref_ids = loaded[base_i][next(iter(w))]["path_id"][:n]; ref_meta = loaded[base_i][next(iter(w))]["meta"]
    for sc, d in zip(scen, loaded):
        for t in w:
            m = d[t]["meta"]
            if m.get("global_seed") != ref_meta.get("global_seed") or m.get("chunk") != ref_meta.get("chunk") or not np.array_equal(d[t]["path_id"][:n], ref_ids):
                raise ValueError(f"сценарий {sc['id']}, {t}: пути не выровнены по path_id с BASE — смесь не считается")
    per = {sc["id"]: _metrics_for(loaded[j], w, wdp, rdp, n) for j, sc in enumerate(scen)}
    delta = {sid: {h: {k: per[sid][h][k] - per["BASE"][h][k] for k in ("median_CAGR", "P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct", "P_2x")} for h in ("Y3", "Y5", "Y8")} for sid in ids if sid != "BASE"}
    out = {"model_version": VERSION, "mode": "scenario_mixture", "spec": "Scenario_Engine_Specification_v1.0", "paths": int(n), "weights": w, "dry_powder_weight": wdp, "dry_powder_return_annual": rdp,
           "scenarios": [{"id": sc["id"], "probability": (probs or {}).get(sc["id"], sc.get("probability"))} for sc in scen],
           "by_scenario": per, "scenario_delta_vs_BASE": delta, "decision": "none"}
    if probs is None:
        out.update({"probability_status": "pending_owner_judgment", "pending": pend, "horizons": None, "scenario_impacts": None, "scenario_concentration": None,
                    "note": "смесь, MedianImpact/ES5Impact/B_s и ScenarioConcentration — not_testable_pending_owner_probability (§2); scenario-specific метрики и дельты к BASE доступны"})
        return out
    # взвешенная эмпирическая смесь: каждый исход сценария s с весом p_s/N
    mix = {}
    for h, key, yrs in (("Y3", "r3", 3), ("Y5", "r5", 5), ("Y8", "r8", 8)):
        pvs, ws = [], []
        for j, sc in enumerate(scen):
            pv = np.zeros(n)
            for t, wt in w.items():
                pv += wt * loaded[j][t][key][:n].astype(float)
            pv += wdp * (1.0 + rdp) ** yrs
            pvs.append(pv); ws.append(np.full(n, probs[sc["id"]] / n))
        mix[h] = _wmetrics(np.concatenate(pvs), np.concatenate(ws), yrs)
    impacts = {}
    for sid in ids:
        if sid == "BASE":
            continue
        p_s = probs[sid]; b = per["BASE"]["Y5"]; m = per[sid]["Y5"]
        impacts[sid] = {"probability": p_s, "MedianImpact_Y5": p_s * (m["median_CAGR"] - b["median_CAGR"]), "ES5Impact_Y5": p_s * (m["expected_shortfall_5pct"] - b["expected_shortfall_5pct"]),
                        "adverse_ES_burden_B": p_s * max(0.0, b["expected_shortfall_5pct"] - m["expected_shortfall_5pct"])}
    tot = sum(v["adverse_ES_burden_B"] for v in impacts.values())
    conc = (max(v["adverse_ES_burden_B"] for v in impacts.values()) / tot) if tot > 0 else 0.0
    out.update({"probability_status": "owner_judgment", "horizons": mix, "scenario_impacts": impacts,
                "scenario_concentration": {"value": conc, "no_adverse_scenario_burden": tot <= 0, "warning": conc > 0.50, "hard_limit_breach": conc > 0.60, "rule": "max_s B_s / Σ_s B_s по non-BASE; warning >50 %, hard >60 % (Optimizer v1.0)"},
                "note": "медиана и ES5 нелинейны — impacts диагностические, не аддитивное разложение (§7)"})
    return out
