# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Fold the per-question translations into the demo questionnaire package.

The questions and their options are written in `quizzes-paired.json`; their
translations live in `quiz-i18n/*.json`, one block per questionnaire and per
question. Keeping them apart makes a translation reviewable on its own, but the
seeder reads a single file, so this script merges them.

    python tools/merge_quiz_i18n.py          # write
    python tools/merge_quiz_i18n.py --check  # verify only

Every language named by a questionnaire must cover every question and every
option: a half-translated quiz shows French answers under a German question,
which is worse than no translation at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "demo" / "content"
PACKAGE = CONTENT / "quizzes-paired.json"
TRANSLATIONS = CONTENT / "quiz-i18n"


def load_translations() -> dict[str, dict[int, dict]]:
    """Read every translation block, keyed by demo file then questionnaire index."""
    blocks: dict[str, dict[int, dict]] = {}
    for path in sorted(TRANSLATIONS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for block in data:
            target = block.get("file") or PACKAGE.name
            index = int(block["index"])
            per_file = blocks.setdefault(target, {})
            if index in per_file:
                raise SystemExit(f"{path.name}: {target} questionnaire {index} translated twice")
            per_file[index] = block["questions"]
    return blocks


def merge(package: dict, blocks: dict[int, dict[str, dict]], *, target: str) -> int:
    items = package["items"]
    written = 0
    for index, questions in sorted(blocks.items()):
        if index >= len(items):
            raise SystemExit(f"{target}: questionnaire {index} is out of range ({len(items)} items)")
        quiz = items[index]
        default = quiz["default_language"]
        for q_index, translations in sorted(questions.items(), key=lambda kv: int(kv[0])):
            position = int(q_index)
            if position >= len(quiz["questions"]):
                raise SystemExit(f"{target}: questionnaire {index} question {position} is out of range")
            question = quiz["questions"][position]
            for language, payload in translations.items():
                if language == default:
                    raise SystemExit(f"questionnaire {index} q{position}: {language} is the original")
                if len(payload["options"]) != len(question["options"]):
                    raise SystemExit(
                        f"questionnaire {index} q{position} {language}: "
                        f"{len(payload['options'])} answers for {len(question['options'])} options"
                    )
                if not payload["text"].strip():
                    raise SystemExit(f"questionnaire {index} q{position} {language}: empty question")
                question.setdefault("translations", {})[language] = payload["text"]
                for option, text in zip(question["options"], payload["options"], strict=True):
                    if not str(text).strip():
                        raise SystemExit(
                            f"questionnaire {index} q{position} {language}: empty answer"
                        )
                    option.setdefault("translations", {})[language] = text
                written += 1
    return written


def main() -> int:
    check = "--check" in sys.argv[1:]
    blocks = load_translations()
    written = 0
    for target, per_file in blocks.items():
        path = CONTENT / target
        package = json.loads(path.read_text(encoding="utf-8"))
        written += merge(package, per_file, target=target)
        if not check:
            path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{target}: translations merged")
    print(f"{written} translated questions {'checked' if check else 'merged'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
