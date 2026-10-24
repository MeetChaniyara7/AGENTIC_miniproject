"""Load prompt templates from prompts/*.txt and fill <<placeholders>>.

<<name>> tokens (not str.format) so the JSON and SQL examples inside the prompts
can contain braces freely.
"""
from __future__ import annotations

from functools import lru_cache

from config import ROOT


@lru_cache(maxsize=None)
def _load(name: str) -> str:
    return (ROOT / "prompts" / f"{name}.txt").read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    text = _load(name)
    for key, value in values.items():
        text = text.replace(f"<<{key}>>", str(value))
    return text
