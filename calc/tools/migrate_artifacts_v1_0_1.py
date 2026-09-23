"""Детерминированная миграция артефактов компаний workspace к Company Artifact Schema v1.0.x (текущая цель — SCHEMA_VERSION)
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
Не мигрируются: spacex (старый формат, отдельное решение), папки без triggers.yaml, каталоги `_*`.
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
SKIP_FOLDERS = {"spacex"}
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


# ----------------------------------------------------------------------------------------------- прогон по папке
def migrate_folder(folder: Path, apply: bool) -> dict:
    present = [fn for fn in FILES if (folder / fn).exists()]
    docs = {fn: load_plain(folder / fn) for fn in present}
    expected = migrate_docs(docs, load_verify_reports(folder))
    full = all(fn in docs for fn in ("states.yaml", "kpis.yaml", "mpc_inputs.yaml"))
    ctx = {"full": full, "states": docs.get("states.yaml"), "kpis": docs.get("kpis.yaml"), "state": docs.get("state.json")}
    report = {"folder": folder.name, "profile": "full_model" if full else "registry_only", "changed": [], "unchanged": [], "errors": []}
    for fn in present:
        p = folder / fn
        raw_b = p.read_bytes()
        assert not raw_b.startswith(b"\xef\xbb\xbf"), f"{p}: BOM не ожидается"
        raw = raw_b.decode("utf-8")
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        try:
            new = patch_json(text, expected[fn]) if fn == "state.json" else patch_yaml(fn, text, ctx)
            got = norm_dates(json.loads(new) if fn == "state.json" else yaml.safe_load(new))
            if got != expected[fn]:
                raise AssertionError("результат построчного патча ≠ эталонной миграции: " + _first_diff(got, expected[fn]))
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"{fn}: {e}")
            continue
        if new == text:
            report["unchanged"].append(fn)
            continue
        report["changed"].append(fn)
        if apply:
            out = new.replace("\n", "\r\n") if crlf else new
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
        print(f"{r['folder']:8} {r['profile']:13} изменено: {', '.join(r['changed']) or '—'} | без изменений: {len(r['unchanged'])}" + (f" | ОШИБКИ: {r['errors']}" if r["errors"] else ""))
    print("режим:", "ЗАПИСЬ" if a.apply else "сухой прогон (ничего не записано)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
