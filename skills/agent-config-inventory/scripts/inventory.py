#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Inventory an agent configuration and report what is actually in force.

Guidance accumulates in several shapes that look interchangeable but behave very
differently: a skill loads on demand, a rule loads every session, a note is read
only when something points at it, and a hook is the only shape the runtime
enforces. Drift is normal and invisible, so this script reports the shapes and
checks the claims rather than trusting them.

Checks:

  inventory        How many skills, commands, rules, notes and hooks exist, and where.
  asserted-hooks   Text that claims a hook enforces something, against the hooks the
                   settings actually register. A hook file that exists but is not
                   registered does nothing.
  commands         Files under commands/, which are invocable but cannot carry a
                   directory, supporting files, or invocation controls.
  secret-shaped    Settings entries that appear to embed a credential value.
  dead-paths       Filesystem paths referenced by notes that no longer exist.

Exit code is 1 when a claim could not be substantiated, 0 otherwise.
Standard library only. Values of secret-shaped entries are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HOOK_REFERENCE = re.compile(r"hooks[/\\]([A-Za-z0-9_.-]+\.py)")
# Words that turn a mention of a hook into a claim that it is in force.
ENFORCEMENT_CLAIM = re.compile(
    r"(?:拒否|ブロック|止める|阻止|強制|enforce|block|reject|prevent|gates\b)"
)
# Words that disclose the hook is not active, which makes a mention honest.
ENFORCEMENT_DISCLAIMED = re.compile(
    r"(?:有効にしていない|未整備|無効|not enabled|disabled|未登録|未配線)"
)
SECRET_REFERENCE = re.compile(
    # Commands that FETCH a secret from a store name it; they do not embed a value.
    # Counting them keeps the report noisy, which is how a check gets ignored.
    r"(?i)(?:gcloud\s+secrets\s+versions\s+access"
    r"|aws\s+secretsmanager\s+get-secret-value"
    r"|vault\s+(?:kv\s+)?(?:read|get))"
)
SECRET_SHAPED = re.compile(
    # No \b before the keyword: a name such as SERVICE_PASSWORD has a word
    # character before "PASSWORD", so \b would miss exactly the case that matters.
    r"(?i)([A-Za-z0-9_]*(?:password|passwd|secret|token|api[_-]?key|credential))"
    r"\s*=\s*['\"]?[^\s'\"&|;]{6,}"
)
PATH_REFERENCE = re.compile(r"`(~[/\\][^`]+|[A-Za-z]:[/\\][^`]+)`")
SETTINGS_NAMES = ("settings.json", "settings.local.json")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def settings_files(home: Path, extra: list[Path]) -> list[Path]:
    found = [home / name for name in SETTINGS_NAMES]
    return [path for path in [*found, *extra] if path.is_file()]


def registered_hooks(paths: list[Path]) -> dict[str, list[str]]:
    """Map settings file name to the hook commands it registers."""
    registered: dict[str, list[str]] = {}
    for path in paths:
        commands: list[str] = []
        for entries in (load_json(path).get("hooks") or {}).values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
                    command = hook.get("command") if isinstance(hook, dict) else None
                    if command:
                        commands.append(str(command))
        registered[path.name] = commands
    return registered


def text_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def find_memory_dirs(home: Path, explicit: Path | None) -> list[Path]:
    if explicit:
        return [explicit] if explicit.is_dir() else []
    projects = home / "projects"
    if not projects.is_dir():
        return []
    return sorted(p / "memory" for p in projects.iterdir() if (p / "memory").is_dir())


def note_type(path: Path) -> str:
    match = re.search(r"^\s*type:\s*(\w+)", path.read_text(encoding="utf-8", errors="replace"), re.M)
    return match.group(1) if match else "untyped"


