"""Generate SadnessVPN's Flowseal profile table from the official batch files."""

from __future__ import annotations

import argparse
import hashlib
import pprint
import shlex
import subprocess
from pathlib import Path


PROFILE_SPECS = (
    ("general.bat", "flowseal_general", "General", "Основная", "Основная рекомендуемая стратегия Flowseal"),
    ("general (ALT).bat", "flowseal_alt", "ALT", "ALT", "Альтернативная стратегия Flowseal · вариант 1"),
    ("general (ALT2).bat", "flowseal_alt2", "ALT 2", "ALT", "Альтернативная стратегия Flowseal · вариант 2"),
    ("general (ALT3).bat", "flowseal_alt3", "ALT 3", "ALT", "Альтернативная стратегия Flowseal · вариант 3"),
    ("general (ALT4).bat", "flowseal_alt4", "ALT 4", "ALT", "Альтернативная стратегия Flowseal · вариант 4"),
    ("general (ALT5).bat", "flowseal_alt5", "ALT 5", "ALT", "Не рекомендуется upstream · только для ручного тестирования"),
    ("general (ALT6).bat", "flowseal_alt6", "ALT 6", "ALT", "Альтернативная стратегия Flowseal · вариант 6"),
    ("general (ALT7).bat", "flowseal_alt7", "ALT 7", "ALT", "Альтернативная стратегия Flowseal · вариант 7"),
    ("general (ALT8).bat", "flowseal_alt8", "ALT 8", "ALT", "Альтернативная стратегия Flowseal · вариант 8"),
    ("general (ALT9).bat", "flowseal_alt9", "ALT 9", "ALT", "Альтернативная стратегия Flowseal · вариант 9"),
    ("general (ALT10).bat", "flowseal_alt10", "ALT 10", "ALT", "Альтернативная стратегия Flowseal · вариант 10"),
    ("general (ALT11).bat", "flowseal_alt11", "ALT 11", "ALT", "Альтернативная стратегия Flowseal · вариант 11"),
    ("general (ALT12).bat", "flowseal_alt12", "ALT 12", "ALT", "Альтернативная стратегия Flowseal · вариант 12"),
    ("general (ALT13).bat", "flowseal_alt13", "ALT 13", "ALT", "Альтернативная стратегия Flowseal · вариант 13"),
    ("general (FAKE TLS AUTO).bat", "flowseal_fake_tls_auto", "Fake TLS Auto", "Fake TLS", "Автоматическая подмена TLS для сложной фильтрации"),
    ("general (FAKE TLS AUTO ALT).bat", "flowseal_fake_tls_auto_alt", "Fake TLS Auto ALT", "Fake TLS", "Fake TLS Auto · альтернативный вариант 1"),
    ("general (FAKE TLS AUTO ALT2).bat", "flowseal_fake_tls_auto_alt2", "Fake TLS Auto ALT 2", "Fake TLS", "Fake TLS Auto · альтернативный вариант 2"),
    ("general (FAKE TLS AUTO ALT3).bat", "flowseal_fake_tls_auto_alt3", "Fake TLS Auto ALT 3", "Fake TLS", "Fake TLS Auto · альтернативный вариант 3"),
    ("general (SIMPLE FAKE).bat", "flowseal_simple_fake", "Simple Fake", "Simple Fake", "Упрощённая стратегия с подменой пакетов"),
    ("general (SIMPLE FAKE ALT).bat", "flowseal_simple_fake_alt", "Simple Fake ALT", "Simple Fake", "Simple Fake · альтернативный вариант 1"),
    ("general (SIMPLE FAKE ALT2).bat", "flowseal_simple_fake_alt2", "Simple Fake ALT 2", "Simple Fake", "Simple Fake · альтернативный вариант 2"),
    ("general (EXP).bat", "flowseal_exp", "EXP", "Экспериментальные", "Экспериментальная стратегия Flowseal"),
)


def _command_args(batch_file: Path) -> tuple[str, ...]:
    lines = batch_file.read_text(encoding="utf-8-sig").splitlines()
    start_index = next(
        index for index, line in enumerate(lines) if '"%BIN%winws.exe"' in line
    )
    command_lines: list[str] = []
    for line in lines[start_index:]:
        stripped = line.strip()
        continued = stripped.endswith("^")
        command_lines.append(stripped[:-1].rstrip() if continued else stripped)
        if not continued:
            break

    tokens = shlex.split(" ".join(command_lines), posix=True)
    executable_index = next(
        index for index, token in enumerate(tokens) if token.endswith("winws.exe")
    )
    args = []
    for token in tokens[executable_index + 1 :]:
        token = token.replace("%GameFilterTCP%", "12")
        token = token.replace("%GameFilterUDP%", "12")
        token = token.replace("^!", "!")
        args.append(token)

    unresolved = [arg for arg in args if "%" in arg and "%BIN%" not in arg and "%LISTS%" not in arg]
    if unresolved:
        raise ValueError(f"Unresolved variables in {batch_file.name}: {unresolved}")
    if any("^" in arg for arg in args):
        raise ValueError(f"Unresolved cmd escaping in {batch_file.name}")
    return tuple(args)


def _tags(args: tuple[str, ...], category: str) -> tuple[str, ...]:
    joined = " ".join(args)
    tags = ["Discord", "YouTube"]
    mechanisms = (
        ("multisplit", "Multisplit"),
        ("multidisorder", "Multidisorder"),
        ("hostfakesplit", "Host split"),
        ("fakedsplit", "Fake split"),
        ("syndata", "Syndata"),
        ("--dpi-desync-fake-tls", "Fake TLS"),
    )
    for needle, label in mechanisms:
        if needle in joined and label not in tags:
            tags.append(label)
        if len(tags) == 4:
            break
    if category == "Экспериментальные":
        tags[-1:] = ["Тестовый"]
    return tuple(tags)


def generate(source_root: Path, output_file: Path) -> None:
    missing = [name for name, *_ in PROFILE_SPECS if not (source_root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing upstream profiles: {', '.join(missing)}")

    commit = subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    profiles = []
    for source_name, profile_id, name, category, description in PROFILE_SPECS:
        source_file = source_root / source_name
        args = _command_args(source_file)
        experimental = category == "Экспериментальные" or "NOT RECOMMENDED" in source_file.read_text(encoding="utf-8-sig")
        profiles.append(
            {
                "id": profile_id,
                "name": name,
                "category": category,
                "desc": description,
                "icon": "!" if experimental else ("◇" if "Fake" in category else "✦"),
                "tags": _tags(args, "Экспериментальные" if experimental else category),
                "experimental": experimental,
                "source_file": source_name,
                "source_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
                "args": args,
            }
        )

    rendered = (
        '"""Generated Flowseal strategy data. Do not edit by hand.\n\n'
        "Run tools/sync_flowseal_profiles.py against the official repository.\n"
        '"""\n\n'
        f'FLOWSEAL_SOURCE = "https://github.com/Flowseal/zapret-discord-youtube"\n'
        f'FLOWSEAL_COMMIT = "{commit}"\n\n'
        "FLOWSEAL_PROFILES = "
        + pprint.pformat(tuple(profiles), width=120, sort_dicts=False)
        + "\n\nPROFILE_BY_ID = {profile['id']: profile for profile in FLOWSEAL_PROFILES}\n"
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(rendered, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Path to a clone of Flowseal/zapret-discord-youtube")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "engine" / "flowseal_profiles.py",
    )
    args = parser.parse_args()
    generate(args.source.resolve(), args.output.resolve())
    print(f"Generated {len(PROFILE_SPECS)} profiles in {args.output}")


if __name__ == "__main__":
    main()
