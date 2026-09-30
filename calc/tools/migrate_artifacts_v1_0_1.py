"""Детерминированная миграция артефактов компаний workspace к Company Artifact Schema v1.0.x (текущая цель — SCHEMA_VERSION; инструмент 1.1.0)
(MIG-101…111 из Company_Artifact_Schema_v1.0.1.yaml + §7 IMA_Schema_Party_1; принято владельцем 22.09.2026;
MIG-121/122 из Company_Artifact_Schema_v1.0.5.yaml — история прогонов дозора у наблюдений, 23.09.2026).

Инварианты (проверяются при каждом запуске, при нарушении файл НЕ пишется):
  И1. Семантическая нейтральность: ни один канонический ID, состояние оси, условие триггера, значение KPI (число) не
      меняются — меняются только форма (строка «>40» → 40 + observation_qualifier) и добавляются обязательные поля.
  И2. Текст патчится построчно (ruamel даёт номера строк), без переформатирования: комментарии, кавычки, порядок ключей,
      переводы строк (CRLF/LF) сохраняются. Результат построчного патча обязан быть РАВЕН эталонной миграции в памяти
      (`migrate_docs`) — иначе отказ.
  И3. Идемпотентность: повторный запуск не меняет ни одного файла.
  И4. Файл пишется только если изменился.
Использование (хост, системный Python + ruamel.yaml + pyyaml):
  python calc/tools/migrate_artifacts_v1_0_1.py <workspace> [--apply] [--only nbis,nvda]   (без --apply — сухой прогон)
Не мигрируются: папки без triggers.yaml, каталоги `_*`.

Версия инструмента 1.1.0 (30.09.2026) — профиль legacy spacex (MIG-SPCX). Папка portfolio/spacex написана до Artifact Schema
v1.0.x и до 1.1.0 пропускалась. Для неё ПЕРЕД общими правилами MIG-1xx применяется профиль; каждое правило — одно
преобразование формы, значение берётся из указанного места; И1–И4 действуют и для профиля (патч сверяется с эталоном
spcx_migrate_docs). Поля старого формата, которым в схеме нет места, переносятся ДОСЛОВНО (текст, комментарии) в
portfolio/spacex/_legacy/<файл> (вне валидируемых пяти), в исходнике — комментарий-ссылка; существующий _legacy не перезаписывается.
  MIG-SPCX-01 schema_version '1.0.5' во всех пяти файлах — общим правилом (вставка перед первым ключом, как у nbis).
  states.yaml:
  MIG-SPCX-02 states[*].definition → criteria (переименование ключа в той же строке, текст критерия дословно; criteria в
              схеме — строка, структуры нет).
  MIG-SPCX-03 оси: current = current_snapshot.state (иначе state.json → scenario_state[ось].state); current_evidence =
              current_snapshot.evidence (дословно); source_refs = ключи sources для URL из current_snapshot.source (текст без
              URL источником не становится, пустой список допустим); current_snapshot и transition_triggers → _legacy
              (условия переходов живут только в triggers.yaml; сверка transition_triggers ↔ triggers.yaml — в отчёте, триггеры
              не создаются).
  MIG-SPCX-04 sources (обязателен): по одному ключу <TICKER>_<вид> на URL снимков осей; source_class — spcx_source_class,
              as_of — states.as_of (как в MIG-102).
  MIG-SPCX-05 корневые source_policy, transition_semantics, evaluation_rule, legacy_compatibility → _legacy (свободного
              текстового ключа в схеме states.yaml нет; semantics добавляет общее правило).
  kpis.yaml:
  MIG-SPCX-06 zone_semantics.thresholds_provenance = model_assumption (обязательное поле, const схемы).
  MIG-SPCX-07 у KPI: value_type = actual (прогнозов компании среди KPI нет; name/formula с guidance/прогноз — в отчёт как
              неоднозначные); source_class — spcx_source_class(source_url); verified = null (дозор не проверял);
              provenance = derived_fact при арифметической формуле с делением, иначе verified_fact.
  MIG-SPCX-08 notes → note (переименование); last_value_raw → note «last_value_raw: <значение>», если note ещё нет, иначе
              → _legacy; last_yoy_growth, last_yoy_change, inputs → _legacy (critical_kpis.<id>).
  MIG-SPCX-09 корневые derived_checks, data_quality, kpi_observation_rule, supporting_metrics, calculated_metrics → _legacy.
  triggers.yaml:
  MIG-SPCX-10 strategy_ref, probability_in_strategy, notes_kpi, supporting_metrics, calculated_metrics → _legacy (triggers.<id>).
  MIG-SPCX-11 transition: null — это не переход: ключ удаляется (axis сохраняется), список — в отчёт.
  MIG-SPCX-12 meta: reference_price_in_strategy, target_average_price, position_plan → _legacy; yahoo_symbol — из
              meta.price_source (…/chart/<SYMBOL>); exchange — NASDAQ, если в state.json.events_reported есть включение в
              Nasdaq-100 с источником ir.nasdaq.com (иначе отказ: биржа не выдумывается).
  MIG-SPCX-13 automations: pilot → _legacy; covers-строка «E-10..E-19, …» → явный список ID (раскрытие диапазонов), исходная
              строка — в note той же записи.
  mpc_inputs.yaml:
  MIG-SPCX-14 semantics → driver_exposure_semantics (driver_scale → scale, rule → direction_rule; иные ключи — отказ).
  MIG-SPCX-15 methodology_refs, status, model_notes → _legacy; driver_vector_provenance = model_assumption с комментарием
              о переносе экспертной оценки v1.0.
  state.json (файл дамп-идемпотентен → пишется дампом эталона):
  MIG-SPCX-16 kpi_observations: provenance — как у KPI с тем же kpi_id (MIG-SPCX-07); verified не меняется; run_id (прогон
              invest-calc, не дозора — verification_run_id из него не делается) → note «run_id: …».
  MIG-SPCX-17 info_log старой формы: summary = text (дословно), kind — прежний или legacy_trigger_log; trigger_id, level → _legacy.
  MIG-SPCX-18 scenario_state[ось].verified = false (+ verified_note): схема требует boolean, протокольной проверки не было.
  MIG-SPCX-19 calc_inputs, gaap_profit_quarters → _legacy/state_legacy.json.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import io
import json
import re
import sys
from pathlib import Path

import yaml

SCHEMA_VERSION = "1.0.5"  # цепочка патчей v1.0.1 → v1.0.2 (MIG-112/113) → v1.0.3 (MIG-114/115) → v1.0.4 (MIG-117) → v1.0.5 (MIG-121/122)
FILES = ["states.yaml", "kpis.yaml", "triggers.yaml", "mpc_inputs.yaml", "state.json"]
TOOL_VERSION = "1.1.0"  # 1.1.0 — профиль legacy spacex (MIG-SPCX-01…19); SCHEMA_VERSION цели не меняется
SKIP_FOLDERS: set[str] = set()  # до 1.1.0 здесь был spacex («старый формат, отдельное решение») — решение: профиль MIG-SPCX
SPCX_FOLDERS = {"spacex"}      # папки, к которым перед общими правилами применяется профиль MIG-SPCX
LEGACY_QUALIFIERS = ("lower_bound", "upper_bound", "approximate")


# ----------------------------------------------------------------------------------------------- общие функции
def norm_dates(o):
    if isinstance(o, dict):
        return {k: norm_dates(v) for k, v in o.items()}
    if isinstance(o, list):
        return [norm_dates(v) for v in o]
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    return o


def load_plain(p: Path):
    text = p.read_text(encoding="utf-8")
    return norm_dates(json.loads(text) if p.suffix == ".json" else yaml.safe_load(text))


def source_class(url: str | None, label: str | None) -> str:
    """Класс источника по домену/типу документа (правило миграции MIG-102/103 до Source Policy v1.0)."""
    u = (url or "").lower()
    t = (label or "").lower()
    if "yahoo" in u or "yahoo" in t:
        return "market_data_provider"
    if "transcript" in u or "transcript" in t or "call" in t:
        return "issuer_transcript"
    if "presentation" in u or "presentation" in t or "slides" in t:
        return "issuer_investor_presentation"
    if "sec.gov" in u:
        return "issuer_ir_release" if re.search(r"ex[-_]?99|_pr\.|press", u) else "regulatory_filing"
    if t == "sec" or any(x in t for x in ("10-q", "10-k", "6-k", "20-f")):
        return "regulatory_filing"
    if u or t:
        return "issuer_ir_release"
    return "other_primary"


def split_value(v):
    """Нормализация значения (MIG-105, §7): → (число|None, доп. поля)."""
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return None, {"observation_qualifier": "range", "value_range": {"min": v[0], "max": v[1]}}
    if isinstance(v, str):
        m = re.fullmatch(r"\s*([<>]=?)\s*([-+]?\d+(?:\.\d+)?)\s*", v)
        if m:
            num = float(m.group(2))
            num = int(num) if num.is_integer() and "." not in m.group(2) else num
            return num, {"observation_qualifier": "lower_bound" if m.group(1).startswith(">") else "upper_bound"}
        m = re.fullmatch(r"\s*~\s*([-+]?\d+(?:\.\d+)?)\s*", v)
        if m:
            return float(m.group(1)), {"observation_qualifier": "approximate"}
    return v, {}


def _is_binary_zone(s) -> bool:
    return bool(re.fullmatch(r"\s*=?\s*(1|0|true|false|yes|no)\s*", str(s), re.I))


# ----------------------------------------------------------------------------------------------- эталон: миграция словарей
def migrate_kpi_like(k: dict, val_key: str) -> None:
    v, extra = split_value(k.get(val_key))
    k[val_key] = v
    for kk, vv in extra.items():
        k.setdefault(kk, vv)
    vt = k.get("value_type")
    if vt in LEGACY_QUALIFIERS:
        k.setdefault("observation_qualifier", vt)
        k["value_type"] = "actual"
    elif vt is None:
        k["value_type"] = "actual"
    k.setdefault("provenance", "verified_fact")


def _obs_key(o: dict) -> tuple:
    """Тождество наблюдения (Artifact Schema v1.0.5, ART-REF-031): kpi_id + period_end + нормализованные value/value_range."""
    return (o.get("kpi_id"), o.get("period_end"), json.dumps(_num(o.get("value")), sort_keys=True), json.dumps(_num(o.get("value_range")), sort_keys=True))


def _num(v):
    """Числа к float (3 и 3.0 — одно наблюдение); bool и остальное — как есть."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return {k: _num(x) for k, x in v.items()}
    return v


