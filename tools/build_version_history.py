"""Собирает историю версий из installer/release-notes-*.json.

Манифест обновлений несёт заметки только текущей версии, поэтому история
складывается локально и уезжает в пакет вместе с интерфейсом. Так раздел
«Обновления» показывает прошлые выпуски и без связи с сервером.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.update_manifest import version as parse_version

SOURCE = ROOT / "installer"
TARGET = ROOT / "ui" / "static" / "version-history.json"
PATTERN = re.compile(r"^release-notes-(\d+\.\d+\.\d+)\.json$")


def collect():
    entries = []
    for path in sorted(SOURCE.glob("release-notes-*.json")):
        match = PATTERN.match(path.name)
        if not match:
            continue
        try:
            notes = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(notes, list):
            continue
        # Точной даты выпуска в заметках нет; берём время файла — оно
        # соответствует моменту подготовки релиза.
        released = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        entries.append({
            "version": match.group(1),
            "notes": [str(note) for note in notes if str(note).strip()],
            "released": released.strftime("%d.%m.%Y"),
        })
    entries.sort(key=lambda item: parse_version(item["version"]), reverse=True)
    return entries


def main():
    entries = collect()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"file": str(TARGET), "versions": len(entries)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
