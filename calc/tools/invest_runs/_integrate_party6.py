"""Интеграция партии 6 (пакет IMMA_SPOT_ETN_Party6_v1.0): SPOT RV v1.0 + MC v1.0 (архетип A, EUR) в portfolio/spot (стадия
company_model → conditional_mc), ETN mc v1.0.2 (замена v1.0.1 в папке; RV не менялась) — calc_runs + info_log дамп-идемпотентно.
Запуск: python _integrate_party6.py <workspace> SPOT=<mc_run> ETN=<mc_run> [--apply]"""
import json
import re
import sys
from pathlib import Path


def dump(st: dict, raw: str) -> str:
    one_line = bool(re.search(r'\n\s*\{"kpi_id": ', raw))
    inline_ids = bool(re.search(r'"verification_run_ids": \[[ \t]*"', raw))
    st2 = dict(st); obs = st.get("kpi_observations") or []
    if one_line and obs:
        st2["kpi_observations"] = [f"@@OBS{i}@@" for i in range(len(obs))]
    txt = json.dumps(st2, ensure_ascii=False, indent=2) + "\n"
    if one_line:
        for i, o in enumerate(obs):
            txt = txt.replace(f'"@@OBS{i}@@"', json.dumps(o, ensure_ascii=False))
    if inline_ids:
        txt = re.sub(r'"verification_run_ids": \[\n((?:[ \t]*"[^"\n]*",?\n)+)[ \t]*\]', lambda m: '"verification_run_ids": [' + ", ".join(x.strip().rstrip(",") for x in m.group(1).strip().split("\n")) + "]", txt)
    return txt if raw.endswith("\n") else txt.rstrip("\n")


WS = Path(sys.argv[1]); RUNS = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a); APPLY = "--apply" in sys.argv
SRC = WS / "from_imma" / "SPOT_ETN_Party6_v1.0"; NOW = "2026-09-25T14:30:00Z"
RV_RUNS = {"SPOT": "20260925T133204Z-reverse_valuation-66a42b"}
VALRUN = {"SPOT": "1848a3", "ETN": "867bdc"}
PLAN = {"SPOT": ("spot", [(SRC / "SPOT_calibration_v1.0.yaml", "calibration_v1.0.yaml"), (SRC / "SPOT_mc_calibration_v1.0.yaml", "mc_calibration_v1.0.yaml")], None),
        "ETN": ("etn", [(SRC / "ETN_mc_calibration_v1.0.2.yaml", "mc_calibration_v1.0.2.yaml")], "mc_calibration_v1.0.1.yaml")}
PURPOSE = {"SPOT": "нормативный прогон принятой калибровки SPOT v1.0 партии 6 (архетип A, калибровка целиком в EUR: equity_value_0 = USD 509.45 × 205.58 млн акций / 1.1460 = 91.39 млрд EUR; валидатор 1.7.0 …-1848a3 pass под Joint v1.1, MC-G5-013 в норме; intrinsic W 0.232 ниже ориентира A 0.25 — задокументировано IMMA, не подгонялось; 3 предупреждения MC-G5-001 — reviewed-immaterial по решению IMMA)",
           "ETN": "нормативный прогон переиздания ETN mc v1.0.2 под Joint v1.1 (v1.0.1 не проходила MC-G5-013 под v1.1: ElectricalAmericas σ 0.160 > 0.15 из-за корней INDUSTRIAL_RESHORING; в v1.0.2 шесть вкладов ×0.90 → σ 0.143; check_supersedes: пропаж 0 / изменено 6; валидатор 1.7.0 …-867bdc pass; intrinsic W 0.280 / full 0.331)"}
LOG = {"SPOT": "Интеграция калибровки SPOT v1.0 (партия 6, 25.09; EUR): calibration_v1.0.yaml + mc_calibration_v1.0.yaml приняты (валидатор 1.7.0 режим calibration pass под Joint v1.1); RV …-66a42b: implied CAGR 5Y 10.1 %, TV share 0.859, terminal_dependent (предрасчёт IMMA 9.25 % / 0.828 — расхождение вынесено IMMA); нормативные прогоны: ",
       "ETN": "Переиздание ETN mc v1.0.2 под Joint v1.1 (партия 6, 25.09; ×0.90 к шести вкладам на ElectricalAmericas по MC-G5-013): принято (check_supersedes OK, валидатор 1.7.0 …-867bdc pass); прежний файл mc_calibration_v1.0.1.yaml удалён из папки (from_imma/git); прежние прогоны (…-c0c4ef) остаются записями воспроизводимости; новый нормативный прогон: "}


def run_record(run_id: str) -> dict:
    return json.load(open(WS / "portfolio" / "_runs" / f"{run_id}.json", encoding="utf-8"))


