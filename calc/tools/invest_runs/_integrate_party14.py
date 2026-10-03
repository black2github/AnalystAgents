"""Интеграция принятых калибровок партии 14 (сейчас — HPS.A v1.0; S / CRWD — после подтверждения / переиздания IMMA) в папки компаний
(роль интегратора): файлы calibration_v1.0.yaml + mc_calibration_v1.0.yaml из from_imma, записи calc_runs (RV, MC) и info_log в state.json
(полная перезапись json indent=2 — файлы партии 13 дамп-идемпотентны), стадия в _candidates.yaml → conditional_mc, запись в
_calibration_lifecycle.yaml (state current), карта нормативных прогонов _norm_runs_joint11.json (пути для портфельного слоя).
Запуск: ONLY=HPSA python _integrate_party14.py [--apply]"""
import json
import os
import re
import sys
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); PK = WS / "from_imma" / "Party14_CRWD_HPSA_S_RV_MC_Calibrations_v1.0"; S = Path(__file__).parent
APPLY = "--apply" in sys.argv; NOW = "2026-10-03T21:30:00Z"; TODAY = "2026-10-03"
ONLY = set(os.environ.get("ONLY", "HPSA").split(","))
META = {"HPSA": {"ticker": "HPS.A", "folder": "hps_a", "rv": "20261003T205836Z-reverse_valuation-445a1a", "val": "20261003T205837Z-artifact_validator-91e257", "mc": "20261003T210242Z-company_mc-98b0da",
                 "archetype": "mature_positive_margin", "anchor": "2026-06-27", "fq": "Q2 2026",
                 "purpose": "нормативный прогон принятой калибровки HPS.A v1.0 партии 14 (архетип A с M&A-переходом: база без AEG до Q3 2026; валидатор 1.10.1: схема 1.0.2, MC-G5-013 pass σ 0.114/0.015/0.032, 5× MC-G5-001 reviewed-immaterial; intrinsic W 0.270 в ориентире; robustness 1.0/1.0)"},
        "S": {"ticker": "S", "folder": "s", "rv": "20261003T205839Z-reverse_valuation-d4986d", "val": "20261003T205839Z-artifact_validator-d65ac5", "mc": "20261003T210450Z-company_mc-775457",
              "archetype": "mature_positive_margin", "anchor": "2026-07-31", "fq": "Q2 FY2027",
              "purpose": "нормативный прогон калибровки S v1.0 партии 14 (архетип A, старт FCF-маржи 4 % model_assumption; валидатор pass; intrinsic W 0.223 — warning; robustness: знак 0.625 — вырожденный случай медианы ≈ 0, допуск 1.0)"},
        "CRWD": {"ticker": "CRWD", "folder": "crwd", "rv": "20261003T205832Z-reverse_valuation-83e31c", "val": "20261003T205833Z-artifact_validator-9814fa", "mc": None,
                 "archetype": "mature_positive_margin", "anchor": "2026-07-31", "fq": "Q2 FY2027", "purpose": ""}}


def rec(rid):
    return json.load(open(WS / "portfolio" / "_runs" / f"{rid}.json", encoding="utf-8"))


def mc_entry(m):
    r = rec(m["mc"]); o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; rb = o.get("robustness") or {}
    return {"run_id": m["mc"], "model": "company_mc", "version": o.get("model_version"), "timestamp": m["mc"][:15],
            "spec": "Company_Conditional_Monte_Carlo_Specification_v1.1.3 (Joint_Simulation_Layer_Rules_v1.1.2; company_mc 2.5.0, parity-gated blend)",
            "calibration": "mc_calibration_v1.0.yaml", "purpose": m["purpose"], "equity_value_0_b": round(r["inputs"]["equity_value_0"] / 1e9, 2), "paths": r["inputs"].get("paths") or 500000, "seed": r["seed"],
            "summary": {"median_CAGR_3Y": round(b["return"]["median_CAGR_3Y"], 4), "median_CAGR_5Y": round(b["return"]["median_CAGR_5Y"], 4), "median_CAGR_8Y": round(b["return"]["median_CAGR_8Y"], 4),
                        "CAGR_5Y_q05_q95": [round(q["0.05"], 3), round(q["0.95"], 3)], "P_2x_5Y": round(b["return"]["P_2x_5Y"], 4), "P_loss_gt_30pct_5Y": round(b["downside"]["P_loss_gt_30pct_5Y"], 4),
                        "P_loss_gt_50pct_5Y": round(b["downside"]["P_loss_gt_50pct_5Y"], 4), "ES5": round(b["downside"]["expected_shortfall_5pct_5Y"], 4),
                        "median_equity_value_5Y_b": round(b["median_equity_value_5Y_b"], 2), "RV_Growth_Gap": round(b["gap_metrics"]["RV_Growth_Gap"], 4), "Price_Expectation_Gap": round(b["gap_metrics"]["Price_Expectation_Gap"], 4),
                        "convergence_stable": (o.get("convergence") or {}).get("stable"), "robustness_pass": rb.get("pass"), "robustness_shares": [rb.get("same_sign_share"), rb.get("within_delta_tolerance_share")]},
            "paths_file": (o.get("paths_file") or "").replace("/data/workspace-invest/", ""), "valuation_crossover": (b.get("valuation_crossover") or {}).get("mode"), "basis_parity_margin_Y5": (b.get("basis_parity_margin") or {}).get("Y5")}