def _run_ids(o: dict) -> list[str]:
    ids = list(o.get("verification_run_ids") or [])
    if o.get("verification_run_id") and o["verification_run_id"] not in ids:
        ids.append(o["verification_run_id"])
    return ids


def migrate_observations(obs: list[dict], reports: list[dict] | None) -> list[dict]:
    """MIG-122 (Company_Artifact_Schema_v1.0.5, принята 23.09.2026): история прогонов у наблюдений.
    1) дубликаты по тождеству наблюдения схлопываются в одну строку (ART-REF-031): остаётся строка, привязанная к прогону
       (verification_run_id), недостающие поля добираются из строки-дубликата; значение и период у них равны по построению;
    2) verification_run_ids сеется из verification_run_id;
    3) более ранние прогоны восстанавливаются ТОЛЬКО из иммутабельных отчётов _verify/*.json: run_id отчёта добавляется
       наблюдению, если в отчёте есть item с тем же kpi_id, runtime_verified=true и candidate.last_value/value_range,
       равными значению наблюдения (детерминированная связь; иначе история не выдумывается);
    4) список упорядочен по метке времени в run_id, verification_run_id = последний (ART-REF-030)."""
    out: list[dict] = []
    index: dict[tuple, int] = {}
    for o in obs:
        k = _obs_key(o)
        if k not in index:
            index[k] = len(out)
            out.append(dict(o))
            continue
        kept = out[index[k]]
        winner, other = (o, kept) if (o.get("verification_run_id") and not kept.get("verification_run_id")) else (kept, o)
        merged = dict(winner)
        for kk, vv in other.items():
            merged.setdefault(kk, vv)
        ids = _run_ids(kept)
        ids += [r for r in _run_ids(o) if r not in ids]
        if ids:
            merged["verification_run_ids"] = ids
        out[index[k]] = merged
    for o in out:
        ids = _run_ids(o)
        for r in reports or []:
            rid = r.get("run_id")
            if not rid or rid in ids:
                continue
            for it in r.get("items") or []:
                c = it.get("candidate") or {}
                if it.get("kpi_id") == o.get("kpi_id") and it.get("runtime_verified") is True \
                        and c.get("last_value") == o.get("value") and (c.get("value_range") or None) == (o.get("value_range") or None):
                    ids.append(rid)
                    break
        if ids:
            ids.sort(key=lambda s: s.rsplit("-", 1)[-1])  # verify-<TK>-<YYYYMMDDTHHMMSSZ>: метка времени в конце
            o["verification_run_ids"] = ids
            o["verification_run_id"] = ids[-1]
    return out


def load_verify_reports(folder: Path) -> list[dict]:
    """Иммутабельные отчёты дозора папки, по возрастанию имени файла (вход MIG-122)."""
    d = folder / "_verify"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []


def migrate_docs(docs: dict, reports: list[dict] | None = None) -> dict:
    """Эталонная миграция в памяти (словари после load_plain). Возвращает новые словари; вход не меняется.
    reports — отчёты _verify/*.json папки для MIG-122 (без них история сеется только из verification_run_id)."""
    docs = copy.deepcopy(docs)
    full = all(fn in docs for fn in ("states.yaml", "kpis.yaml", "mpc_inputs.yaml"))
    for d in docs.values():
        d["schema_version"] = SCHEMA_VERSION
    st = docs.get("states.yaml")
    if st:
        sem = st.setdefault("semantics", {})
        if "numeric_thresholds_provenance" not in sem:
            sem["numeric_thresholds_provenance"] = sem.pop("thresholds_provenance", None) or "model_assumption"
        else:
            sem.pop("thresholds_provenance", None)
        sem.setdefault("evidence_required", True)
        sem.setdefault("pending_verification_blocks_transition", True)
        sem.setdefault("trigger_not_decision", True)
        src = st.get("sources") or {}
        for key, val in list(src.items()):
            val = {"url": val} if isinstance(val, str) else dict(val)
            val.setdefault("source_class", source_class(val.get("url"), val.get("type") or key))
            val.setdefault("as_of", st.get("as_of"))
            src[key] = val
    kp = docs.get("kpis.yaml")
    if kp:
        for k in kp.get("critical_kpis", []):
            k.setdefault("source_class", source_class(k.get("source_url"), k.get("source")))
            migrate_kpi_like(k, "last_value")
            th = k.get("thresholds") or {}
            if "yellow" not in th and set(th) >= {"green", "red"} and _is_binary_zone(th["green"]) and _is_binary_zone(th["red"]):
                th["binary"] = True  # MIG-106: только когда зоны бинарны по форме
    tr = docs.get("triggers.yaml")
    if tr:
        tr.setdefault("profile", "full_model" if full else "registry_only")
        au = tr.get("automations")
        if isinstance(au, dict) and "_note" in au:
            tr["automations_note"] = au.pop("_note")
        for t in tr.get("triggers", []):
            if "transition" in t:
                t.setdefault("condition_provenance", "model_assumption")
            if tr["profile"] == "full_model":
                t.setdefault("fired", [])
        if tr["profile"] == "full_model":
            if "rules" not in tr and st:
                tr["rules"] = {k: st["semantics"][k] for k in ("evidence_required", "pending_verification_blocks_transition", "trigger_not_decision")}
            meta = tr.setdefault("meta", {})
            sj = docs.get("state.json") or {}
            meta.setdefault("source_artifact", (kp or {}).get("source_artifact"))
            meta.setdefault("price_source", (sj.get("price") or {}).get("source") or "Yahoo Finance chart (дозор)")
            meta.setdefault("price_at_registry", (sj.get("price") or {}).get("last"))
            meta.setdefault("position", None)
        meta = tr.get("meta") or {}
        if isinstance(meta.get("horizon"), int):
            meta["horizon"] = str(meta["horizon"])
    mp = docs.get("mpc_inputs.yaml")
    if mp:
        mp.setdefault("driver_vector_provenance", "model_assumption")
    sj = docs.get("state.json")
    if sj:
        for o in sj.get("kpi_observations", []) or []:
            migrate_kpi_like(o, "value")
        sj["kpi_observations"] = migrate_observations(sj.get("kpi_observations") or [], reports)  # MIG-122
        if isinstance(sj.get("conviction"), dict):
            sj["conviction"].setdefault("provenance", "owner_judgment")
        if isinstance(sj.get("notes"), str):
            sj["notes"] = [sj["notes"]]
        elif sj.get("notes") is None:
            sj["notes"] = []
        for key in ("fired", "events_reported", "pending_verification", "info_log", "state_transitions", "kpi_observations", "calc_runs"):
            sj.setdefault(key, [])
        sj.setdefault("scenario_state", {})
    return docs


