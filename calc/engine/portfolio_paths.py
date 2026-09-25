"""Агрегация портфеля по совместным путям v1.0 (Portfolio_Optimizer_Specification_v1.0 §7): срез 4 company_mc.

PortfolioValue_h = Σ_i w_i · RelativeValue_i,h + w_dp · (1 + r_dp)^h — по одному и тому же path_id у всех компаний.
Файлы путей пишет company_mc (inputs.paths_out) в формате .npz: r3, r5, r8, maxdd5 (float32, относительная стоимость
к E0 и просадка), b3/b5/b8 (int8, basis), path_id (int64) и meta (JSON: ticker, model_version, global_seed, chunk, paths,
joint). Совместимость путей проверяется по meta: одинаковые global_seed, chunk, paths и joint=true у всех.

inputs: {"paths_files": {ticker: путь .npz}, "weights": {ticker: w}, "dry_powder_weight": w_dp,
         "dry_powder_return_annual": r_dp (model_assumption; например доходность T-bills), "allow_unaligned": false}
Смешивание сценариев (1.1.0, ЧЕРНОВИК до Scenario Engine v1.0): вместо paths_files — "scenarios": [{"id", "probability",
"paths_files": {ticker: .npz}}] (сумма вероятностей 1; пути всех сценариев выровнены по path_id — общий global_seed);
по каждому path_id сценарий выбирается детерминированно (mixture_seed) по вероятностям → смесь; в выходе — метрики смеси,
по каждому сценарию отдельно и scenario_delta (медиана/ES5/P(loss) к первому сценарию в списке, обычно BASE);
scenario_concentration — None до определения IMMA.
outputs: медианный CAGR 3/5/8Y портфеля, P(2x), P(loss>30/50%), ES5, квантили CAGR 5Y, вклад компаний в медиану Y5,
  корреляции относительных стоимостей Y5 между компаниями, alignment.
"""
from __future__ import annotations

import json
import math

import numpy as np

VERSION = "1.1.0"


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


def _run_mixture(inputs: dict, seed: int) -> dict:
    """Смесь сценариев по path_id (черновик): выбор сценария на путь по вероятностям, метрики смеси и по сценариям."""
    scen = inputs["scenarios"]
    w = {k: float(v) for k, v in (inputs.get("weights") or {}).items()}
    wdp = float(inputs.get("dry_powder_weight", 0.0)); rdp = float(inputs.get("dry_powder_return_annual", 0.0))
    probs = np.array([float(sc.get("probability", 0.0)) for sc in scen])
    if abs(probs.sum() - 1.0) > 1e-6 or (probs < 0).any():
        raise ValueError(f"вероятности сценариев должны быть ≥0 и давать 1.0, получено {probs.tolist()}")
    if abs(sum(w.values()) + wdp - 1.0) > 1e-6:
        raise ValueError("веса + dry powder должны давать 1.0")
    loaded = []
    for sc in scen:
        files = sc.get("paths_files") or {}
        missing = [t for t in w if t not in files]
        if missing:
            raise ValueError(f"сценарий {sc.get('id')}: нет файлов путей для {missing}")
        loaded.append({t: load_paths(files[t]) for t in w})
    n = min(len(d[t]["r5"]) for d in loaded for t in w)
    ref_ids = loaded[0][next(iter(w))]["path_id"][:n]; ref_meta = loaded[0][next(iter(w))]["meta"]
    for sc, d in zip(scen, loaded):
        for t in w:
            m = d[t]["meta"]
            if m.get("global_seed") != ref_meta.get("global_seed") or m.get("chunk") != ref_meta.get("chunk") or not np.array_equal(d[t]["path_id"][:n], ref_ids):
                raise ValueError(f"сценарий {sc.get('id')}, {t}: пути не выровнены по path_id с {scen[0].get('id')} — смесь не считается")
    rng = np.random.default_rng(int(inputs.get("mixture_seed", seed)) + 424_243)
    choice = rng.choice(len(scen), size=n, p=probs)          # сценарий на путь (детерминировано)
    mixed = {t: {key: np.select([choice == j for j in range(len(scen))], [loaded[j][t][key][:n] for j in range(len(scen))]) for key in ("r3", "r5", "r8")} for t in w}
    mix = _metrics_for(mixed, w, wdp, rdp, n)
    per = {sc["id"]: _metrics_for(loaded[j], w, wdp, rdp, n) for j, sc in enumerate(scen)}
    base_id = scen[0]["id"]
    delta = {sc["id"]: {h: {k: per[sc["id"]][h][k] - per[base_id][h][k] for k in ("median_CAGR", "P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct", "P_2x")} for h in ("Y3", "Y5", "Y8")} for sc in scen[1:]}
    shares = {sc["id"]: float((choice == j).mean()) for j, sc in enumerate(scen)}
    return {"model_version": VERSION, "mode": "scenario_mixture_draft", "paths": int(n), "weights": w, "dry_powder_weight": wdp, "dry_powder_return_annual": rdp,
            "scenarios": [{"id": sc["id"], "probability": float(sc["probability"]), "realized_share": shares[sc["id"]]} for sc in scen], "mixture_seed": int(inputs.get("mixture_seed", seed)),
            "horizons": mix, "by_scenario": per, "scenario_delta_vs_first": delta, "scenario_concentration": None,
            "note": "ЧЕРНОВИК до Scenario Engine v1.0: смесь по path_id (общие случайные числа), дельта сценария = разность метрик сценария и первого в списке; определение Scenario Concentration и вклада смеси — по спецификации IMMA; decision: none",
            "decision": "none"}
