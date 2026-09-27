"""Проверка документа (YAML/JSON) по JSON Schema Draft 2020-12 — для нормативных пакетов IMMA (каталог событий, состояние сценариев,
реестр оснований Lifecycle и т. п.), когда у artifact_validator нет отдельного режима. Использование:
  python calc/tools/check_schema.py <schema.yaml|json> <doc.yaml|json> [...ещё документы]   → код 1, если есть ошибки."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


def load(p: str):
    t = Path(p).read_text(encoding="utf-8")
    return json.loads(t) if p.endswith(".json") else yaml.safe_load(t)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__); return 2
    v = Draft202012Validator(load(argv[0])); bad = 0
    for d in argv[1:]:
        errs = sorted(v.iter_errors(load(d)), key=lambda e: list(e.path))
        print(f"{Path(d).name}: {'OK' if not errs else str(len(errs)) + ' ошибок'}")
        for e in errs[:10]:
            print(f"   {'/'.join(str(x) for x in e.path) or '<root>'}: {e.message[:140]}")
        bad += len(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