# ----------------------------------------------------------------------------------------------- построчный патч YAML
def _q(s) -> str:
    """Скаляр для вставки в YAML: числа/bool/null как есть, строки — в одинарных кавычках."""
    if s is None:
        return "null"
    if isinstance(s, bool):
        return "true" if s else "false"
    if isinstance(s, (int, float)):
        return repr(s)
    return "'" + str(s).replace("'", "''") + "'"


class _Patch:
    """Накопитель строковых правок; применяется снизу вверх, чтобы номера строк не плыли."""

    def __init__(self, lines: list[str]):
        self.lines = lines
        self.ops: list[tuple[int, int, list[str]]] = []  # (start, end_exclusive, new_lines)

    def insert_after(self, idx: int, new: list[str]):
        self.ops.append((idx + 1, idx + 1, new))

    def insert_before(self, idx: int, new: list[str]):
        self.ops.append((idx, idx, new))

    def replace(self, start: int, end: int, new: list[str]):
        self.ops.append((start, end, new))

    def append(self, new: list[str]):
        n = len(self.lines)
        while n > 0 and not self.lines[n - 1].strip():
            n -= 1
        self.ops.append((n, n, new))

    def apply(self) -> list[str]:
        out = list(self.lines)
        for start, end, new in sorted(self.ops, key=lambda o: (o[0], o[1]), reverse=True):
            out[start:end] = new
        return out


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _value_end(lines: list[str], key_idx: int, key_col: int) -> int:
    """Конец (исключительно) значения ключа в блочном отображении: строки глубже key_col или список «- » на той же колонке."""
    i = key_idx + 1
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        ind = _indent(ln)
        if ind > key_col or (ind == key_col and ln[key_col:].startswith("- ")):
            i += 1
            continue
        break
    return i


def _block_end(lines: list[str], key_idx: int, key_col: int) -> int:
    """Конец блока значения без хвостовых пустых строк."""
    e = _value_end(lines, key_idx, key_col)
    while e > key_idx + 1 and not lines[e - 1].strip():
        e -= 1
    return e


def _keyline(lines, cm, key) -> tuple[int, int]:
    ln, col, _, _ = cm.lc.data[key]
    assert re.match(r"\s*(- )?" + re.escape(str(key)) + r"\s*:", lines[ln]), (key, lines[ln])
    return ln, col


