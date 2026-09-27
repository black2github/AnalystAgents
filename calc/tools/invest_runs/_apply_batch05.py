"""Партия 5 (кроме CRWV-конвертации, сделана _apply_batch.py): таксономия v1.1 → 14 mpc_inputs.yaml (SPCX — новый файл);
ASTS semantics patch v1.1; CRWV benchmark-блок; _portfolio.yaml → AI_COMPUTE_BASKET_V1 + ref CRWV; _candidates → CRWV company_model;
пометка в MPC Schema v1.0 о таксономии v1.1. Перед запуском: docker cp mpc_inputs.yaml 13 папок и asts states/kpis/triggers/state.json."""
import json
from pathlib import Path
import yaml

D = Path("C:/Users/alexe/Downloads"); TODAY = "2026-09-21"
SHARE = "https://chatgpt.com/share/6ab134dd-6b98-83eb-aa2d-7aaebb521909"
def dump(o): return yaml.safe_dump(o, allow_unicode=True, sort_keys=False, width=120)
def hdr(path):
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("#")) + "\n"

FOLDER = {"SPCX": "spacex", "NBIS": "nbis", "NVDA": "nvda", "HOOD": "hood", "LLY": "lly", "META": "meta", "ASML": "asml", "RKLB": "rklb",
          "MSFT": "msft", "NET": "net", "PLTR": "pltr", "ETN": "etn", "ASTS": "asts", "CRWV": "crwv"}

# 1. таксономия v1.1 → mpc_inputs.yaml
patch = yaml.safe_load((D / "MPC_driver_exposure_patch_v1.1.yaml").read_text(encoding="utf-8"))
tax = yaml.safe_load((D / "MPC_Driver_Taxonomy_v1.1.yaml").read_text(encoding="utf-8"))
new_ids = [x["id"] for x in tax["drivers"]["added_v1_1"]]
for tk, pt in patch["patches"].items():
    add = pt["add"]; assert set(add) == set(new_ids), tk
    p = Path("portfolio") / FOLDER[tk] / "mpc_inputs.yaml"
    if p.exists():
        h = hdr(p); m = yaml.safe_load(p.read_text(encoding="utf-8"))
        vec = m["driver_exposure_vector"]
        for k, v in add.items():
            assert k not in vec, (tk, k)
            vec[k] = v
        m["driver_taxonomy_version"] = "1.1"
        m.setdefault("changelog", []).append({"date": TODAY, "change": f"taxonomy v1.1: добавлено {len(add)} драйверов (MPC_driver_exposure_patch_v1.1, share {SHARE})"})
        p.write_text(h + dump(m), encoding="utf-8")
    else:  # SPCX — модели MPC v1.0 у SPCX не было
        assert tk == "SPCX"
        m = {"version": "0.1", "ticker": tk, "artifact": "mpc_inputs", "as_of": TODAY, "driver_taxonomy_version": "1.1",
             "source_artifact": f"inbox/received/MPC_driver_exposure_patch_v1.1.yaml (другая LLM, {TODAY})",
             "status": "incomplete",
             "gap": "Вектор v1.0 (16 драйверов), failure_modes и driver_interpretation для SPCX не выдавались (модель SPCX предшествует MPC). Заказать у LLM.",
             "driver_exposure_vector": dict(add), "failure_modes": []}
        p.write_text(f"# Входы MPC для {tk}: НЕПОЛНЫЕ — только 16 драйверов таксономии v1.1 из патча; v1.0-вектор и failure modes не выдавались.\n" + dump(m), encoding="utf-8")
    print("mpc", tk, "ok")

# 2. пометка в MPC Schema v1.0 (файл LLM не переписываем — только заголовочный комментарий)
sch = Path("methodology/Marginal_Portfolio_Contribution_Schema_v1.0.yaml"); ss = sch.read_text(encoding="utf-8")
note = "# ВНИМАНИЕ: раздел driver_taxonomy (16 драйверов v1.0) заменён methodology/MPC_Driver_Taxonomy_v1.1.yaml (32 драйвера, additive, 21.09.2026); схема сохранена как v1.0.\n"
if not ss.startswith("# ВНИМАНИЕ"):
    sch.write_text(note + ss, encoding="utf-8")

# 3. ASTS semantics patch v1.1
ap = yaml.safe_load((D / "ASTS_source_semantics_patch_v1.1.yaml").read_text(encoding="utf-8"))
sp = Path("portfolio/asts/states.yaml"); h = hdr(sp); sd = yaml.safe_load(sp.read_text(encoding="utf-8"))
sd["axes"]["Regulatory_Spectrum"].update(ap["states_patch"]["Regulatory_Spectrum"])
sd["version"] = "1.1"; sd["changelog"] = [{"date": TODAY, "change": "Regulatory_Spectrum: evidence_type qualitative_primary_source + verification_rule через ASTS-KPI-11 (patch v1.1)"}]
sp.write_text(h + dump(sd), encoding="utf-8")
kp = Path("portfolio/asts/kpis.yaml"); h = hdr(kp); kd = yaml.safe_load(kp.read_text(encoding="utf-8"))
for pk in ap["kpis_patch"]:
    ex = next((k for k in kd["critical_kpis"] if k["id"] == pk["id"]), None)
    e = {"id": pk["id"], "name": pk["name"], "unit": pk.get("unit"), "period": pk.get("period"), "source": "SEC" if "sec.gov" in pk.get("source", "") else "IR",
         "thresholds": pk.get("zones"), "last_value": pk.get("current_value"), "last_date": "2026-08-12" if pk["id"] == "ASTS-KPI-11" else None, "source_url": pk.get("source"),
         "verified": False, "note": pk.get("note"), "formula": pk.get("formula"), "observation_window_days": pk.get("observation_window_days")}
    e = {k: v for k, v in e.items() if v is not None}
    if ex:
        keep_thr = ex.get("thresholds"); keep_date = ex.get("last_date"); keep_ver = ex.get("verified")
        ex.clear(); ex.update(e); ex.setdefault("thresholds", keep_thr); ex.setdefault("last_date", keep_date)
        ex["verified"] = keep_ver if pk["id"] == "ASTS-KPI-02" else False  # значение 6 уже подтверждено; сменилась только формулировка периода
    else:
        kd["critical_kpis"].append(e)