def build_report(home: Path, memory_dir: Path | None, extra_settings: list[Path]) -> dict:
    home = home.expanduser()
    skills = sorted(
        p.parent.name for p in (home / "skills").glob("*/SKILL.md") if p.is_file()
    )
    commands = sorted(p.name for p in (home / "commands").glob("*.md") if p.is_file())
    rules = sorted(p.name for p in (home / "rules").glob("*.md") if p.is_file())
    hook_files = sorted(p.name for p in (home / "hooks").glob("*.py") if p.is_file())

    memory_dirs = find_memory_dirs(home, memory_dir)
    notes: list[Path] = []
    for directory in memory_dirs:
        notes.extend(p for p in directory.glob("*.md") if p.name != "MEMORY.md")
    by_type: dict[str, int] = {}
    for note in notes:
        by_type[note_type(note)] = by_type.get(note_type(note), 0) + 1

    settings = settings_files(home, extra_settings)
    hooks_by_file = registered_hooks(settings)
    all_registered = " ".join(command for commands_ in hooks_by_file.values() for command in commands_)

    # Text that claims a hook does something.
    searched = [*notes, *text_files(home / "skills"), *text_files(home / "rules")]
    claims: list[dict] = []
    for path in searched:
        body = path.read_text(encoding="utf-8", errors="replace")
        for name in sorted(set(HOOK_REFERENCE.findall(body))):
            exists = (home / "hooks" / name).is_file()
            wired = name in all_registered
            if exists and wired:
                continue
            asserts = bool(ENFORCEMENT_CLAIM.search(body))
            disclaims = bool(ENFORCEMENT_DISCLAIMED.search(body))
            claims.append(
                {
                    "claimed_by": path.name,
                    "hook": name,
                    "file_exists": exists,
                    "registered": wired,
                    "state": "not registered" if exists else "file missing",
                    # A document that says the hook is off is accurate, not a defect.
                    "severity": "contradiction" if asserts and not disclaims else "mention",
                }
            )

    # Settings entries that look like they embed a credential.
    secret_shaped: list[dict] = []
    for path in settings:
        data = load_json(path)
        allow = (data.get("permissions") or {}).get("allow") or []
        for index, rule in enumerate(allow):
            if not isinstance(rule, str) or SECRET_REFERENCE.search(rule):
                continue
            if SECRET_SHAPED.search(rule):
                key = SECRET_SHAPED.search(rule).group(1)
                secret_shaped.append(
                    {"settings": path.name, "index": index, "key": key, "value_shown": False}
                )
        for key, value in (data.get("env") or {}).items():
            if SECRET_SHAPED.search("%s=%s" % (key, value)):
                secret_shaped.append(
                    {"settings": path.name, "index": None, "key": key, "value_shown": False}
                )

    # Paths referenced by notes that no longer exist.
    dead_paths: list[dict] = []
    for note in notes:
        body = note.read_text(encoding="utf-8", errors="replace")
        for raw in sorted(set(PATH_REFERENCE.findall(body))):
            candidate = Path(os.path.expanduser(raw.replace("\\", "/")))
            if any(ch in raw for ch in "*?<>{}") or raw.rstrip("/\\").endswith("…"):
                continue
            if not candidate.exists():
                dead_paths.append({"note": note.name, "path": raw})

    return {
        "home": str(home),
        "counts": {
            "skills": len(skills),
            "commands": len(commands),
            "rules": len(rules),
            "notes": len(notes),
            "hook_files": len(hook_files),
            "hooks_registered": sum(len(v) for v in hooks_by_file.values()),
        },
        "skills": skills,
        "commands": commands,
        "rules": rules,
        "notes_by_type": dict(sorted(by_type.items())),
        "hook_files": hook_files,
        "hooks_registered": hooks_by_file,
        "unsubstantiated_hook_claims": claims,
        "secret_shaped_settings": secret_shaped,
        "dead_paths": dead_paths,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Report what an agent configuration enforces.")
    parser.add_argument("--home", type=Path, default=Path.home() / ".claude")
    parser.add_argument("--memory-dir", type=Path, default=None)
    parser.add_argument(
        "--settings",
        type=Path,
        action="append",
        default=[],
        help="additional settings file to consider (project or policy scope)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args.home, args.memory_dir, args.settings)
    contradictions = [
        claim
        for claim in report["unsubstantiated_hook_claims"]
        if claim["severity"] == "contradiction"
    ]
    problems = len(contradictions) + len(report["secret_shaped_settings"])

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if problems else 0

    counts = report["counts"]
    print("agent configuration: %s" % report["home"])
    print(
        "  skills %d | commands %d | rules %d | notes %d | hook files %d | hooks registered %d"
        % (
            counts["skills"],
            counts["commands"],
            counts["rules"],
            counts["notes"],
            counts["hook_files"],
            counts["hooks_registered"],
        )
    )
    if report["notes_by_type"]:
        print(
            "  notes by type: %s"
            % ", ".join("%s %d" % item for item in report["notes_by_type"].items())
        )
    if report["commands"]:
        print("\ncommands (invocable, but cannot carry supporting files or invocation controls):")
        for name in report["commands"]:
            print("  - %s" % name)
    if report["unsubstantiated_hook_claims"]:
        print("\nHOOKS referenced by text but not in force:")
        for claim in report["unsubstantiated_hook_claims"]:
            label = "CONTRADICTION" if claim["severity"] == "contradiction" else "mention only"
            print(
                "  - [%s] %s -> %s (%s, file_exists=%s, registered=%s)"
                % (
                    label,
                    claim["claimed_by"],
                    claim["hook"],
                    claim["state"],
                    claim["file_exists"],
                    claim["registered"],
                )
            )
    if report["secret_shaped_settings"]:
        print("\nSECRET-SHAPED settings entries (value intentionally not printed):")
        for item in report["secret_shaped_settings"]:
            where = (
                "permissions.allow[%d]" % item["index"] if item["index"] is not None else "env"
            )
            print("  - %s %s key=%s" % (item["settings"], where, item["key"]))
    if report["dead_paths"]:
        print("\nDEAD PATHS referenced by notes:")
        for item in report["dead_paths"][:20]:
            print("  - %s -> %s" % (item["note"], item["path"]))
        if len(report["dead_paths"]) > 20:
            print("  ... and %d more" % (len(report["dead_paths"]) - 20))
    if problems:
        print("\n%d claim(s) could not be substantiated." % problems)
    else:
        print("\nNo unsubstantiated claim found in the inspected scope.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