def mc_entry(tk: str, rid: str, cal_name: str) -> dict:
    r = run_record(rid); o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; rb = o.get("robustness") or {}
    return {"run_id": rid, "model": "company_mc", "version": o.get("model_version"), "timestamp": r["run_id"][:15],
            "spec": "Company_Conditional_Monte_Carlo_Specification_v1.1.3 (Joint_Simulation_Layer_Schema v1.1, Rules v1.1.2; company_mc 2.3.2, parity-gated blend)",
            "calibration": cal_name, "purpose": PURPOSE[tk],
            "equity_value_0_b": round(r["inputs"]["equity_value_0"] / 1e9, 1), "paths": r["inputs"].get("paths") or 500000, "seed": r["seed"],
            "summary": {"median_CAGR_3Y": round(b["return"]["median_CAGR_3Y"], 4), "median_CAGR_5Y": round(b["return"]["median_CAGR_5Y"], 4), "median_CAGR_8Y": round(b["return"]["median_CAGR_8Y"], 4),
                        "CAGR_5Y_q05_q95": [round(q["0.05"], 3), round(q["0.95"], 3)], "P_2x_5Y": round(b["return"]["P_2x_5Y"], 4), "P_loss_gt_30pct_5Y": round(b["downside"]["P_loss_gt_30pct_5Y"], 4),
                        "P_loss_gt_50pct_5Y": round(b["downside"]["P_loss_gt_50pct_5Y"], 4), "ES5": round(b["downside"]["expected_shortfall_5pct_5Y"], 4),
                        "median_equity_value_5Y_b": round(b["median_equity_value_5Y_b"], 1), "RV_Growth_Gap": round(b["gap_metrics"]["RV_Growth_Gap"], 4), "Price_Expectation_Gap": round(b["gap_metrics"]["Price_Expectation_Gap"], 4),
                        "convergence_stable": (o.get("convergence") or {}).get("stable"), "robustness_pass": rb.get("pass"), "robustness_shares": [rb.get("same_sign_share"), rb.get("within_delta_tolerance_share")]},
            "paths_file": (o.get("paths_file") or "").replace("/data/workspace-invest/", ""), "valuation_crossover": (b.get("valuation_crossover") or {}).get("mode"), "basis_parity_margin_Y5": (b.get("basis_parity_margin") or {}).get("Y5")}


def rv_entry(tk: str, rid: str) -> dict:
    r = run_record(rid); o = r["outputs"]; c = o["calculated"]; ms = o.get("model_stability") or {}
    return {"run_id": rid, "model": f"reverse_valuation {o.get('model_version')}", "spec": o.get("spec_version"), "calibration": f"{tk}_calibration_v1.0 (EUR)", "valuation_date": r["inputs"].get("valuation_date"),
            "price": r["inputs"]["market"]["price"], "currency": "EUR", "shares_outstanding": r["inputs"]["market"]["shares_outstanding"], "equity_value_b": round(c["equity_value"] / 1e9, 2),
            "implied_revenue_cagr_5y": round(c["implied_revenue_cagr_5y"], 4), "terminal_value_share_of_pv": round(c["terminal_value_share_of_pv"], 4), "model_stability": ms.get("class"),
            "note": "Первый нормативный RV-прогон SPOT; калибровка целиком в EUR (цена NYSE 18.09 / курс ЕЦБ 1.1460); класс устойчивости по Reverse_Valuation_Rules_v1.1 §1 — " + str(ms.get("class")) + "; предрасчёт IMMA 9.25 % / TV share 0.828 против хоста 10.08 % / 0.859 — расхождение (вероятно, вычет чистого кэша в предрасчёте) передано IMMA, хост авторитетен"}


changes = []
for tk, (folder, files, old_name) in PLAN.items():
    if tk not in RUNS:
        continue
    fd = WS / "portfolio" / folder
    for src, name in files:
        dst = fd / name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            changes.append(f"{folder}/{name} ← {src.name}")
            if APPLY: dst.write_bytes(src.read_bytes())
    if old_name and (fd / old_name).exists():
        changes.append(f"{folder}/{old_name}: удалить (прежняя версия; копия в from_imma и git)")
        if APPLY: (fd / old_name).unlink()
    sp = fd / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); st = json.loads(raw)
    idem = dump(st, raw.replace("\r\n", "\n")) == raw.replace("\r\n", "\n")
    entries = [e for e in [rv_entry(tk, RV_RUNS[tk]) if tk in RV_RUNS else None, mc_entry(tk, RUNS[tk], files[-1][1])] if e]
    have = {e.get("run_id") for e in st.get("calc_runs", [])}
    new = [e for e in entries if e["run_id"] not in have]
    if new:
        if not idem:
            changes.append(f"{folder}/state.json: НЕ идемпотентен для дампа — записи calc_runs НЕ добавлены (нужен построчный патч)")
        else:
            changes.append(f"{folder}/state.json: +{len(new)} calc_runs ({', '.join(e['run_id'] for e in new)})")
            if APPLY:
                st.setdefault("calc_runs", []).extend(new)
                st.setdefault("info_log", []).append({"timestamp": NOW, "kind": "calc", "summary": LOG[tk] + ", ".join(e["run_id"] for e in new)})
                st["updated"] = NOW
                with open(sp, "w", encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n") as fh:
                    fh.write(dump(st, raw.replace("\r\n", "\n")))
if "SPOT" in RUNS:
    cp = WS / "portfolio" / "_candidates.yaml"; raw = cp.read_bytes(); text = raw.decode("utf-8").replace("\r\n", "\n")
    out = re.sub(r"(\{ticker: SPOT,[^\n]*?stage: )company_model", r"\1conditional_mc", text, count=1)
    if out != text:
        changes.append("_candidates.yaml: SPOT stage company_model → conditional_mc")
        if APPLY: cp.write_bytes((out.replace("\n", "\r\n") if b"\r\n" in raw else out).encode("utf-8"))
for c in changes: print("-", c)
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