def rv_entry(m):
    r = rec(m["rv"]); o = r["outputs"]; c = o["calculated"]; ms = o.get("model_stability") or {}
    return {"run_id": m["rv"], "model": f"reverse_valuation {o.get('model_version')}", "spec": o.get("spec_version"), "calibration": "calibration_v1.0.yaml", "valuation_date": r["inputs"].get("valuation_date"),
            "price": r["inputs"]["market"]["price"], "shares_outstanding": r["inputs"]["market"]["shares_outstanding"], "equity_value_b": round(c["equity_value"] / 1e9, 2), "currency": r["inputs"].get("currency"),
            "implied_revenue_cagr_5y": round(c["implied_revenue_cagr_5y"], 4), "terminal_value_share_of_pv": round(c["terminal_value_share_of_pv"], 4), "model_stability": ms.get("class"),
            "note": "Первый нормативный RV-прогон (партия 14); класс устойчивости по Reverse_Valuation_Rules_v1.1 §1 — " + str(ms.get("class"))}


changes = []
norm = json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8"))
life = yaml.safe_load((WS / "portfolio/_calibration_lifecycle.yaml").read_text(encoding="utf-8"))
for key in sorted(ONLY):
    m = META[key]; fd = WS / "portfolio" / m["folder"]; pfx = key
    for src_name, dst_name in ((f"{pfx}_calibration_v1.0.yaml", "calibration_v1.0.yaml"), (f"{pfx}_mc_calibration_v1.0.yaml", "mc_calibration_v1.0.yaml")):
        src = PK / src_name; dst = fd / dst_name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            changes.append(f"{m['folder']}/{dst_name} ← {src_name}")
            if APPLY:
                dst.write_bytes(src.read_bytes())
    sp = fd / "state.json"; raw = sp.read_text(encoding="utf-8"); st = json.loads(raw)
    entries = [rv_entry(m)] + ([mc_entry(m)] if m["mc"] else [])
    have = {e.get("run_id") for e in st.get("calc_runs", [])}
    new = [e for e in entries if e["run_id"] not in have]
    if new:
        changes.append(f"{m['folder']}/state.json: +{len(new)} calc_runs ({', '.join(e['run_id'] for e in new)}), info_log, pending_verification: dozor_full_model_verification остаётся")
        if APPLY:
            st.setdefault("calc_runs", []).extend(new)
            st.setdefault("info_log", []).append({"timestamp": NOW, "kind": "calc", "summary": f"Интеграция калибровки {m['ticker']} v1.0 (партия 14, {TODAY}): calibration_v1.0.yaml + mc_calibration_v1.0.yaml приняты (RV {m['rv'][-6:]}, валидатор calibration pass {m['val'][-6:]}); нормативный прогон: {m['mc'] or '—'}"})
            st["updated"] = NOW
            sp.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if m["mc"]:
        if norm.get(m["ticker"]) != m["mc"]:
            changes.append(f"_norm_runs_joint11.json: {m['ticker']} → {m['mc']}"); norm[m["ticker"]] = m["mc"]
        if not any(c.get("ticker") == m["ticker"] for c in life["calibrations"]):
            changes.append(f"_calibration_lifecycle.yaml: + {m['ticker']} current")
            life["calibrations"].append({"ticker": m["ticker"], "folder": m["folder"], "archetype": m["archetype"], "mc_file": "mc_calibration_v1.0.yaml", "mc_as_of": TODAY, "rv_file": "calibration_v1.0.yaml", "rv_as_of": TODAY,
                                         "base_period_anchor": m["anchor"], "base_period_fiscal_quarter": m["fq"], "lifecycle_state": "current", "last_check": TODAY,
                                         "last_check_basis": f"приёмка партии 14 ({TODAY}): RV {m['rv'][-6:]}, валидатор {m['val'][-6:]}, норматив {m['mc'][-6:]}",
                                         "next_mandatory_check": "после публикации отчёта за Q3 2026 (CLR-1 §5.1 — сверка дозором; HPS.A: первая консолидация AEG → CLR-2 пересмотр базы)" if key == "HPSA" else "после публикации отчёта за Q3 FY2027 (CLR-1 §5.1)",
                                         "open_bases": []})
# стадия в _candidates.yaml
cp = WS / "portfolio/_candidates.yaml"; text = cp.read_text(encoding="utf-8"); out = text
for key in sorted(ONLY):
    tk = META[key]["ticker"]
    out2 = re.sub(rf"(\{{ticker: {re.escape(tk)},[^\n]*?stage: )company_model", r"\1conditional_mc", out, count=1)
    if out2 != out:
        changes.append(f"_candidates.yaml: {tk} stage company_model → conditional_mc"); out = out2
if APPLY:
    if out != text:
        cp.write_text(out, encoding="utf-8", newline="\n")
    json.dump(norm, open(S / "_norm_runs_joint11.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    # _calibration_lifecycle.yaml — CRLF-файл: дописываем блок текстом (yaml.dump переформатирует весь файл)
    lp = WS / "portfolio/_calibration_lifecycle.yaml"; raw = lp.read_bytes().decode("utf-8"); crlf = "\r\n" in raw; txt = raw.replace("\r\n", "\n")
    txt = re.sub(r"^updated: '\d{4}-\d{2}-\d{2}'", f"updated: '{TODAY}'", txt, count=1, flags=re.M)
    for c in life["calibrations"]:
        if f"- ticker: {c['ticker']}\n" not in txt:
            txt = txt.rstrip("\n") + "\n" + yaml.safe_dump([c], allow_unicode=True, sort_keys=False, width=140)
    lp.write_bytes((txt.replace("\n", "\r\n") if crlf else txt).encode("utf-8"))
for c in changes:
    print("-", c)
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