def patch_yaml(fn: str, raw: str, ctx: dict) -> str:
    """Построчная миграция одного YAML-файла. ctx: {"full": bool, "states": dict|None, "kpis": dict|None, "state": dict|None}."""
    from ruamel.yaml import YAML

    y = YAML()
    y.preserve_quotes = True
    doc = y.load(raw)
    lines = raw.split("\n")
    P = _Patch(lines)
    top_keys = list(doc.keys())
    first_ln = min(doc.lc.data[k][0] for k in top_keys)
    head = []  # верхние ключи, вставляемые перед первым ключом файла
    if "schema_version" not in doc:
        head.append(f"schema_version: '{SCHEMA_VERSION}'")
    elif str(doc["schema_version"]) != SCHEMA_VERSION:  # bump версии (MIG-112/114): та же строка, кавычки как были
        vln, _ = _keyline(lines, doc, "schema_version")
        q = "'" if "'" in lines[vln] else ('"' if '"' in lines[vln] else "")
        P.replace(vln, vln + 1, [f"{' ' * _indent(lines[vln])}schema_version: {q}{SCHEMA_VERSION}{q}"])

    if fn == "states.yaml":
        sem = doc.get("semantics")
        if sem is not None:
            sln, scol = _keyline(lines, doc, "semantics")
            assert lines[sln].rstrip().endswith(":"), "semantics должен быть блочным отображением"
            child_col = _indent(lines[sln + 1])
            add = []
            if "numeric_thresholds_provenance" not in sem:
                if "thresholds_provenance" in sem:
                    tln, _ = _keyline(lines, sem, "thresholds_provenance")
                    P.replace(tln, tln + 1, [lines[tln].replace("thresholds_provenance:", "numeric_thresholds_provenance:", 1)])
                else:
                    add.append(" " * child_col + "numeric_thresholds_provenance: model_assumption")
            elif "thresholds_provenance" in sem:
                tln, tcol = _keyline(lines, sem, "thresholds_provenance")
                P.replace(tln, _value_end(lines, tln, tcol), [])
            for k, v in (("evidence_required", True), ("pending_verification_blocks_transition", True), ("trigger_not_decision", True)):
                if k not in sem:
                    add.append(" " * child_col + f"{k}: {_q(v)}")
            if add:
                P.insert_after(sln, add)
        else:
            head.append("semantics:")
            head += ["  evidence_required: true", "  pending_verification_blocks_transition: true", "  trigger_not_decision: true", "  numeric_thresholds_provenance: model_assumption"]
        src = doc.get("sources") or {}
        as_of = doc.get("as_of")
        for key, val in src.items():
            kln, kcol = _keyline(lines, src, key)
            if isinstance(val, str):
                m = re.match(r"^(\s*)([^:\s]+):\s+(.+?)\s*$", lines[kln])
                assert m and m.group(3) == val, ("источник-строка", lines[kln])
                ind = " " * (kcol + 2)
                P.replace(kln, kln + 1, [f"{' ' * kcol}{key}:", f"{ind}source_class: {source_class(val, key)}", f"{ind}url: {val}", f"{ind}as_of: {_q(norm_dates(as_of))}"])
            else:
                child_col = _indent(lines[kln + 1])
                add = []
                if "source_class" not in val:
                    add.append(" " * child_col + f"source_class: {source_class(val.get('url'), val.get('type') or key)}")
                if "as_of" not in val:
                    add.append(" " * child_col + f"as_of: {_q(norm_dates(as_of))}")
                if add:
                    P.insert_after(kln, add)

    elif fn == "kpis.yaml":
        for item in doc.get("critical_kpis", []):
            iln, icol = _keyline(lines, item, "id")
            ind = " " * icol
            add = []
            if "source_class" not in item:
                add.append(f"{ind}source_class: {source_class(item.get('source_url'), item.get('source'))}")
            if "provenance" not in item:
                add.append(f"{ind}provenance: verified_fact")
            vt = item.get("value_type")
            if vt is None:
                add.append(f"{ind}value_type: actual")
            elif vt in LEGACY_QUALIFIERS:
                vln, _ = _keyline(lines, item, "value_type")
                P.replace(vln, vln + 1, [f"{ind}value_type: actual"] + ([f"{ind}observation_qualifier: {vt}"] if "observation_qualifier" not in item else []))
            if "last_value" in item:
                lv = item["last_value"]
                num, extra = split_value(norm_dates(lv) if not isinstance(lv, (list, str)) else (list(lv) if isinstance(lv, list) else str(lv)))
                if extra:
                    lln, lcol = _keyline(lines, item, "last_value")
                    end = _block_end(lines, lln, lcol)
                    new = [f"{ind}last_value: {_q(num)}"]
                    if "observation_qualifier" not in item:
                        new.append(f"{ind}observation_qualifier: {extra['observation_qualifier']}")
                    if "value_range" in extra and "value_range" not in item:
                        new += [f"{ind}value_range:", f"{ind}  min: {_q(extra['value_range']['min'])}", f"{ind}  max: {_q(extra['value_range']['max'])}"]
                    P.replace(lln, end, new)
            th = item.get("thresholds")
            if isinstance(th, dict) and "yellow" not in th and "binary" not in th and set(th) >= {"green", "red"} and _is_binary_zone(th["green"]) and _is_binary_zone(th["red"]):
                tln, tcol = _keyline(lines, item, "thresholds")
                assert lines[tln].rstrip().endswith(":"), "thresholds должен быть блочным"
                P.insert_after(tln, [" " * _indent(lines[tln + 1]) + "binary: true"])
            if add:
                P.insert_after(iln, add)

    elif fn == "triggers.yaml":
        full = ctx["full"]
        profile = doc.get("profile") or ("full_model" if full else "registry_only")
        if "profile" not in doc:
            head.append(f"profile: {profile}")
        au = doc.get("automations")
        if isinstance(au, dict) and "_note" in au and "automations_note" not in doc:
            nln, ncol = _keyline(lines, au, "_note")
            end = _value_end(lines, nln, ncol)
            assert end == nln + 1, "automations._note ожидается однострочным"
            if len(au) == 1:  # _note был единственным ключом → блок стал бы null; делаем явный пустой map
                aln, acol = _keyline(lines, doc, "automations")
                P.replace(aln, end, [" " * acol + "automations: {}"])
            else:
                P.replace(nln, end, [])
            P.append([f"automations_note: {_q(au['_note'])}"])
        for t in doc.get("triggers", []):
            iln, icol = _keyline(lines, t, "id")
            ind = " " * icol
            add = []
            if "transition" in t and "condition_provenance" not in t:
                add.append(f"{ind}condition_provenance: model_assumption")
            if profile == "full_model" and "fired" not in t:
                add.append(f"{ind}fired: []")
            if add:
                P.insert_after(iln, add)
        meta = doc.get("meta")
        if meta is not None:
            mln, mcol = _keyline(lines, doc, "meta")
            child_col = _indent(lines[mln + 1])
            add = []
            if profile == "full_model":
                sj = ctx.get("state") or {}
                kp = ctx.get("kpis") or {}
                for k, v in (("source_artifact", kp.get("source_artifact")), ("price_source", (sj.get("price") or {}).get("source") or "Yahoo Finance chart (дозор)"),
                             ("price_at_registry", (sj.get("price") or {}).get("last")), ("position", None)):
                    if k not in meta:
                        add.append(" " * child_col + f"{k}: {_q(v)}")
            if isinstance(meta.get("horizon"), int):
                hln, _ = _keyline(lines, meta, "horizon")
                P.replace(hln, hln + 1, [" " * child_col + f"horizon: '{meta['horizon']}'"])
            if add:
                P.insert_before(_block_end(lines, mln, mcol), add)
        if profile == "full_model" and "rules" not in doc:
            sem = (ctx.get("states") or {}).get("semantics") or {}
            P.append(["rules:"] + [f"  {k}: {_q(sem.get(k, True))}" for k in ("evidence_required", "pending_verification_blocks_transition", "trigger_not_decision")])

    elif fn == "mpc_inputs.yaml":
        if "driver_vector_provenance" not in doc:
            head.append("driver_vector_provenance: model_assumption")

    if head:
        P.insert_before(first_ln, head)
    return "\n".join(P.apply())


# ----------------------------------------------------------------------------------------------- патч state.json
def patch_json(raw: str, expected: dict) -> str:
    """state.json: если json.dumps(indent=2) воспроизводит файл байт-в-байт — перезапись дампом; иначе построчный патч
    (компактные однострочные наблюдения + вставка schema_version)."""
    data = json.loads(raw)
    if json.dumps(data, ensure_ascii=False, indent=2) + "\n" == raw:
        return json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
    lines = raw.split("\n")
    P = _Patch(lines)
    assert lines[0].strip() == "{", "state.json должен начинаться с «{»"
    if "schema_version" not in data:
        P.insert_after(0, [f'  "schema_version": "{SCHEMA_VERSION}",'])
    elif data["schema_version"] != SCHEMA_VERSION:
        for i, ln in enumerate(lines):
            m = re.match(r'^(\s*)"schema_version": "[^"]*"(,?)\s*$', ln)
            if m:
                P.replace(i, i + 1, [f'{m.group(1)}"schema_version": "{SCHEMA_VERSION}"{m.group(2)}'])
                break
        else:
            raise AssertionError("schema_version не найден одной строкой")
    exp_obs = {o["kpi_id"]: o for o in expected.get("kpi_observations", [])}
    if len(exp_obs) != len(expected.get("kpi_observations", [])) or any(o.get("verification_run_id") for o in data.get("kpi_observations") or []):
        raise AssertionError("MIG-122 (история прогонов / схлопывание дубликатов) построчно не патчится: файл не дамп-идемпотентен")
    for i, ln in enumerate(lines):
        m = re.match(r'^(\s*)(\{"kpi_id": .*\})(,?)\s*$', ln)
        if m:
            o = json.loads(m.group(2))
            new = dict(o)
            migrate_kpi_like(new, "value")
            assert new == exp_obs.get(o["kpi_id"]), ("наблюдение расходится с эталоном", o.get("kpi_id"))
            if new != o:
                P.replace(i, i + 1, [m.group(1) + json.dumps(new, ensure_ascii=False) + m.group(3)])
    if isinstance(data.get("notes"), str):  # MIG-108: строка → список из одного элемента
        for i, ln in enumerate(lines):
            m = re.match(r'^(\s*)"notes": ("(?:[^"\\]|\\.)*")(,?)\s*$', ln)
            if m:
                P.replace(i, i + 1, [f'{m.group(1)}"notes": [', f"{m.group(1)}  {m.group(2)}", f"{m.group(1)}]{m.group(3)}"])
                break
        else:
            raise AssertionError("notes-строка не найдена одной строкой")
    return "\n".join(P.apply())


# ----------------------------------------------------------------------------------------------- профиль legacy spacex (MIG-SPCX)
SPCX_LEGACY_FILES = {"states.yaml": "states_legacy_notes.yaml", "kpis.yaml": "kpis_legacy.yaml", "triggers.yaml": "triggers_legacy.yaml",
                     "mpc_inputs.yaml": "mpc_inputs_legacy.yaml", "state.json": "state_legacy.json"}
