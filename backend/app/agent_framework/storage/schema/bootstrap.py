from __future__ import annotations

BUILTIN_PROMPTS = [
    (
        "prompt-builtin-summarize",
        "Summarize",
        "summarize",
        "Summarize the following text concisely, preserving the key points "
        "and any decisions or action items:\n\n",
    ),
    (
        "prompt-builtin-translate",
        "Translate to English",
        "translate",
        "Translate the following text to natural English. Preserve formatting, "
        "code blocks, and lists:\n\n",
    ),
    (
        "prompt-builtin-explain-code",
        "Explain code",
        "explain-code",
        "Explain the following code in plain language. Include what it does, "
        "important edge cases, and any potential bugs:\n\n",
    ),
    (
        "prompt-builtin-improve-writing",
        "Improve writing",
        "improve-writing",
        "Improve the writing below for clarity, concision, and tone. Keep the "
        "original meaning and structure:\n\n",
    ),
]


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_prompt_seed_sql() -> str:
    values = [
        "("
        f"{_sql_literal(prompt_id)}, '', 'builtin', {_sql_literal(name)}, "
        f"{_sql_literal(body)}, {_sql_literal(shortcut)}, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
        ")"
        for prompt_id, name, shortcut, body in BUILTIN_PROMPTS
    ]
    return (
        "INSERT INTO prompts("
        "id, owner_user, kind, name, body, shortcut, created_at, updated_at"
        ") VALUES " + ", ".join(values) + " ON CONFLICT (id) DO NOTHING"
    )


PROMPT_SEED_SQL = build_prompt_seed_sql()
