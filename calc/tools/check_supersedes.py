"""Проверка полноты замены норматива при переиздании (приёмка от IMMA, правило 23.09.2026: «переиздание = полный текст
предыдущей версии + дельта»). Сравнивает деревья двух YAML/JSON-файлов (старая и новая версия) и печатает всё, что в новой
версии ПРОПАЛО: ключи словарей, записи списков (по id / path / rule / file / name, иначе по значению для скаляров), — на
любой глубине. Изменённые значения только считаются и показываются как справка (версии, даты, описания меняются
законно); пропажа без явного разрешения (--allow <путь>) — отказ (код возврата 1).

Схемная валидация и живые отчёты проходят и при выпавших разделах (случай Dozor v1.2: пропали principles, kpi_rules,
runtime_write_rules …) — поэтому проверка деревьев обязательна на каждой приёмке вместе с валидатором.

Использование:
  python calc/tools/check_supersedes.py <старый.yaml> <новый.yaml> [--allow a.b.c ...] [--json] [--show-changed]
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import yaml

ID_KEYS = ("id", "path", "rule", "file", "name", "kpi_id", "trigger_id", "axis_id")


def _load(p: Path):
    text = p.read_text(encoding="utf-8")
    return json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)


def _key(item):
    if isinstance(item, dict):
        for k in ID_KEYS:
            if k in item and isinstance(item[k], (str, int)):
                return f"{k}={item[k]}"
        return None
    if isinstance(item, (str, int, float, bool)) or item is None:
        return repr(item)
    return None


def _same_scalar(a, b) -> bool:
    if isinstance(a, (datetime.date, datetime.datetime)):
        a = a.isoformat()
    if isinstance(b, (datetime.date, datetime.datetime)):
        b = b.isoformat()
    return a == b


def compare(old, new, path: str = "$") -> tuple[list[str], list[str]]:
    """→ (removed, changed): пути пропавших узлов и пути изменённых скаляров."""
    removed: list[str] = []
    changed: list[str] = []
    if isinstance(old, dict):
        if not isinstance(new, dict):
            removed.append(f"{path} (словарь заменён на {type(new).__name__})")
            return removed, changed
        for k, v in old.items():
            if k not in new:
                removed.append(f"{path}.{k}")
            else:
                r, c = compare(v, new[k], f"{path}.{k}")
                removed += r
                changed += c
        return removed, changed
    if isinstance(old, list):
        if not isinstance(new, list):
            removed.append(f"{path} (список заменён на {type(new).__name__})")
            return removed, changed
        keyed_old = {_key(x): x for x in old if _key(x) is not None}
        keyed_new = {_key(x): x for x in new if _key(x) is not None}
        for k, v in keyed_old.items():
            if k not in keyed_new:
                removed.append(f"{path}[{k}]")
            elif isinstance(v, dict):
                r, c = compare(v, keyed_new[k], f"{path}[{k}]")
                removed += r
                changed += c
        unkeyed_old = [x for x in old if _key(x) is None]
        unkeyed_new = [x for x in new if _key(x) is None]
        if len(unkeyed_new) < len(unkeyed_old):
            removed.append(f"{path} (безымянных записей было {len(unkeyed_old)}, стало {len(unkeyed_new)})")
        for i, (a, b) in enumerate(zip(unkeyed_old, unkeyed_new)):
            r, c = compare(a, b, f"{path}[#{i}]")
            removed += r
            changed += c
        return removed, changed
    if not _same_scalar(old, new):
        changed.append(path)
    return removed, changed


def deref(node, root, depth: int = 0):
    """Раскрывает внутренние JSON-Schema ссылки {"$ref": "#/..."} по документу root: вынос схемы записи в $defs — рефакторинг,
    а не пропажа (случай output_report_schema v1.2: items.items → $ref '#/$defs/kpi_item'). Глубина ограничена от циклов."""
    if depth > 12:
        return node
    roots = root if isinstance(root, list) else [root]
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/") and len(node) == 1:
            for r in roots:  # ссылка относительна корню СХЕМЫ (узел с $defs/$schema), который может быть вложен в YAML-документ
                target = r
                for part in ref[2:].split("/"):
                    target = target.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(target, dict) else None
                    if target is None:
                        break
                if target is not None:
                    return deref(target, roots, depth + 1)
            return node
        return {k: deref(v, roots, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [deref(v, roots, depth + 1) for v in node]
    return node


def _schema_roots(d, acc: list) -> list:
    """Документ + все вложенные узлы с $defs/$schema (корни JSON Schema внутри YAML-норматива)."""
    if isinstance(d, dict):
        if "$defs" in d or "$schema" in d:
            acc.append(d)
        for v in d.values():
            _schema_roots(v, acc)
    elif isinstance(d, list):
        for v in d:
            _schema_roots(v, acc)
    return acc


def _load_deref(p: Path):
    d = _load(p)
    return deref(d, [d] + _schema_roots(d, []))


def check(old_path: Path, new_path: Path, allow: list[str] | None = None) -> dict:
    removed, changed = compare(_load_deref(old_path), _load_deref(new_path))
    allow = allow or []
    allowed = [r for r in removed if any(r == a or r.startswith(a + ".") or r.startswith(a + "[") for a in allow)]
    blocking = [r for r in removed if r not in allowed]
    return {"old": str(old_path), "new": str(new_path), "removed": blocking, "removed_allowed": allowed, "changed": changed,
            "pass": not blocking}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--allow", nargs="*", default=[], help="пути ($.a.b, $.list[id=X]), пропажа которых разрешена явным решением")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-changed", action="store_true")
    a = ap.parse_args(argv)
    r = check(Path(a.old), Path(a.new), a.allow)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"{Path(a.old).name} → {Path(a.new).name}: пропало {len(r['removed'])} (разрешено {len(r['removed_allowed'])}), изменено значений {len(r['changed'])}")
        for x in r["removed"]:
            print("  ПРОПАЛО:", x)
        for x in r["removed_allowed"]:
            print("  пропало (разрешено):", x)
        if a.show_changed:
            for x in r["changed"]:
                print("  изменено:", x)
        print("итог:", "OK — полнота замены подтверждена" if r["pass"] else "ОТКАЗ — переиздание неполное (нужен полный текст + дельта или явное решение --allow)")
    return 0 if r["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