kd["max_critical_kpis"] = 11; kd["version"] = "1.1"
kd["changelog"] = [{"date": TODAY, "change": "KPI-02 переименован (окно 50 дней по источнику); добавлен KPI-11 (бинарный статус FCC-авторизации) — patch v1.1"}]
kp.write_text(h + dump(kd), encoding="utf-8")
tp = Path("portfolio/asts/triggers.yaml"); h = hdr(tp); td = yaml.safe_load(tp.read_text(encoding="utf-8"))
for tid, tpatch in ap["triggers_patch"].items():
    t = next(x for x in td["triggers"] if x["id"] == tid); t.update(tpatch); t["notes"] = "patch v1.1: условие переведено на ASTS-KPI-11"
td["meta"]["registry_updated"] = f"{TODAY} (patch v1.1: E-08 по KPI-11)"
tp.write_text(h + dump(td), encoding="utf-8")
j = Path("portfolio/asts/state.json"); st = json.loads(j.read_text(encoding="utf-8"))
st["scenario_state"]["Regulatory_Spectrum"]["evidence_type"] = "qualitative_primary_source"
st["scenario_state"]["Regulatory_Spectrum"]["verified_note"] = "patch v1.1: подтверждение оси — через ASTS-KPI-11 (бинарный статус FCC), ждёт сверки"
for o in st["kpi_observations"]:
    if o["kpi_id"] == "ASTS-KPI-02": o["name"] = "Spacecraft launched within disclosed 50-day window"; o["observation_window_days"] = 50
st["info_log"].append({"timestamp": f"{TODAY}T09:00:00Z", "kind": "correction", "summary": "ASTS patch v1.1: KPI-02 окно 50 дней (по источнику), KPI-11 FCC-статус добавлен (не сверен), Regulatory_Spectrum — qualitative_primary_source"})
st["updated"] = f"{TODAY}T09:00:00Z"
j.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# 4. CRWV: benchmark-блок из файла LLM → mpc_inputs (ссылка), thesis
cd = yaml.safe_load((D / "CRWV_company_state_v1.0.yaml").read_text(encoding="utf-8"))
cp = Path("portfolio/crwv/mpc_inputs.yaml"); h = hdr(cp); cm = yaml.safe_load(cp.read_text(encoding="utf-8"))
cm["benchmark"] = cd["benchmark"]; cp.write_text(h + dump(cm), encoding="utf-8")

# 5. _portfolio.yaml: AI_COMPUTE benchmark + ref CRWV
pp = Path("portfolio/_portfolio.yaml"); s = pp.read_text(encoding="utf-8")
old = '''      benchmark_id: none
      status: no_external_benchmark_v1
      decided_by: "другая LLM (партия 1, 21.09.2026), владелец согласен"
      reason: "экономика GPU-облаков не представлена ни IGV, ни полупроводниковыми индексами, ни широкими AI-ETF; до методологии AI_COMPUTE_BASKET сектор вне покрытия"
'''
assert s.count(old) == 1
s = s.replace(old, '''      benchmark_id: AI_COMPUTE_BASKET_V1
      type: internal_synthetic_basket           # NBIS 50% + CRWV 50%, равные веса, квартальная ребалансировка, chain-link
      methodology_ref: methodology/AI_COMPUTE_Sector_Benchmark_Specification_v1.0.md
      definition_ref: methodology/AI_COMPUTE_Benchmark_v1.0.yaml
      engine_model: synthetic_basket            # invest-calc: индекс по adjusted close Yahoo chart
      benchmark_quality: provisional_low_breadth   # 2 компонента; полное качество — от 4
      benchmark_coverage: true
      approved: "2026-09-21 (партия 5 другой LLM); прежнее решение v1 «внешнего benchmark нет» заменено"
      concentration_override: {stress_floor: "вес AI_COMPUTE >= 20% NAV И просадка <= -25% → режим не мягче Stress", shock_floor: "вес >= 25% И просадка <= -40% → не мягче Shock", provenance: model_assumption, no_double_count: true}
''')
tail = "      target: {weight: null, target_version: null, effective_from: null}\n"
key = "    - ticker: CRWV\n      account: P2\n"; assert key in s
i = s.index(tail, s.index(key)) + len(tail)
if "portfolio/crwv/states.yaml" not in s:
    s = s[:i] + "      state_vector_ref: portfolio/crwv/states.yaml\n      company_rules_ref: portfolio/crwv/triggers.yaml\n" + s[i:]
pp.write_text(s, encoding="utf-8"); yaml.safe_load(s)

# 6. _candidates.yaml
c = Path("portfolio/_candidates.yaml"); cs = c.read_text(encoding="utf-8")
i = cs.index("  - {ticker: CRWV,"); jx = cs.index("\n", i); line = cs[i:jx]
assert "stage: candidate" in line
cs = cs[:i] + line.replace("stage: candidate", 'stage: company_model, model_received: "2026-09-21"') + cs[jx:]
c.write_text(cs, encoding="utf-8"); yaml.safe_load(cs)
print("batch05 applied")