SPCX_STATES_ROOT_EXTRA = ("source_policy", "transition_semantics", "evaluation_rule", "legacy_compatibility")
SPCX_AXIS_EXTRA = ("current_snapshot", "transition_triggers")
SPCX_KPIS_ROOT_EXTRA = ("derived_checks", "data_quality", "kpi_observation_rule", "supporting_metrics", "calculated_metrics")
SPCX_KPI_EXTRA = ("last_yoy_growth", "last_yoy_change", "inputs")
SPCX_TRIGGER_EXTRA = ("strategy_ref", "probability_in_strategy", "notes_kpi", "supporting_metrics", "calculated_metrics")
SPCX_META_EXTRA = ("reference_price_in_strategy", "target_average_price", "position_plan")
SPCX_MPC_EXTRA = ("methodology_refs", "status", "model_notes")
SPCX_MPC_SEMANTICS = {"driver_scale": "scale", "provenance": "provenance", "rule": "direction_rule"}   # MIG-SPCX-14: чистое переименование
SPCX_STATE_EXTRA = ("calc_inputs", "gaap_profit_quarters")
SPCX_INFO_KIND = "legacy_trigger_log"      # MIG-SPCX-17: kind записей info_log старой формы, где его не было
SPCX_AXIS_VERIFIED_NOTE = "флаг добавлен миграцией MIG-SPCX-18: протокольной проверки дозором не было (нет verification_run_id)"
SPCX_DVP_COMMENT = "# MIG-SPCX-15: перенос из v1.0 — экспертная оценка вектора (source_artifact), не проверялась"


def spcx_source_class(url: str | None) -> str:
    """MIG-SPCX-07 (Source Policy v1.0, source_class_resolution): SEC-хостинговый релиз о результатах (earningsrelease*, ex99, press)
    → issuer_ir_release (приоритет 2, по идентичности документа, не по домену); тело формы SEC (10-Q/10-K) → regulatory_filing
    (приоритет 1); Yahoo/StockAnalysis → market_data_provider (приоритет 7; агрегатор StockAnalysis политика не называет —
    отнесён к поставщикам рыночных данных); иначе other_primary. Общий source_class() не меняется (другие папки не трогаются)."""
    u = (url or "").lower()
    if "yahoo" in u or "stockanalysis.com" in u:
        return "market_data_provider"
    if "sec.gov" in u:
        name = u.split("?")[0].rsplit("/", 1)[-1]
        return "issuer_ir_release" if re.search(r"earningsrelease|ex[-_]?99|_pr\.|press", name) else "regulatory_filing"
    return "other_primary"


def _spcx_source_key(ticker: str, url: str) -> str:
    u = url.lower()
    if "sec.gov" in u:
        kind = "EARNINGS_RELEASE" if spcx_source_class(url) == "issuer_ir_release" else "SEC_FILING"
    elif "yahoo" in u:
        kind = "YAHOO_QUOTE"
    elif "stockanalysis.com" in u:
        kind = "STOCKANALYSIS"
    else:
        kind = "SOURCE"
    return f"{ticker}_{kind}"


def _snapshot_urls(src) -> list[str]:
    """URL из поля source снимка («url1; url2» или текст): только элементы, начинающиеся с http — источники не выдумываются."""
    return [s.strip() for s in str(src or "").split(";") if s.strip().startswith("http")]


def _is_calc_formula(f) -> bool:
    """KPI — расчётное значение (derived_fact), если формула — арифметика с делением («a / b»); иначе формула описывает
    раскрытую строку отчёта (verified_fact по source_url)."""
    return bool(re.search(r"\s/\s", str(f or "")))


def _covers_list(text: str, prefix: str) -> list[str]:
    """«E-10..E-19, E-25..E-29 (пояснение)» → явный список ID (детерминированное раскрытие диапазонов, MIG-SPCX-13)."""
    out: list[str] = []
    for a, b in re.findall(r"E-(\d+)\.\.E-(\d+)", text):
        out += [f"{prefix}-E-{i:02d}" for i in range(int(a), int(b) + 1)]
    return out


def _spcx_exchange(state: dict) -> str | None:
    """Биржа из фактов папки: запись events_reported с источником ir.nasdaq.com о включении в Nasdaq-100 (включение требует
    листинга на Nasdaq). Нет такой записи — None (биржа не выдумывается, миграция откажет)."""
    for e in (state or {}).get("events_reported") or []:
        if "ir.nasdaq.com" in str(e.get("source") or "") and "Nasdaq-100" in str(e.get("summary") or ""):
            return "NASDAQ"
    return None


