"""Third batch: short method guides, plus interleaved revision quizzes.

The guides are single-topic wikis — how to study, take notes, read a paper — that
do not belong to a discipline. The quizzes mix facts from every theme on purpose:
interleaving forces the reader to recognise the subject before answering.
"""

from __future__ import annotations

import random
from typing import Any

MINI_WIKIS: list[dict[str, Any]] = [
    {
        "slug": "study-methods",
        "title": "Study methods that work",
        "description": "Retrieval, spacing and interleaving, and why rereading feels better than it works.",
        "language": "en",
        "pages": [
            {
                "slug": "retrieval-and-spacing",
                "title": "Retrieval and spacing",
                "markdown": (
                    "# Retrieval and spacing\n\n"
                    "Testing yourself works better than rereading, because remembering is the "
                    "skill you are training. Close the book and write what you recall; the "
                    "effort of reconstruction is what consolidates the material.\n\n"
                    "Space the reviews instead of repeating them in one sitting. Forgetting a "
                    "little between sessions is useful: the second retrieval is harder and "
                    "therefore worth more.\n\n"
                    "**In practice** — three short self-tests across a week beat one long "
                    "rereading session.\n"
                ),
            },
            {
                "slug": "interleaving",
                "title": "Interleaving and feedback",
                "markdown": (
                    "# Interleaving and feedback\n\n"
                    "Practise related topics in mixed order. Blocked practice (ten of the same "
                    "exercise) feels smoother, but mixed practice teaches you to choose the "
                    "method, which is what an exam or a real problem asks for.\n\n"
                    "Seek feedback quickly. A correction applied while the attempt is still "
                    "fresh changes the next attempt; the same correction a week later mostly "
                    "changes nothing.\n"
                ),
                "parent": "retrieval-and-spacing",
            },
        ],
    },
    {
        "slug": "note-taking",
        "title": "Note-taking that survives",
        "description": "Notes as a tool for thinking, not a transcript of the lesson.",
        "language": "en",
        "pages": [
            {
                "slug": "notes-as-thinking",
                "title": "Notes as thinking",
                "markdown": (
                    "# Notes as thinking\n\n"
                    "A transcript copies; a note transforms. Write in your own words, leave "
                    "space for a question, and mark what you did not understand — those marks "
                    "are the most valuable part of the page.\n\n"
                    "One page, one idea. If a page needs three titles, it is three pages.\n"
                ),
            },
            {
                "slug": "revisiting",
                "title": "Revisiting notes",
                "markdown": (
                    "# Revisiting notes\n\n"
                    "Notes that are never reopened are archives, not tools. A short pass a day "
                    "later, then a week later, converts them into memory; a summary written from "
                    "memory is better still.\n\n"
                    "Link notes to each other. A link you create is a connection you have "
                    "already understood.\n"
                ),
                "parent": "notes-as-thinking",
            },
        ],
    },
    {
        "slug": "asking-questions",
        "title": "Asking better questions",
        "description": "Turning a vague difficulty into a question someone can answer.",
        "language": "en",
        "pages": [
            {
                "slug": "the-question",
                "title": "What makes a question answerable",
                "markdown": (
                    "# What makes a question answerable\n\n"
                    "A good question states what you tried, what you expected and what "
                    "happened. That triad lets someone else reproduce the problem, and often "
                    "makes the answer obvious to you before it arrives.\n\n"
                    "Ask one question at a time. A message with four questions gets one answer.\n"
                ),
            },
            {
                "slug": "answering-well",
                "title": "Answering well",
                "markdown": (
                    "# Answering well\n\n"
                    "Answer the question that was asked, then add context if it changes the "
                    "answer. Saying 'it depends' without saying what it depends on is not an "
                    "answer.\n\n"
                    "When you do not know, say so and say how you would find out.\n"
                ),
                "parent": "the-question",
            },
        ],
    },
    {
        "slug": "reading-a-paper",
        "title": "Reading a scientific paper",
        "description": "A reading order that finds the claim, the evidence and the limits.",
        "language": "en",
        "pages": [
            {
                "slug": "reading-order",
                "title": "A reading order",
                "markdown": (
                    "# A reading order\n\n"
                    "Start with the abstract, then the last paragraph of the introduction, then "
                    "the figures. If the claim survives that, read the methods: who was "
                    "studied, how many, and compared with what.\n\n"
                    "The discussion is the authors' interpretation, not their result. Keep the "
                    "two apart in your notes.\n"
                ),
            },
            {
                "slug": "limits",
                "title": "Finding the limits",
                "markdown": (
                    "# Finding the limits\n\n"
                    "Every study has a population, a size and a duration. Ask how far the "
                    "finding travels beyond them: a result in twenty students over two weeks is "
                    "a hypothesis, not a rule.\n\n"
                    "Note what the authors did not measure — it is often the most interesting "
                    "part of the paper.\n"
                ),
                "parent": "reading-order",
            },
        ],
    },
    {
        "slug": "giving-feedback",
        "title": "Giving feedback people can use",
        "description": "Specific, timely and about the work rather than the person.",
        "language": "en",
        "pages": [
            {
                "slug": "specific-and-timely",
                "title": "Specific and timely",
                "markdown": (
                    "# Specific and timely\n\n"
                    "'This paragraph is unclear' is an opinion; 'I lost the thread at the third "
                    "sentence, where the subject changes' is an observation the author can act "
                    "on.\n\n"
                    "Give feedback while the work is still being made. A remark on a finished "
                    "project is a verdict, not a help.\n"
                ),
            },
            {
                "slug": "receiving-feedback",
                "title": "Receiving feedback",
                "markdown": (
                    "# Receiving feedback\n\n"
                    "Ask for the kind of feedback you want: on structure, on clarity, on "
                    "accuracy. A vague request produces a vague answer.\n\n"
                    "Thank the reader, then decide. Feedback is information, not an order.\n"
                ),
                "parent": "specific-and-timely",
            },
        ],
    },
    {
        "slug": "presenting",
        "title": "Presenting without reading slides",
        "description": "One idea per slide, a spoken argument, and rehearsing the transitions.",
        "language": "en",
        "pages": [
            {
                "slug": "structure",
                "title": "Structure",
                "markdown": (
                    "# Structure\n\n"
                    "Say what you will show, show it, say what it meant. Three parts, five "
                    "minutes, and the audience can follow without notes.\n\n"
                    "One idea per slide. If a slide needs a paragraph of explanation, the "
                    "paragraph belongs in your voice.\n"
                ),
            },
            {
                "slug": "delivery",
                "title": "Delivery",
                "markdown": (
                    "# Delivery\n\n"
                    "Rehearse the transitions, not the sentences. A memorised script breaks at "
                    "the first interruption; a clear next step survives one.\n\n"
                    "Leave silence after an important point. It is the cheapest emphasis "
                    "available.\n"
                ),
                "parent": "structure",
            },
        ],
    },
]


def mixed_quizzes(all_facts: list[tuple[str, str, list[str], str]], count: int = 16) -> list[dict[str, Any]]:
    """Interleaved quizzes: questions from several themes, three per quiz."""
    pool = list(all_facts)
    random.Random("mixed").shuffle(pool)
    quizzes = []
    per_quiz = 3
    for index in range(count):
        chunk = pool[index * per_quiz : (index + 1) * per_quiz]
        if len(chunk) < per_quiz:
            break
        quizzes.append(
            {
                "title": f"Mixed revision — set {index + 1}",
                "description": "Three questions from different subjects: identify the topic before answering.",
                "mode": "qcm",
                "default_language": "en",
                "wrong_answer_policy": "zero",
                "questions": [
                    {
                        "text_html": question,
                        "time_limit_seconds": 30,
                        "options": [
                            {"text": answer, "is_correct": True},
                            *[{"text": wrong, "is_correct": False} for wrong in wrongs],
                        ],
                    }
                    for question, answer, wrongs, _ in chunk
                ],
            }
        )
    return quizzes
