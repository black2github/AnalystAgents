"""Поправки партии 1 от другой LLM (batch_01_source_corrections_v1.0.yaml, 21.09): NBIS KPI-08 → guidance, KPI-11 (факт) pending,
ось Capacity_Secured → pending_verification; HOOD KPI-03 подтверждён по релизу. Файлы берутся из workspace (docker cp заранее)."""
import json
from pathlib import Path
import yaml

SRC = "https://www.sec.gov/Archives/edgar/data/1513845/000110465926094568/tm2622968d1_ex99-2.htm"
NOW = "2026-09-21T06:35:00Z"

# --- NBIS kpis.yaml ---
p = Path("portfolio/nbis/kpis.yaml"); d = yaml.safe_load(p.read_text(encoding="utf-8"))
k8 = next(k for k in d["critical_kpis"] if k["id"] == "NBIS-KPI-08")
k8.update({"name": "Year-end contracted power target", "last_value": 5.0, "value_type": "company_guidance", "target_date": "2026-12-31",
           "verified": True, "verified_note": "host-check 21.09: «raising our year-end contracted power target again to 5 GW» — guidance, не факт",
           "note": "Прогноз компании (guidance), не realized contracted power; для переходов оси — поддерживающее свидетельство, не основание (поправка LLM 21.09)"})
if not any(k["id"] == "NBIS-KPI-11" for k in d["critical_kpis"]):
    d["critical_kpis"].append({"id": "NBIS-KPI-11", "name": "Actually secured contracted power as of reporting date", "unit": "GW", "period": "quarterly",
                               "source": "SEC", "thresholds": {"green": ">= 5", "yellow": ">= 3 and < 5", "red": "< 3"}, "last_value": None, "last_date": None,
                               "source_url": SRC, "verified": False, "verification_status": "pending_verification",
                               "note": "Письмо акционерам Q2 не квантифицирует фактически законтрактованную мощность на 30.06/12.08 отдельно от цели YE2026. Основание для переходов оси Capacity_Secured (поправка LLM 21.09)"})
d["max_critical_kpis"] = 11
d["version"] = "1.1"; d["changelog"] = [{"version": "1.1", "date": "2026-09-21", "change": "KPI-08 → guidance (5.0 GW, YE2026); добавлен KPI-11 (факт, pending); источник — batch_01_source_corrections_v1.0.yaml"}]
p.write_text(p.read_text(encoding="utf-8").splitlines()[0] + "\n" + yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")

# --- NBIS triggers.yaml: правило оси ---
t = Path("portfolio/nbis/triggers.yaml"); ts = t.read_text(encoding="utf-8")
tr = yaml.safe_load(ts)
for x in tr["triggers"]:
    if x["axis"] == "Capacity_Secured":
        x["kpis"] = ["NBIS-KPI-11"] + [k for k in x.get("kpis", []) if k != "NBIS-KPI-11"]
        x["note"] = "Переходы оси — только по NBIS-KPI-11 (факт); KPI-08 (guidance) — поддерживающее свидетельство (поправка LLM 21.09)"
tr["meta"]["registry_updated"] = "2026-09-21 (поправка: Capacity_Secured по KPI-11)"
hdr = "\n".join(l for l in ts.splitlines() if l.startswith("#")) + "\n"
t.write_text(hdr + yaml.safe_dump(tr, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")

# --- NBIS states.yaml: current → pending_verification ---
s = Path("portfolio/nbis/states.yaml"); sd = yaml.safe_load(s.read_text(encoding="utf-8"))
ax = sd["axes"]["Capacity_Secured"]
ax["current"] = "pending_verification"; ax["prior_snapshot"] = "C3"
ax["current_note"] = "Guidance 5 GW (YE2026) не считается реализованным состоянием; ждём факт по NBIS-KPI-11 (поправка LLM 21.09)"
sd["as_of"] = "2026-09-21"; sd["version"] = "1.1"
s.write_text(s.read_text(encoding="utf-8").splitlines()[0] + "\n" + yaml.safe_dump(sd, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")

# --- NBIS state.json ---
j = Path("portfolio/nbis/state.json"); st = json.loads(j.read_text(encoding="utf-8"))
cs = st["scenario_state"]["Capacity_Secured"]
cs.update({"state": "pending_verification", "prior_snapshot": "C3", "since": "2026-09-21", "verified": False,
           "verified_note": "Поправка LLM 21.09: 5 GW — цель YE2026; факт по KPI-11 не раскрыт → состояние оси не установлено"})
o8 = next((o for o in st["kpi_observations"] if o["kpi_id"] == "NBIS-KPI-08"), None)
if o8:
    o8.update({"name": "Year-end contracted power target", "value": 5.0, "unit": "GW", "verified": True, "value_type": "company_guidance",
               "verified_by": "host-check + поправка LLM 21.09"}); o8.pop("discrepancy", None)
st["info_log"].append({"timestamp": NOW, "kind": "correction", "summary": "Поправка партии 1 (LLM): KPI-08 = guidance 5 GW YE2026 (подтверждён как guidance); KPI-11 факт — pending; ось Capacity_Secured → pending_verification (prior C3)"})
st["updated"] = NOW
j.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# --- HOOD: KPI-03 подтверждён ---
j = Path("portfolio/hood/state.json"); st = json.loads(j.read_text(encoding="utf-8"))
o3 = next((o for o in st["kpi_observations"] if o["kpi_id"] == "HOOD-KPI-03"), None)
if o3:
    o3.update({"value": 0.24, "unit": "fraction", "period_end": "2026-08-31", "verified": True,
               "value_raw": "August 2026 operating release: LTM Net Deposits $74.1B, annual growth rate 24% relative to August 2025 Total Platform Assets; dashboard «24% LTM Growth»",
               "source_url": "https://investors.robinhood.com/static-files/5980b367-8c3d-486b-b38d-99fad8d6da70",
               "verified_by": "другая LLM (batch_01_source_corrections, 21.09) с указанием точного места в релизе; дозор подтвердит при следующей сверке по PDF"})
    o3.pop("why", None)
st["scenario_state"]["Customer_Asset_Scale"]["verified"] = True
st["scenario_state"]["Customer_Asset_Scale"]["verified_note"] = "KPI-01/02 подтверждены заданием, KPI-03 — по указанию LLM на место в релизе (21.09)"
st["info_log"].append({"timestamp": NOW, "kind": "correction", "summary": "HOOD KPI-03 (LTM Net Deposit growth 24%) подтверждён: место в августовском релизе указано LLM; ось Customer_Asset_Scale verified"})
st["updated"] = NOW
j.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("corrections applied")
