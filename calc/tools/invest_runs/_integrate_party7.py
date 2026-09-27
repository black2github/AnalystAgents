"""Интеграция партии 7: SPCX mc v1.1.3 (миграция на схему 1.0.2; файл в portfolio/spacex, v1.1.2 снимается из папки) + calc_runs/info_log;
TAIWAN_QUARANTINE_v1.0.yaml уже скопирован в portfolio/_scenarios (валидатор pass). Запуск: python _integrate_party7.py <workspace> SPCX=<run> [--apply]"""
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
SRC = WS / "from_imma" / "Party7_TAIWAN_QUARANTINE_SPCX_v1.0"; NOW = "2026-09-25T21:00:00Z"
fd = WS / "portfolio" / "spacex"; rid = RUNS["SPCX"]; changes = []
src, name, old = SRC / "SPCX_mc_calibration_v1.1.3.yaml", "mc_calibration_v1.1.3.yaml", "mc_calibration_v1.1.2.yaml"
if not (fd / name).exists() or (fd / name).read_bytes() != src.read_bytes():
    changes.append(f"spacex/{name} ← {src.name}")
    if APPLY: (fd / name).write_bytes(src.read_bytes())
if (fd / old).exists():
    changes.append(f"spacex/{old}: удалить (прежняя версия; копия в from_imma и git)")
    if APPLY: (fd / old).unlink()
r = json.load(open(WS / "portfolio" / "_runs" / f"{rid}.json", encoding="utf-8")); o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; rb = o.get("robustness") or {}
entry = {"run_id": rid, "model": "company_mc", "version": o.get("model_version"), "timestamp": rid[:15], "supersedes": "20260924T073336Z-company_mc-e55d7d",
         "spec": "Company_Conditional_Monte_Carlo_Specification_v1.1.3 (Joint_Simulation_Layer_Schema v1.1, Rules v1.1.2; company_mc 2.3.2/2.4.2, parity-gated blend)",
         "calibration": name,
         "purpose": "нормативный прогон переиздания SPCX mc v1.1.3 (партия 7, 25.09): миграция схемы 1.0.1 → 1.0.2 (parity-gated смесь, revenue_bridge_reference_multiple), центры/хвосты/mapping без изменений (check_supersedes: пропаж 0 / изменено 4); валидатор 1.7.0 под Joint v1.1 …-1998a2 pass (MC-G5-013 в норме; intrinsic W 0.396 / full 0.407 — warning ниже ориентира B, как у v1.1.2); migration delta принята как смена семантики (IMMA 3.1/3.3), прежний прогон e55d7d — запись воспроизводимости",
         "equity_value_0_b": round(r["inputs"]["equity_value_0"] / 1e9, 1), "paths": r["inputs"].get("paths") or 500000, "seed": r["seed"],
         "summary": {"median_CAGR_3Y": round(b["return"]["median_CAGR_3Y"], 4), "median_CAGR_5Y": round(b["return"]["median_CAGR_5Y"], 4), "median_CAGR_8Y": round(b["return"]["median_CAGR_8Y"], 4),
                     "CAGR_5Y_q05_q95": [round(q["0.05"], 3), round(q["0.95"], 3)], "P_2x_5Y": round(b["return"]["P_2x_5Y"], 4), "P_loss_gt_30pct_5Y": round(b["downside"]["P_loss_gt_30pct_5Y"], 4),
                     "P_loss_gt_50pct_5Y": round(b["downside"]["P_loss_gt_50pct_5Y"], 4), "ES5": round(b["downside"]["expected_shortfall_5pct_5Y"], 4),
                     "median_equity_value_5Y_b": round(b["median_equity_value_5Y_b"], 1), "RV_Growth_Gap": round(b["gap_metrics"]["RV_Growth_Gap"], 4) if b["gap_metrics"].get("RV_Growth_Gap") is not None else None,
                     "Price_Expectation_Gap": round(b["gap_metrics"]["Price_Expectation_Gap"], 4) if b["gap_metrics"].get("Price_Expectation_Gap") is not None else None,
                     "convergence_stable": (o.get("convergence") or {}).get("stable"), "robustness_pass": rb.get("pass"), "robustness_shares": [rb.get("same_sign_share"), rb.get("within_delta_tolerance_share")]},
         "paths_file": (o.get("paths_file") or "").replace("/data/workspace-invest/", ""), "valuation_crossover": (b.get("valuation_crossover") or {}).get("mode"), "basis_parity_margin_Y5": (b.get("basis_parity_margin") or {}).get("Y5"),
         "positive_fcf_bridge_share_Y5": (b.get("positive_fcf_bridge_share") or {}).get("Y5")}
sp = fd / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); st = json.loads(raw)
idem = dump(st, raw.replace("\r\n", "\n")) == raw.replace("\r\n", "\n")
if rid not in {e.get("run_id") for e in st.get("calc_runs", [])}:
    if not idem:
        changes.append("spacex/state.json: НЕ идемпотентен для дампа — calc_runs НЕ добавлен")
    else:
        changes.append(f"spacex/state.json: +1 calc_runs ({rid}, supersedes e55d7d)")
        if APPLY:
            st.setdefault("calc_runs", []).append(entry)
            st.setdefault("info_log", []).append({"timestamp": NOW, "kind": "calc", "summary": f"Переиздание SPCX mc v1.1.3 (партия 7, 25.09): миграция на схему 1.0.2 принята (check_supersedes OK, валидатор …-1998a2 pass); прежний файл mc_calibration_v1.1.2.yaml снят из папки (from_imma/git); прежний норматив e55d7d — запись воспроизводимости; новый нормативный прогон: {rid}"})
            st["updated"] = NOW
            with open(sp, "w", encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n") as fh:
                fh.write(dump(st, raw.replace("\r\n", "\n")))
for c in changes: print("-", c)
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