def spcx_migrate_docs(docs: dict) -> tuple[dict, dict, dict]:
    """Эталон профиля legacy spacex в памяти (MIG-SPCX-02…19; MIG-SPCX-01 schema_version — общим правилом после профиля).
    Возвращает (docs после профиля, перенесённое в _legacy по файлам {fn: dict}, заметки для отчёта). Вход не меняется;
    на уже мигрированных файлах — тождество и пустой _legacy (идемпотентность)."""
    docs = copy.deepcopy(docs)
    legacy: dict = {fn: {} for fn in docs}
    notes: dict = {"transition_triggers": {}, "null_transitions_removed": [], "kpi_provenance": {}, "kpi_value_type_ambiguous": []}
    st, kp, tr, mp, sj = (docs.get(fn) for fn in FILES)
    ticker = str((st or kp or {}).get("ticker") or "SPCX")
    prov: dict = {}
    if st:
        L = legacy["states.yaml"]
        urls: list[str] = []
        for ax, a in (st.get("axes") or {}).items():
            for s in (a.get("states") or {}).values():
                if "definition" in s and "criteria" not in s:                                    # MIG-SPCX-02
                    s["criteria"] = s.pop("definition")
            moved = {k: a.pop(k) for k in SPCX_AXIS_EXTRA if k in a}                             # MIG-SPCX-03
            if moved:
                L.setdefault("axes", {})[ax] = moved
            snap = moved.get("current_snapshot") or {}
            if "current" not in a:
                a["current"] = snap.get("state") or ((sj or {}).get("scenario_state") or {}).get(ax, {}).get("state")
            if "current_evidence" not in a:
                a["current_evidence"] = list(snap.get("evidence") or [])
            if "source_refs" not in a:
                u = _snapshot_urls(snap.get("source"))
                urls += [x for x in u if x not in urls]
                a["source_refs"] = u                                                             # ключи — ниже, после построения sources
            if "transition_triggers" in moved:
                notes["transition_triggers"][ax] = list(moved["transition_triggers"])
        if "sources" not in st:                                                                  # MIG-SPCX-04
            keys: dict = {}
            for u in urls:
                base = _spcx_source_key(ticker, u); k = base; n = 2
                while k in keys.values():
                    k = f"{base}_{n}"; n += 1
                keys[u] = k
            st["sources"] = {keys[u]: {"source_class": spcx_source_class(u), "url": u, "as_of": st.get("as_of")} for u in urls}
            for a in (st.get("axes") or {}).values():
                a["source_refs"] = [keys.get(x, x) for x in a["source_refs"]]
        for k in SPCX_STATES_ROOT_EXTRA:                                                         # MIG-SPCX-05
            if k in st:
                L[k] = st.pop(k)
    if kp:
        L = legacy["kpis.yaml"]
        if "zone_semantics" not in kp:                                                           # MIG-SPCX-06
            kp["zone_semantics"] = {"thresholds_provenance": "model_assumption"}
        for k in kp.get("critical_kpis") or []:
            k.setdefault("value_type", "actual")                                                 # MIG-SPCX-07
            k.setdefault("source_class", spcx_source_class(k.get("source_url")))
            k.setdefault("verified", None)
            k.setdefault("provenance", "derived_fact" if _is_calc_formula(k.get("formula")) else "verified_fact")
            prov[k["id"]] = k["provenance"]
            notes["kpi_provenance"][k["id"]] = k["provenance"]
            if re.search(r"guidance|прогноз|outlook|forecast", f"{k.get('name')} {k.get('formula')}", re.I):
                notes["kpi_value_type_ambiguous"].append(k["id"])
            moved = {}
            if "notes" in k and "note" not in k:                                                 # MIG-SPCX-08
                k["note"] = k.pop("notes")
            if "last_value_raw" in k:
                if "note" not in k:
                    k["note"] = f"last_value_raw: {k.pop('last_value_raw')}"
                else:
                    moved["last_value_raw"] = k.pop("last_value_raw")
            for f in SPCX_KPI_EXTRA:
                if f in k:
                    moved[f] = k.pop(f)
            if moved:
                L.setdefault("critical_kpis", {})[k["id"]] = moved
        for f in SPCX_KPIS_ROOT_EXTRA:                                                           # MIG-SPCX-09
            if f in kp:
                L[f] = kp.pop(f)
    if tr:
        L = legacy["triggers.yaml"]
        prefix = ticker
        meta = tr.get("meta") or {}
        moved = {f: meta.pop(f) for f in SPCX_META_EXTRA if f in meta}                          # MIG-SPCX-12
        if moved:
            L["meta"] = moved
        if "yahoo_symbol" not in meta:
            m = re.search(r"/chart/([A-Za-z0-9.\-]+)", str(meta.get("price_source") or ""))
            meta["yahoo_symbol"] = m.group(1) if m else None
        if "exchange" not in meta:
            meta["exchange"] = _spcx_exchange(sj)
        for name, au in (tr.get("automations") or {}).items():                                   # MIG-SPCX-13
            if not isinstance(au, dict):
                continue
            if "pilot" in au:
                L.setdefault("automations", {})[name] = {"pilot": au.pop("pilot")}
            if isinstance(au.get("covers"), str):
                au["note"] = au["covers"]
                au["covers"] = _covers_list(au["covers"], prefix)
        for t in tr.get("triggers") or []:
            moved = {f: t.pop(f) for f in SPCX_TRIGGER_EXTRA if f in t}                          # MIG-SPCX-10
            if moved:
                L.setdefault("triggers", {})[t["id"]] = moved
            if "transition" in t and t["transition"] is None:                                    # MIG-SPCX-11: не переход
                del t["transition"]
                notes["null_transitions_removed"].append(t["id"])
        reg = {t["id"]: t for t in tr.get("triggers") or []}
        for ax, listed in notes["transition_triggers"].items():
            on_axis = [i for i, t in reg.items() if t.get("axis") == ax and isinstance(t.get("transition"), dict)]
            notes["transition_triggers"][ax] = {"listed": listed, "missing_in_triggers": [i for i in listed if i not in reg],
                                                "listed_but_not_transition_on_axis": [i for i in listed if i in reg and i not in on_axis],
                                                "transition_on_axis_not_listed": [i for i in on_axis if i not in listed]}
    if mp:
        L = legacy["mpc_inputs.yaml"]
        if "semantics" in mp and "driver_exposure_semantics" not in mp:                          # MIG-SPCX-14
            sem = mp.pop("semantics")
            extra = set(sem) - set(SPCX_MPC_SEMANTICS)
            if extra:
                raise ValueError(f"mpc_inputs.semantics: ключи {sorted(extra)} не переименовываются в driver_exposure_semantics")
            mp["driver_exposure_semantics"] = {SPCX_MPC_SEMANTICS[k]: v for k, v in sem.items()}
        for f in SPCX_MPC_EXTRA:                                                                 # MIG-SPCX-15
            if f in mp:
                L[f] = mp.pop(f)
        mp.setdefault("driver_vector_provenance", "model_assumption")
    if sj:
        L = legacy["state.json"]
        for o in sj.get("kpi_observations") or []:                                              # MIG-SPCX-16
            if "provenance" not in o:
                o["provenance"] = prov.get(o.get("kpi_id"), "verified_fact")
            if "run_id" in o:
                rid = o.pop("run_id")
                o["note"] = f"run_id: {rid}" if "note" not in o else o["note"]
                if o["note"] != f"run_id: {rid}":
                    L.setdefault("kpi_observations", []).append({"kpi_id": o.get("kpi_id"), "period_end": o.get("period_end"), "run_id": rid})
        for i, e in enumerate(sj.get("info_log") or []):                                          # MIG-SPCX-17
            if "text" in e or "level" in e or "trigger_id" in e:
                extra = {k: e[k] for k in ("trigger_id", "level") if k in e}
                if extra:
                    L.setdefault("info_log", []).append({"timestamp": e.get("timestamp"), **extra})
                sj["info_log"][i] = {"timestamp": e.get("timestamp"), "kind": e.get("kind") or SPCX_INFO_KIND, "summary": e.get("summary") or e.get("text")}
        for a in (sj.get("scenario_state") or {}).values():                                      # MIG-SPCX-18
            if "verified" not in a:
                a["verified"] = False
                a.setdefault("verified_note", SPCX_AXIS_VERIFIED_NOTE)
        for f in SPCX_STATE_EXTRA:                                                               # MIG-SPCX-19
            if f in sj:
                L[f] = sj.pop(f)
    return docs, {fn: v for fn, v in legacy.items() if v}, notes


def _reindent(block: list[str], delta: int) -> list[str]:
    if delta >= 0:
        return [(" " * delta + ln) if ln.strip() else ln for ln in block]
    assert all(not ln.strip() or ln[:-delta].strip() == "" for ln in block), "перенос блока: отрицательный сдвиг режет текст"
    return [ln[-delta:] if ln.strip() else ln for ln in block]


def _plain_or_q(s) -> str:
    """Скаляр как в мигрированных папках: простой токен / URL без «: » и « #» — без кавычек, иначе _q."""
    return str(s) if isinstance(s, str) and re.fullmatch(r"[A-Za-z0-9_.:/?=&%+~\-]+", s) and not re.search(r": | #", s) else _q(s)


def _legacy_header(fn: str) -> list[str]:
    return [f"# Перенесено дословно из {fn} профилем MIG-SPCX (migrate_artifacts_v1_0_1 {TOOL_VERSION}): поля старого формата вне",
            f"# Company Artifact Schema v{SCHEMA_VERSION}. Невалидируемый файл; значения, комментарии и порядок ключей — как в исходнике."]


def _header_comment_index(lines: list[str]) -> int:
    """Индекс строки, после которой вставляется комментарий-ссылка на _legacy (последний ведущий комментарий, иначе −1)."""
    i = -1
    while i + 1 < len(lines) and lines[i + 1].startswith("#"):
        i += 1
    return i


