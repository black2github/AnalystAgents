"""Интеграция партии 13 (модели компаний CRWD / HPS.A / S) в workspace (роль интегратора):
1) Theme_Taxonomy v1.0.1 (+ схема, патч-ноты) → methodology/ (валидатор 1.10.1 берёт последнюю версию таксономии);
2) portfolio/hps_a и portfolio/s — новые папки: states/kpis/triggers/mpc_inputs/state.json/theme_exposure + кандидат и досье IMMA;
3) portfolio/crwd — слияние с реестром владельца 17.09 (как NET 21.09): meta владельца (target_weight, strategy_source/date,
   price_at_strategy, status_in_basket), automations и route-степпер сохраняются; legacy-триггеры CRWD-E-01..04 / C-01 остаются под своими
   id (их покрывают автоматизации корзины), триггеры модели CRWD-E-01..10 получают id CRWD-E-05..E-14 (исходный id — в note);
   state.json: legacy pending_verification / notes / owner_decisions / route сохраняются, вектор состояний и kpi_observations — из модели;
4) portfolio/_candidates.yaml: stage candidate → company_model, model_received 2026-10-03 (построчно).
Сухой прогон по умолчанию; --apply — запись. Запуск: python _integrate_party13.py [--apply]"""
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); PK = WS / "from_imma" / "Party13_CRWD_HPSA_S_Company_Models_v1.0"
APPLY = "--apply" in sys.argv; NOW = "2026-10-03T18:10:00Z"; TODAY = "2026-10-03"
DOCS = ("states.yaml", "kpis.yaml", "triggers.yaml", "mpc_inputs.yaml", "state.json", "theme_exposure_v1.0.yaml")
EXTRA = {"crwd": ("CRWD_candidate_v1.0.yaml", "CRWD_Source_Dossier_v1.0.md"), "hps_a": ("HPSA_candidate_v1.0.yaml", "HPSA_Source_Dossier_v1.0.md"), "s": ("S_candidate_v1.0.yaml", "S_Source_Dossier_v1.0.md")}
plan = []


def put(src: Path, dst: Path, how: str = "copy"):
    plan.append((how, str(src.relative_to(WS)) if src.is_relative_to(WS) else str(src), str(dst.relative_to(WS))))
    if APPLY:
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dst)


def write(dst: Path, text: str, how: str):
    plan.append((how, "-", str(dst.relative_to(WS))))
    if APPLY:
        dst.parent.mkdir(parents=True, exist_ok=True); dst.write_text(text, encoding="utf-8", newline="\n")


# 1. таксономия тем 1.0.1
for name in ("Theme_Taxonomy_v1.0.1.yaml", "Theme_Taxonomy_Schema_v1.0.1.yaml", "Theme_Taxonomy_v1.0.1_Patch_Notes.md"):
    put(PK / name, WS / "methodology" / name)
# общие документы партии — в from_imma уже лежат (пакет целиком)

# 2. новые папки hps_a, s
for fd in ("hps_a", "s"):
    for name in DOCS + EXTRA[fd]:
        put(PK / fd / name, WS / "portfolio" / fd / name)

# 3. crwd — слияние
old_t = yaml.safe_load((WS / "portfolio/crwd/triggers.yaml").read_text(encoding="utf-8")); new_t = yaml.safe_load((PK / "crwd/triggers.yaml").read_text(encoding="utf-8"))
legacy_ids = [t["id"] for t in old_t["triggers"]]
n_legacy_e = sum(1 for i in legacy_ids if i.startswith("CRWD-E-"))
merged = dict(new_t)
meta = dict(new_t["meta"])
for k in ("target_weight", "strategy_source", "strategy_date", "price_at_strategy", "status_in_basket", "fiscal_year", "company"):
    if old_t["meta"].get(k) is not None:
        meta[k] = old_t["meta"][k]
meta["status_in_basket"] = f"{old_t['meta'].get('status_in_basket', 'наблюдать')} (реестр корзины 17.09) → candidate (модель компании, партия 13 IMMA 03.10.2026)"
meta["registry_updated"] = TODAY
merged["meta"] = meta
if old_t.get("automations"):
    merged["automations"] = old_t["automations"]
