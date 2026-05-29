"""Code snippet extractor: Pygments lexer guess, line count, code body."""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult

try:
    from pygments.lexers import guess_lexer  # type: ignore
    from pygments.util import ClassNotFound  # type: ignore
except Exception:  # pragma: no cover
    guess_lexer = None  # type: ignore
    ClassNotFound = Exception  # type: ignore


_FAST_HINTS = {
    "python": [r"def ", r"import ", r"from .* import", r"print("],
    "javascript": ["const ", "let ", "function ", "=>", "console.log"],
    "typescript": [": string", ": number", "interface ", "type "],
    "go": ["package ", "func ", "fmt."],
    "rust": ["fn ", "let mut", "impl ", "::<"],
    "java": ["public class", "System.out", "void main"],
    "ruby": ["def ", "end", "puts "],
    "shell": ["#!/bin/", "$(", "echo "],
    "sql": ["SELECT ", "FROM ", "WHERE ", "INSERT INTO"],
}


def detect_language(code: str) -> str | None:
    if not code.strip():
        return None
    # Try fast hints first — Pygments "guess_lexer" is notoriously wobbly on short snippets.
    upper = code.upper()
    for lang, needles in _FAST_HINTS.items():
        if any(n.upper() in upper for n in needles):
            return lang
    if guess_lexer is not None:
        try:
            lex = guess_lexer(code)
            name = (lex.aliases[0] if lex.aliases else lex.name).lower()
            return name
        except ClassNotFound:
            pass
        except Exception:
            pass
    return "text"


def enrich_code(existing: CodeFields | None, ocr: OCRResult) -> CodeFields:
    code = (existing.code if existing and existing.code else ocr.text or "").strip()
    return CodeFields(
        language=(existing.language if existing and existing.language else None)
        or detect_language(code),
        code=code,
        line_count=len(code.splitlines()),
    )