def spcx_patch_yaml(fn: str, raw: str, ctx: dict) -> tuple[str, str | None]:
    """Построчный профиль MIG-SPCX для YAML (И2): переименования ключей в той же строке, удаление перенесённых блоков,
    вставка обязательных полей. Возвращает (новый текст, текст _legacy/<файл> | None). Перенесённые блоки копируются в
    _legacy дословно (со своими комментариями), со сдвигом отступа под новый родительский ключ."""
    from ruamel.yaml import YAML

    y = YAML()
    y.preserve_quotes = True
    doc = y.load(raw)
    lines = raw.split("\n")
    P = _Patch(lines)
    leg: list[str] = []
    ref = ctx["ref"][fn]

    def take(parent, key, target_col=None):
        """Удалить ключ key из parent (блок целиком) и вернуть его строки со сдвигом к target_col."""
        kln, kcol = _keyline(lines, parent, key)
        nxt = [parent.lc.data[k][0] for k in parent if parent.lc.data[k][0] > kln]
        # конец блока — строка следующего ключа того же отображения (двойные кавычки допускают строки-продолжения с
        # отступом меньше ключа, «\ …»); у последнего ключа — по отступам
        end = min(nxt) if nxt else _block_end(lines, kln, kcol)
        while end > kln + 1 and (not lines[end - 1].strip() or (lines[end - 1].lstrip().startswith("#") and _indent(lines[end - 1]) <= kcol)):
            end -= 1                                                                             # хвостовые пустые/внешние комментарии остаются
        block = list(lines[kln:end])
        if lines[kln].lstrip().startswith("- "):
            raise AssertionError(f"{fn}: перенос ключа {key}, открывающего элемент списка, не поддерживается")
        P.replace(kln, end, [])
        return _reindent(block, (kcol if target_col is None else target_col) - kcol)

    if fn == "states.yaml":
        axes = doc.get("axes") or {}
        axis_leg: list[str] = []
        for ax, a in axes.items():
            for sid, s in (a.get("states") or {}).items():
                if "definition" in s and "criteria" not in s:                                  # MIG-SPCX-02
                    dln, _ = _keyline(lines, s, "definition")
                    P.replace(dln, dln + 1, [lines[dln].replace("definition:", "criteria:", 1)])
            present = [k for k in SPCX_AXIS_EXTRA if k in a]
            if not present:
                continue
            col = _keyline(lines, a, present[0])[1]
            first = min(_keyline(lines, a, k)[0] for k in present)
            axis_leg += [f"  {ax}:"]
            for k in present:
                axis_leg += take(a, k, 4)
            ra = ref["axes"][ax]; ind = " " * col; new = []
            if "current" not in a:
                new.append(f"{ind}current: {_plain_or_q(ra['current'])}")
            for key in ("current_evidence", "source_refs"):
                if key not in a:
                    vals = ra[key]
                    new += [f"{ind}{key}: []"] if not vals else [f"{ind}{key}:"] + [f"{ind}- {_plain_or_q(v) if key == 'source_refs' else _q(v)}" for v in vals]
            P.insert_before(first, new)
        if "sources" not in doc:                                                                 # MIG-SPCX-04
            aln, _ = _keyline(lines, doc, "axes")
            new = ["sources:"] if ref["sources"] else ["sources: {}"]
            for key, v in ref["sources"].items():
                new += [f"  {key}:", f"    source_class: {v['source_class']}", f"    url: {_plain_or_q(v['url'])}", f"    as_of: {_q(v['as_of'])}"]
            P.insert_before(aln, new)
        for k in SPCX_STATES_ROOT_EXTRA:                                                         # MIG-SPCX-05
            if k in doc:
                leg += take(doc, k)
        if axis_leg:
            leg += ["axes:"] + axis_leg

    elif fn == "kpis.yaml":
        if "zone_semantics" not in doc:                                                          # MIG-SPCX-06
            cln, _ = _keyline(lines, doc, "critical_kpis")
            P.insert_before(cln, ["zone_semantics:", "  thresholds_provenance: model_assumption"])
        kleg: list[str] = []
        rk = {k["id"]: k for k in ref.get("critical_kpis") or []}
        for item in doc.get("critical_kpis") or []:
            iln, icol = _keyline(lines, item, "id")
            ind = " " * icol; r = rk[item["id"]]; add = []
            for f in ("value_type", "source_class", "verified", "provenance"):                   # MIG-SPCX-07
                if f not in item:
                    add.append(f"{ind}{f}: {_plain_or_q(r[f]) if r[f] is not None else 'null'}")
            if add:
                P.insert_after(iln, add)
            moved: list[str] = []
            has_note = "note" in item
            if "notes" in item and not has_note:                                                 # MIG-SPCX-08
                nln, _ = _keyline(lines, item, "notes")
                P.replace(nln, nln + 1, [lines[nln].replace("notes:", "note:", 1)])
                has_note = True
            if "last_value_raw" in item:
                if not has_note:
                    rln, rcol = _keyline(lines, item, "last_value_raw")
                    assert _block_end(lines, rln, rcol) == rln + 1, "last_value_raw ожидается однострочным"
                    P.replace(rln, rln + 1, [f"{ind}note: {_q(r['note'])}"])
                else:
                    moved += take(item, "last_value_raw", 4)
            for f in SPCX_KPI_EXTRA:
                if f in item:
                    moved += take(item, f, 4)
            if moved:
                kleg += [f"  {item['id']}:"] + moved
        for f in SPCX_KPIS_ROOT_EXTRA:                                                           # MIG-SPCX-09
            if f in doc:
                leg += take(doc, f)
        if kleg:
            leg += ["critical_kpis:"] + kleg

    elif fn == "triggers.yaml":
        meta = doc.get("meta")
        rm = ref.get("meta") or {}
        if meta is not None:
            mleg: list[str] = []
            for f in SPCX_META_EXTRA:                                                            # MIG-SPCX-12
                if f in meta:
                    mleg += take(meta, f, 2)
            if mleg:
                leg += ["meta:"] + mleg
            add = []
            anchor = "company" if "company" in meta else "ticker"
            aln, acol = _keyline(lines, meta, anchor)
            for f in ("exchange", "yahoo_symbol"):
                if f not in meta:
                    if rm.get(f) is None:
                        raise AssertionError(f"triggers.meta.{f}: значение не выводится из файлов папки — задайте вручную")
                    add.append(" " * acol + f"{f}: {_plain_or_q(rm[f])}")
            if add:
                P.insert_after(aln, add)
        au = doc.get("automations")
        aleg: list[str] = []
        for name, a in (au or {}).items():                                                       # MIG-SPCX-13
            if not isinstance(a, dict) or not ("pilot" in a or isinstance(a.get("covers"), str)):
                continue
            nln, ncol = _keyline(lines, au, name)
            line = lines[nln]
            assert _block_end(lines, nln, ncol) == nln + 1 and "{" in line, "automations: ожидается однострочная flow-запись"
            if "pilot" in a:
                line, k = re.subn(r"pilot:\s*(true|false),\s*", "", line)
                assert k == 1, ("pilot", lines[nln])
                aleg += [f"  {name}:", f"    pilot: {_q(a['pilot'])}"]
            if isinstance(a.get("covers"), str):
                m = re.search(r'covers:\s*("(?:[^"\\]|\\.)*"|\'(?:[^\']|\'\')*\')', line)
                assert m, ("covers", lines[nln])
                lst = "[" + ", ".join(ref["automations"][name]["covers"]) + "]"
                line = line[:m.start()] + f"covers: {lst}" + line[m.end():]
                line = re.sub(r"\s*\}\s*$", f", note: {m.group(1)} }}", line)
            P.replace(nln, nln + 1, [line])
        if aleg:
            leg += ["automations:"] + aleg
        tleg: list[str] = []
        for t in doc.get("triggers") or []:
            moved: list[str] = []
            for f in SPCX_TRIGGER_EXTRA:                                                         # MIG-SPCX-10
                if f in t:
                    moved += take(t, f, 4)
            if "transition" in t and t["transition"] is None:                                    # MIG-SPCX-11
                tln, tcol = _keyline(lines, t, "transition")
                assert _block_end(lines, tln, tcol) == tln + 1, "transition: null ожидается однострочным"
                P.replace(tln, tln + 1, [])
            if moved:
                tleg += [f"  {t['id']}:"] + moved
        if tleg:
            leg += ["triggers:"] + tleg

    elif fn == "mpc_inputs.yaml":
        sem = doc.get("semantics")
        if sem is not None and "driver_exposure_semantics" not in doc:                          # MIG-SPCX-14
            sln, _ = _keyline(lines, doc, "semantics")
            P.replace(sln, sln + 1, [lines[sln].replace("semantics:", "driver_exposure_semantics:", 1)])
            for k in sem:
                if k not in SPCX_MPC_SEMANTICS:
                    raise AssertionError(f"mpc_inputs.semantics.{k}: не переименовывается")
                if SPCX_MPC_SEMANTICS[k] != k:
                    kln, _ = _keyline(lines, sem, k)
                    P.replace(kln, kln + 1, [lines[kln].replace(f"{k}:", f"{SPCX_MPC_SEMANTICS[k]}:", 1)])
        for f in SPCX_MPC_EXTRA:                                                                 # MIG-SPCX-15
            if f in doc:
                leg += take(doc, f)
        if "driver_vector_provenance" not in doc:
            anchor = "driver_interpretation" if "driver_interpretation" in doc else "failure_modes"
            aln, _ = _keyline(lines, doc, anchor)
            P.insert_before(aln, [f"driver_vector_provenance: model_assumption  {SPCX_DVP_COMMENT}"])

    legacy_text = None
    if leg:
        name = SPCX_LEGACY_FILES[fn]
        P.insert_after(_header_comment_index(lines), [f"# MIG-SPCX: поля старого формата перенесены дословно в _legacy/{name} (migrate_artifacts_v1_0_1 {TOOL_VERSION})"])
        legacy_text = "\n".join(_legacy_header(fn) + leg) + "\n"
    return "\n".join(P.apply()), legacy_text


