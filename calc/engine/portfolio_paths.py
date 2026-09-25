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
Экспорт смеси (1.3.0, режим "mixture_export"): inputs {"mode": "mixture_export", "scenarios": [...как выше, с вероятностями...],
  "out_dir": каталог, "tag": метка} → по каждой компании файл путей-смеси <out_dir>/<tag>-mixture-<TK>-paths.npz: разбиение
  path_id по сценариям (BASE — [0, k_B), далее сценарии по порядку списка; k_s = round(p_s·N) с округлением вниз до чётного,
  чтобы не резать антитетические пары; BASE — остаток), одни и те же диапазоны у всех компаний → совместная структура путей
  сохраняется; meta — как у BASE-файла (global_seed/chunk/paths/joint) + "mixture". Файлы-смеси читаются оптимизатором и
  Stability без изменений; их метрики — стратифицированная выборка взвешенной смеси §6 (проверяется тестом).
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

VERSION = "1.3.0"


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
    if inputs.get("mode") == "mixture_export":
        return _export_mixture(inputs)
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
    out.update({"probability_status": "owner_judgment", "horizons": mix, "scenario_impacts": impacts,
                "scenario_concentration": scenario_concentration({sid: v["adverse_ES_burden_B"] for sid, v in impacts.items()}),
                "note": "медиана и ES5 нелинейны — impacts диагностические, не аддитивное разложение (§7)"})
    return out


def scenario_concentration(burdens: dict) -> dict:
    """ScenarioConcentration по правилу IMMA (ответ 25.09 на вопрос 3.4, вариант «а»): A = {s: B_s > 0} среди non-BASE;
    |A| = 0 → not_applicable_no_adverse_scenario; |A| = 1 → raw = 1.0 (тавтология), лимит not_applicable_single_adverse_scenario;
    |A| ≥ 2 → max B_s / Σ B_s по A, warning > 50 %, hard > 60 % (Optimizer v1.0 §3). BASE в знаменатель не входит."""
    A = {sid: float(b) for sid, b in burdens.items() if float(b) > 0.0}
    rule = "A = {s: B_s > 0}; |A| < 2 → лимит не применяется (raw показывается); |A| ≥ 2 → max B_s / Σ B_s ≤ 0.60 (warning > 0.50); BASE вне знаменателя (IMMA 25.09.2026, вариант а)"
    if not A:
        return {"value": None, "raw_value": None, "adverse_scenarios": [], "applicable": False, "status": "not_applicable_no_adverse_scenario", "warning": False, "hard_limit_breach": False, "rule": rule}
    raw = max(A.values()) / sum(A.values())
    if len(A) == 1:
        return {"value": None, "raw_value": raw, "adverse_scenarios": sorted(A), "applicable": False, "status": "not_applicable_single_adverse_scenario", "warning": False, "hard_limit_breach": False, "rule": rule}
    return {"value": raw, "raw_value": raw, "adverse_scenarios": sorted(A), "applicable": True, "status": "applicable", "warning": raw > 0.50, "hard_limit_breach": raw > 0.60, "rule": rule}


def mixture_ranges(n: int, probs: dict, order: list) -> dict:
    """Разбиение N path_id по сценариям: k_s = round(p_s·N), округление вниз до чётного (антитетические пары внутри чанков идут
    подряд), BASE — остаток; порядок: BASE, затем сценарии по списку order. Возвращает {id: (start, stop)}."""
    ks = {}
    for sid in order:
        if sid == "BASE":
            continue
        k = int(round(float(probs[sid]) * n)); k -= k % 2
        ks[sid] = max(0, k)
    used = sum(ks.values())
    if used > n:
        raise ValueError(f"Σ k_s = {used} > N = {n}")
    ranges = {"BASE": (0, n - used)}; pos = n - used
    for sid in order:
        if sid == "BASE":
            continue
        ranges[sid] = (pos, pos + ks[sid]); pos += ks[sid]
    return ranges


