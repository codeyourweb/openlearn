# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)

"""Give every demo questionnaire a title and a summary in the languages it speaks.

The questions of the demo packs are translated (see ``merge_quiz_i18n.py``), but
the catalogue still showed "How the web works — quiz 3" to a German reader: a
half-translated page reads as a broken one, and the demo is the product's public
face. The packs are generated in families ("X — quiz N"), so the wording is
written once per family here and expanded over the numbering.

    python3 tools/merge_quiz_titles.py

Only missing languages are added; a title already translated by hand is kept.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CONTENT = Path(__file__).resolve().parent.parent / "demo" / "content"
LANGUAGES = ("fr", "en", "de", "es")

# family -> {language: name}
NAMES: dict[str, dict[str, str]] = {
    "Mixed revision": {
        "en": "Mixed revision",
        "fr": "Révision mixte",
        "de": "Gemischte Wiederholung",
        "es": "Repaso mixto",
    },
    "Physical geography": {
        "en": "Physical geography",
        "fr": "Géographie physique",
        "de": "Physische Geographie",
        "es": "Geografía física",
    },
    "Turning points of history": {
        "en": "Turning points of history",
        "fr": "Tournants de l'histoire",
        "de": "Wendepunkte der Geschichte",
        "es": "Puntos de inflexión de la historia",
    },
    "Everyday science": {
        "en": "Everyday science",
        "fr": "Sciences du quotidien",
        "de": "Alltagswissenschaft",
        "es": "Ciencia cotidiana",
    },
    "How the web works": {
        "en": "How the web works",
        "fr": "Le web expliqué",
        "de": "Wie das Web funktioniert",
        "es": "Cómo funciona la web",
    },
    "How language models work": {
        "en": "How language models work",
        "fr": "Le fonctionnement des modèles de langage",
        "de": "Wie Sprachmodelle funktionieren",
        "es": "Cómo funcionan los modelos de lenguaje",
    },
    "Sport and training": {
        "en": "Sport and training",
        "fr": "Sport et entraînement",
        "de": "Sport und Training",
        "es": "Deporte y entrenamiento",
    },
    "Reading a work of art": {
        "en": "Reading a work of art",
        "fr": "Lire une œuvre d'art",
        "de": "Ein Kunstwerk lesen",
        "es": "Leer una obra de arte",
    },
    "Health literacy": {
        "en": "Health literacy",
        "fr": "Santé et esprit critique",
        "de": "Gesundheitskompetenz",
        "es": "Alfabetización en salud",
    },
    "Everyday mathematics": {
        "en": "Everyday mathematics",
        "fr": "Mathématiques du quotidien",
        "de": "Alltagsmathematik",
        "es": "Matemáticas cotidianas",
    },
    "Climate and resources": {
        "en": "Climate and resources",
        "fr": "Climat et ressources",
        "de": "Klima und Ressourcen",
        "es": "Clima y recursos",
    },
    "Economics in plain words": {
        "en": "Economics in plain words",
        "fr": "L'économie expliquée simplement",
        "de": "Wirtschaft einfach erklärt",
        "es": "Economía en palabras sencillas",
    },
    "Learning a language": {
        "en": "Learning a language",
        "fr": "Apprendre une langue",
        "de": "Eine Sprache lernen",
        "es": "Aprender un idioma",
    },
    "How music works": {
        "en": "How music works",
        "fr": "Comment fonctionne la musique",
        "de": "Wie Musik funktioniert",
        "es": "Cómo funciona la música",
    },
    "Food, energy and health": {
        "en": "Food, energy and health",
        "fr": "Alimentation, énergie et santé",
        "de": "Ernährung, Energie und Gesundheit",
        "es": "Alimentación, energía y salud",
    },
}

# family -> {language: sentence}, written once for the five-question packs.
GUIDE_SUMMARY = {
    "en": "Five questions drawn from the {name} guide.",
    "fr": "Cinq questions tirées du guide « {name} ».",
    "de": "Fünf Fragen aus dem Leitfaden „{name}“.",
    "es": "Cinco preguntas extraídas de la guía «{name}».",
}

SET_SUMMARY = {
    "en": "Three questions from different subjects: identify the topic before answering.",
    "fr": "Trois questions de matières différentes : identifiez le thème avant de répondre.",
    "de": "Drei Fragen aus verschiedenen Fächern: Erkennen Sie zuerst das Thema.",
    "es": "Tres preguntas de asignaturas distintas: identifica el tema antes de responder.",
}

# Titles that are not part of a numbered family: full translations, including the
# summary, because they carry real editorial content.
SINGLES: dict[str, dict[str, dict[str, str]]] = {
    "Artificial Intelligence Foundations": {
        "en": {
            "title": "Artificial Intelligence Foundations",
            "description": (
                "Ten questions on how modern AI systems are built, trained and evaluated "
                "— no mathematics required."
            ),
        },
        "fr": {
            "title": "Fondements de l'intelligence artificielle",
            "description": (
                "Dix questions sur la façon dont les systèmes d'IA modernes sont construits, "
                "entraînés et évalués — sans mathématiques."
            ),
        },
        "de": {
            "title": "Grundlagen der künstlichen Intelligenz",
            "description": (
                "Zehn Fragen dazu, wie moderne KI-Systeme gebaut, trainiert und bewertet "
                "werden — ohne Mathematik."
            ),
        },
        "es": {
            "title": "Fundamentos de la inteligencia artificial",
            "description": (
                "Diez preguntas sobre cómo se construyen, entrenan y evalúan los sistemas "
                "de IA modernos, sin matemáticas."
            ),
        },
    },
    "Science: The Solar System": {
        "en": {
            "title": "Science: The Solar System",
            "description": (
                "Eight questions on the planets, their moons and the scale of the solar system."
            ),
        },
        "fr": {
            "title": "Sciences : le système solaire",
            "description": (
                "Huit questions sur les planètes, leurs lunes et l'échelle du système solaire."
            ),
        },
        "de": {
            "title": "Wissenschaft: Das Sonnensystem",
            "description": (
                "Acht Fragen zu den Planeten, ihren Monden und den Ausmaßen des Sonnensystems."
            ),
        },
        "es": {
            "title": "Ciencia: el sistema solar",
            "description": (
                "Ocho preguntas sobre los planetas, sus lunas y la escala del sistema solar."
            ),
        },
    },
    "Histoire de France : dates et figures clés": {
        "fr": {
            "title": "Histoire de France : dates et figures clés",
            "description": (
                "Neuf questions sur les dates, les dynasties et les personnages qui ont fait "
                "l'histoire de France."
            ),
        },
        "en": {
            "title": "French history: key dates and figures",
            "description": (
                "Nine questions on the dates, dynasties and figures who shaped the history "
                "of France."
            ),
        },
        "de": {
            "title": "Geschichte Frankreichs: Schlüsseldaten und Persönlichkeiten",
            "description": (
                "Neun Fragen zu Daten, Dynastien und Persönlichkeiten, die die Geschichte "
                "Frankreichs geprägt haben."
            ),
        },
        "es": {
            "title": "Historia de Francia: fechas y figuras clave",
            "description": (
                "Nueve preguntas sobre las fechas, dinastías y personajes que marcaron la "
                "historia de Francia."
            ),
        },
    },
    "Littérature française : les grands classiques": {
        "fr": {
            "title": "Littérature française : les grands classiques",
            "description": (
                "Neuf questions sur les romans, les pièces et les poètes que l'on étudie "
                "encore au lycée, de Molière à Proust."
            ),
        },
        "en": {
            "title": "French literature: the great classics",
            "description": (
                "Nine questions on the novels, plays and poets still taught at school, "
                "from Molière to Proust."
            ),
        },
        "de": {
            "title": "Französische Literatur: die großen Klassiker",
            "description": (
                "Neun Fragen zu den Romanen, Stücken und Dichtern, die noch heute in der "
                "Schule gelesen werden, von Molière bis Proust."
            ),
        },
        "es": {
            "title": "Literatura francesa: los grandes clásicos",
            "description": (
                "Nueve preguntas sobre las novelas, obras de teatro y poetas que todavía "
                "se estudian en el instituto, de Molière a Proust."
            ),
        },
    },
}

NUMBERED = re.compile(r"^(?P<family>.+?) — (?:quiz|set) (?P<number>\d+)$")

SUFFIX = {"en": "quiz", "fr": "questionnaire", "de": "Quiz", "es": "cuestionario"}
SET_SUFFIX = {"en": "set", "fr": "série", "de": "Reihe", "es": "serie"}


def spoken_by(item: dict) -> set[str]:
    """The languages this questionnaire genuinely speaks, questions included.

    A title in German over questions that only exist in English advertises
    something the reader never gets, so a title translation is gated on the
    content actually carrying that language.
    """
    languages = {item.get("default_language") or "en"}
    for question in item["questions"]:
        languages |= set((question.get("translations") or {}).keys())
        for option in question.get("options", []):
            languages |= set((option.get("translations") or {}).keys())
    return languages


def translations_for(title: str) -> dict[str, dict[str, str]] | None:
    """Return {language: {title, description}} for one demo title, or None."""
    if title in SINGLES:
        return SINGLES[title]
    match = NUMBERED.match(title)
    if not match:
        return None
    family = match.group("family")
    number = match.group("number")
    if family not in NAMES:
        return None
    names = NAMES[family]
    is_set = " — set " in title
    spoken: dict[str, dict[str, str]] = {}
    for language in LANGUAGES:
        suffix = (SET_SUFFIX if is_set else SUFFIX)[language]
        summary = SET_SUMMARY if is_set else GUIDE_SUMMARY
        spoken[language] = {
            "title": f"{names[language]} — {suffix} {number}",
            "description": summary[language].format(name=names[language]),
        }
    return spoken


def main() -> int:
    touched = 0
    added = 0
    for path in sorted(CONTENT.glob("quizzes*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        items = document["items"] if isinstance(document, dict) else document
        changed = False
        for item in items:
            offered = translations_for(item["title"])
            if not offered:
                continue
            spoken = spoken_by(item)
            original_titles = dict(item.get("title_translations") or {})
            original_summaries = dict(item.get("description_translations") or {})
            # A language the questions do not carry is dropped from the title too:
            # a translated heading over an English question is a broken promise.
            titles = {
                language: value
                for language, value in original_titles.items()
                if language in spoken
            }
            summaries = {
                language: value
                for language, value in original_summaries.items()
                if language in spoken
            }
            for language, values in offered.items():
                if language == item.get("default_language") or language not in spoken:
                    continue
                titles.setdefault(language, values["title"])
                summaries.setdefault(language, values["description"])
            if (titles, summaries) != (original_titles, original_summaries):
                item["title_translations"] = titles
                item["description_translations"] = summaries
                added += sum(1 for language in titles if language not in original_titles)
                changed = True
        if changed:
            touched += 1
            if isinstance(document, dict):
                document["items"] = items
                payload = document
            else:
                payload = items
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    print(f"{added} translations added across {touched} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