def spcx_patch_json(raw: str, ref: dict, legacy: dict | None) -> tuple[str, str | None]:
    """state.json профиля MIG-SPCX: файл дамп-идемпотентен (json.dumps indent=2) — пишется дампом эталона; иначе отказ.
    _legacy/state_legacy.json — дамп перенесённого."""
    data = json.loads(raw)
    if json.dumps(data, ensure_ascii=False, indent=2) + "\n" != raw:
        raise AssertionError("state.json профиля MIG-SPCX ожидается дамп-идемпотентным (json.dumps indent=2)")
    return json.dumps(ref, ensure_ascii=False, indent=2) + "\n", (json.dumps(legacy, ensure_ascii=False, indent=2) + "\n" if legacy else None)


def spcx_stage(texts: dict) -> tuple[dict, dict, dict, dict]:
    """Профиль MIG-SPCX над текстами файлов папки: (тексты после профиля, эталон docs после профиля, тексты _legacy {имя: текст},
    заметки). Проверяет И2: разбор каждого пропатченного файла равен эталону spcx_migrate_docs, разбор _legacy — перенесённому."""
    docs = {fn: norm_dates(json.loads(t) if fn == "state.json" else yaml.safe_load(t)) for fn, t in texts.items()}
    ref, legacy, notes = spcx_migrate_docs(docs)
    out, leg_out = {}, {}
    for fn, t in texts.items():
        if fn == "state.json":
            new, lt = spcx_patch_json(t, ref[fn], legacy.get(fn))
        else:
            new, lt = spcx_patch_yaml(fn, t, {"ref": ref})
        got = norm_dates(json.loads(new) if fn == "state.json" else yaml.safe_load(new))
        if got != ref[fn]:
            raise AssertionError(f"{fn}: профиль MIG-SPCX — патч ≠ эталону: " + _first_diff(got, ref[fn]))
        if (lt is None) != (fn not in legacy):
            raise AssertionError(f"{fn}: _legacy — расхождение наличия переноса")
        if lt is not None:
            lgot = norm_dates(json.loads(lt) if fn == "state.json" else yaml.safe_load(lt))
            if lgot != norm_dates(legacy[fn]):
                raise AssertionError(f"{fn}: _legacy ≠ перенесённому: " + _first_diff(lgot, norm_dates(legacy[fn])))
            leg_out[SPCX_LEGACY_FILES[fn]] = lt
        out[fn] = new
    return out, ref, leg_out, notes


# ----------------------------------------------------------------------------------------------- прогон по папке
def migrate_folder(folder: Path, apply: bool) -> dict:
    present = [fn for fn in FILES if (folder / fn).exists()]
    texts, crlf = {}, {}
    for fn in present:
        raw_b = (folder / fn).read_bytes()
        assert not raw_b.startswith(b"\xef\xbb\xbf"), f"{folder / fn}: BOM не ожидается"
        raw = raw_b.decode("utf-8")
        crlf[fn] = "\r\n" in raw
        texts[fn] = raw.replace("\r\n", "\n")
    orig = dict(texts)
    report = {"folder": folder.name, "profile": None, "changed": [], "unchanged": [], "errors": [], "legacy": []}
    legacy_texts: dict = {}
    if folder.name in SPCX_FOLDERS:
        try:
            texts, _, legacy_texts, report["spcx"] = spcx_stage(texts)
        except Exception as e:  # noqa: BLE001 — профиль отказал: ни один файл папки не пишется
            report["errors"].append(f"MIG-SPCX: {e}")
            return report
    docs = {fn: norm_dates(json.loads(texts[fn]) if fn == "state.json" else yaml.safe_load(texts[fn])) for fn in present}
    expected = migrate_docs(docs, load_verify_reports(folder))
    full = all(fn in docs for fn in ("states.yaml", "kpis.yaml", "mpc_inputs.yaml"))
    ctx = {"full": full, "states": docs.get("states.yaml"), "kpis": docs.get("kpis.yaml"), "state": docs.get("state.json")}
    report["profile"] = "full_model" if full else "registry_only"
    staged: dict = {}
    for fn in present:
        p = folder / fn
        text = texts[fn]
        try:
            new = patch_json(text, expected[fn]) if fn == "state.json" else patch_yaml(fn, text, ctx)
            got = norm_dates(json.loads(new) if fn == "state.json" else yaml.safe_load(new))
            if got != expected[fn]:
                raise AssertionError("результат построчного патча ≠ эталонной миграции: " + _first_diff(got, expected[fn]))
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"{fn}: {e}")
            continue
        if new == orig[fn]:
            report["unchanged"].append(fn)
            continue
        report["changed"].append(fn)
        staged[p] = new.replace("\n", "\r\n") if crlf[fn] else new
    ldir = folder / "_legacy"
    for name, lt in legacy_texts.items():                                                        # MIG-SPCX: перенесённое
        lp = ldir / name
        if lp.exists():
            if lp.read_bytes().decode("utf-8") != lt:
                report["errors"].append(f"_legacy/{name}: файл уже существует и отличается — перезапись запрещена")
            continue
        report["legacy"].append(f"_legacy/{name}")
        staged[lp] = lt
    if folder.name in SPCX_FOLDERS and report["errors"]:
        return report                                                                            # профиль пишет папку только целиком
    if apply:
        for p, out in staged.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(out.encode("utf-8"))
    return report


def _first_diff(a, b, path="$") -> str:
    if type(a) is not type(b):
        return f"{path}: тип {type(a).__name__} ≠ {type(b).__name__} ({a!r:.60} / {b!r:.60})"
    if isinstance(a, dict):
        for k in set(a) | set(b):
            if k not in a or k not in b:
                return f"{path}.{k}: {'нет в патче' if k not in a else 'нет в эталоне'}"
            if a[k] != b[k]:
                return _first_diff(a[k], b[k], f"{path}.{k}")
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: длина {len(a)} ≠ {len(b)}"
        for i, (x, z) in enumerate(zip(a, b)):
            if x != z:
                return _first_diff(x, z, f"{path}[{i}]")
    return f"{path}: {a!r:.80} ≠ {b!r:.80}"


def iter_folders(workspace: Path, only: set[str] | None):
    for p in sorted((workspace / "portfolio").iterdir()):
        if p.is_dir() and not p.name.startswith("_") and p.name not in SKIP_FOLDERS and (p / "triggers.yaml").exists():
            if only is None or p.name in only:
                yield p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workspace")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default=None)
    a = ap.parse_args(argv)
    only = set(a.only.split(",")) if a.only else None
    bad = 0
    for folder in iter_folders(Path(a.workspace), only):
        r = migrate_folder(folder, a.apply)
        bad += bool(r["errors"])
        print(f"{r['folder']:8} {str(r['profile']):13} изменено: {', '.join(r['changed']) or '—'} | без изменений: {len(r['unchanged'])}"
              + (f" | _legacy: {', '.join(r['legacy'])}" if r.get("legacy") else "") + (f" | ОШИБКИ: {r['errors']}" if r["errors"] else ""))
        if r.get("spcx"):
            print("  MIG-SPCX:", json.dumps(r["spcx"], ensure_ascii=False))
    print("режим:", "ЗАПИСЬ" if a.apply else "сухой прогон (ничего не записано)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