merged["route"] = old_t["route"]                                      # степпер владельца (watch/entry/confirm/hold/exit); конвейер модели — в комментарии шапки
renum = {}
model_triggers = []
for i, t in enumerate(new_t["triggers"], start=1):
    t = dict(t); old_id = t["id"]; new_id = f"CRWD-E-{n_legacy_e + i:02d}"
    renum[old_id] = new_id; t["id"] = new_id
    t["note"] = f"партия 13 IMMA (исходный id {old_id}); legacy-триггеры корзины 17.09 — CRWD-E-01..E-{n_legacy_e:02d}"
    model_triggers.append(t)
legacy_triggers = []
for t in old_t["triggers"]:
    t = dict(t); t.setdefault("note", ""); t["note"] = (t["note"] + "; " if t["note"] else "") + "legacy-реестр корзины 17.09 (до модели компании); условия — owner_judgment"
    t.setdefault("fired", [])
    legacy_triggers.append(t)
merged["triggers"] = legacy_triggers + model_triggers
head = ("# Реестр триггеров: CrowdStrike (CRWD, NASDAQ) — реестр корзины ИИ-инфраструктуры 17.09 (legacy CRWD-E-01..04, C-01) + модель компании\n"
        f"# партии 13 IMMA 03.10.2026 (CRWD-E-{n_legacy_e + 1:02d}..E-{n_legacy_e + len(model_triggers):02d}; исходные id IMMA — в note; source_artifact CRWD_candidate_v1.0.yaml).\n"
        "# Триггер ≠ решение. route — степпер владельца (17.09); конвейер модели: model accepted → dozor verification (PENDING_HOST_RUN) → RV+MC\n"
        "# calibration (следующий заказ IMMA).\n")
write(WS / "portfolio/crwd/triggers.yaml", head + yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, width=1000), "merge")

old_s = json.loads((WS / "portfolio/crwd/state.json").read_text(encoding="utf-8")); new_s = json.loads((PK / "crwd/state.json").read_text(encoding="utf-8"))
st = dict(new_s)
st["source"] = old_s.get("source")
st["owner_decisions"] = old_s.get("owner_decisions") or []
st["pending_verification"] = (old_s.get("pending_verification") or []) + (new_s.get("pending_verification") or [])
st["notes"] = (old_s.get("notes") or []) + (new_s.get("notes") or []) + [f"{TODAY}: модель компании (партия 13 IMMA) встроена в реестр корзины 17.09: legacy-триггеры сохранены, триггеры модели → CRWD-E-{n_legacy_e + 1:02d}..E-{n_legacy_e + len(model_triggers):02d}; KPI сверены хостом с первоисточниками (досье 03.10), дозор-прогон — PENDING_HOST_RUN"]
st["route"] = dict(old_s["route"]); st["route"]["note"] = (old_s["route"].get("note") or "") + " Конвейер модели (партия 13): current=dozor_verification, done=[model] — см. triggers.yaml route.note."
st["info_log"] = (old_s.get("info_log") or []) + (new_s.get("info_log") or [])
st["updated"] = NOW
write(WS / "portfolio/crwd/state.json", json.dumps(st, ensure_ascii=False, indent=2) + "\n", "merge")
for name in ("states.yaml", "kpis.yaml", "mpc_inputs.yaml", "theme_exposure_v1.0.yaml") + EXTRA["crwd"]:
    put(PK / "crwd" / name, WS / "portfolio/crwd" / name)
if (WS / "portfolio/crwd/thesis.md").exists():
    plan.append(("keep", "-", "portfolio/crwd/thesis.md"))

# 4. _candidates.yaml — построчно
cp = WS / "portfolio/_candidates.yaml"; txt = cp.read_text(encoding="utf-8"); lines = txt.split("\n"); changed = 0
for i, ln in enumerate(lines):
    for tk, fd in (("CRWD", "crwd"), ("HPS.A", "hps_a"), ("S", "s")):
        if re.search(rf"^\s*- \{{ticker: {re.escape(tk)},", ln) and "stage: candidate" in ln:
            ln2 = ln.replace("stage: candidate", f'stage: company_model, model_received: "{TODAY}"')
            if tk != "CRWD" and "folder:" not in ln2 and "folder:" not in (lines[i + 1] if i + 1 < len(lines) else ""):
                ln2 = ln2.replace(f"stage: company_model", f"folder: {fd}, stage: company_model")
            lines[i] = ln2; changed += 1
assert changed == 3, f"ожидались 3 строки кандидатов, изменено {changed}"
write(cp, "\n".join(lines), "edit")

for how, src, dst in plan:
    print(f"{how:6} {src} -> {dst}")
print("renumbered:", renum)
print("APPLIED" if APPLY else "DRY RUN (--apply для записи)")