def _export_mixture(inputs: dict) -> dict:
    """Режим mixture_export (1.3.0): файлы путей-смеси по компаниям — стратифицированная выборка взвешенной смеси §6 по
    разбиению path_id (общие диапазоны у всех компаний). Требует вероятностей у всех non-BASE сценариев."""
    scen = inputs["scenarios"]; ids = [sc["id"] for sc in scen]
    if len(set(ids)) != len(ids) or "BASE" not in ids:
        raise ValueError("scenarios: id уникальны и обязателен BASE")
    pn = {}
    for sc in scen:
        if sc["id"] == "BASE":
            continue
        if sc.get("probability") is None:
            raise ValueError(f"mixture_export: у сценария {sc['id']} нет вероятности (pending) — экспорт смеси невозможен (§2)")
        pn[sc["id"]] = float(sc["probability"])
    if any(v < 0 for v in pn.values()) or sum(pn.values()) > 1.0 + 1e-12:
        raise ValueError(f"вероятности non-BASE сценариев должны быть ≥0 и в сумме ≤1: {pn}")
    probs = {**pn, "BASE": 1.0 - sum(pn.values())}
    base = next(sc for sc in scen if sc["id"] == "BASE")
    tickers = list(inputs.get("tickers") or base["paths_files"].keys())
    for sc in scen:
        missing = [t for t in tickers if t not in (sc.get("paths_files") or {})]
        if missing:
            raise ValueError(f"сценарий {sc['id']}: нет файлов путей для {missing}")
    out_dir = inputs.get("out_dir") or os.path.dirname(base["paths_files"][tickers[0]]); tag = str(inputs.get("tag") or "mixture")
    os.makedirs(out_dir, exist_ok=True)
    files_out = {}; ranges = None; n_ref = None; ref_meta = None
    for t in tickers:
        loaded = {sc["id"]: load_paths(sc["paths_files"][t]) for sc in scen}
        z0 = np.load(base["paths_files"][t], allow_pickle=False); keys = [k for k in z0.files if k != "meta"]
        n = min(len(d["r5"]) for d in loaded.values())
        if n_ref is None:
            n_ref = n; ref_meta = loaded["BASE"]["meta"]; ranges = mixture_ranges(n, probs, ids)
        elif n != n_ref:
            raise ValueError(f"{t}: число путей {n} ≠ {n_ref} у первой компании — смесь не выравнивается")
        m0 = loaded["BASE"]["meta"]
        if m0.get("global_seed") != ref_meta.get("global_seed") or m0.get("chunk") != ref_meta.get("chunk") or m0.get("paths") != ref_meta.get("paths"):
            raise ValueError(f"{t}: BASE-пути не выровнены с первой компанией (global_seed/chunk/paths)")
        ref_ids = loaded["BASE"]["path_id"][:n]
        for sid, d in loaded.items():
            if d["meta"].get("global_seed") != m0.get("global_seed") or d["meta"].get("chunk") != m0.get("chunk") or not np.array_equal(d["path_id"][:n], ref_ids):
                raise ValueError(f"сценарий {sid}, {t}: пути не выровнены по path_id с BASE — смесь не считается")
        arrays = {}
        for k in keys:
            parts = []
            for sid in ["BASE"] + [s for s in ids if s != "BASE"]:
                a, b = ranges[sid]
                z = np.load(scen[ids.index(sid)]["paths_files"][t], allow_pickle=False)
                parts.append(z[k][a:b])
            arrays[k] = np.concatenate(parts)
        meta = dict(m0); meta["mixture"] = {"spec": "Scenario_Engine_Specification_v1.0 §6 — stratified partition by path_id", "probabilities": probs,
                                            "ranges": {sid: list(r) for sid, r in ranges.items()}, "source_files": {sc["id"]: sc["paths_files"][t] for sc in scen}, "exporter": f"portfolio_paths {VERSION}"}
        fp = os.path.join(out_dir, f"{tag}-mixture-{t}-paths.npz")
        np.savez_compressed(fp, meta=np.array(json.dumps(meta, ensure_ascii=False)), **arrays)
        files_out[t] = fp
    return {"model_version": VERSION, "mode": "mixture_export", "spec": "Scenario_Engine_Specification_v1.0", "paths": int(n_ref), "probabilities": probs,
            "ranges": {sid: list(r) for sid, r in ranges.items()}, "paths_files": files_out,
            "note": "файлы-смеси = стратифицированная выборка взвешенной смеси §6 (одни диапазоны path_id у всех компаний); читаются оптимизатором и Stability без изменений"}
