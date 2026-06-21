"""Code snippet extractor: Pygments lexer guess, line count, code body."""
from __future__ import annotations

import re

from shotclassify_common import CodeFields, OCRResult

try:
    from pygments.lexers import guess_lexer  # type: ignore
    from pygments.util import ClassNotFound  # type: ignore
except Exception:  # pragma: no cover
    guess_lexer = None  # type: ignore
    ClassNotFound = Exception  # type: ignore


# Each entry is (language tag, list of substring needles). Order MATTERS:
# more-specific languages are checked first so that, for example, a
# Swift snippet's ``import Foundation`` wins before Python's bare
# ``import`` substring. Likewise SQL (``SELECT`` / ``FROM``) wins
# before Python (which also has ``from `` as a needle for ``from x
# import y``). Substrings are matched case-insensitively against the
# raw text.
_FAST_HINTS = (
    # Highly-distinctive sigils / shebangs first so they cannot lose
    # to a generic keyword later.
    ("shell", ["#!/bin/", "#!/usr/bin/env bash", "#!/usr/bin/env sh"]),
    ("php", ["<?php"]),
    # SQL ahead of Python so ``SELECT a FROM t`` does not lose to
    # Python's ``from`` substring.
    ("sql", ["SELECT ", "INSERT INTO", "UPDATE ", "DELETE FROM"]),
    # Highly-distinctive imports / sigils next.
    ("c#", ["Console.WriteLine", "using System;", "public static void Main", "namespace "]),
    ("swift", ["import Foundation", "@objc", "guard let "]),
    ("kotlin", ["companion object", "fun main("]),
    ("scala", ["extends App", "import scala", "object Main extends"]),
    ("haskell", ["import qualified", "main = do", ":: IO ", "putStrLn "]),
    ("elixir", ["defmodule ", "defp ", "iex>", "|> ", "IO.puts"]),
    ("rust", [
        "fn main()", "let mut ", "impl ", "::<", "println!", "Result<", "Option<",
    ]),
    # Go BEFORE generic-keyword languages: ``package main`` and
    # ``fmt.Println`` are unique to Go.
    ("go", ["package main", "fmt.Println", "fmt.Printf", "fmt.Errorf"]),
    ("typescript", [": string", ": number", "interface ", "type "]),
    ("javascript", ["console.log", "const ", "let ", "function ", "=>"]),
    ("python", [
        "def ", "import ", "from ", "print(", "self.", "    return ",
    ]),
    ("java", ["public class", "System.out", "void main"]),
    ("ruby", ["puts ", "require ", "def "]),
)


# Lightweight framework / library guesses driven off imports and
# top-level identifiers. Returns None when no strong signal is found
# so the caller can decide whether to fall back to the bare language.
_FRAMEWORK_HINTS = {
    "react": ["import react", "from 'react'", 'from "react"', "useState(", "useEffect("],
    "vue": ["createApp(", "defineComponent(", "<script setup>"],
    "angular": ["@Component(", "@NgModule(", "BrowserModule"],
    "nextjs": ["from 'next/", 'from "next/', "getServerSideProps", "getStaticProps"],
    "django": ["from django", "django.db", "models.Model", "urlpatterns"],
    "flask": ["from flask", "Flask(__name__)", "@app.route"],
    "fastapi": ["from fastapi", "FastAPI(", "@app.get", "@app.post"],
    "rails": ["ActiveRecord::Base", "ApplicationController", "Rails.application"],
    # JVM microframeworks. Quarkus and Micronaut both compete with
    # Spring on the JVM. Their needles are distinct from Spring's
    # (`io.quarkus` / `io.micronaut` vs `@SpringBootApplication`) so
    # iteration order rarely matters in practice — but we still put
    # them BEFORE `spring` so a Quarkus extension that happens to use
    # `@RestController` (from a Spring compatibility shim) still tags
    # the file as Quarkus, which is the more specific signal.
    "quarkus": [
        "io.quarkus",
        "@QuarkusTest",
        "@ApplicationScoped",
        "quarkus.platform",
    ],
    "micronaut": [
        "io.micronaut",
        "@MicronautTest",
        "io.micronaut.http",
        "io.micronaut.runtime",
    ],
    "spring": ["@SpringBootApplication", "@RestController", "@Autowired"],
    "express": ["require('express')", 'require("express")', "express()"],
    "gin": ["gin.New(", "gin.Default(", "*gin.Context"],
    "actix": ["actix_web", "HttpServer::new"],
    "tokio": ["tokio::main", "tokio::spawn", "tokio::runtime"],
    # PHP web frameworks. Laravel's facades (`Illuminate\\`) and Artisan
    # commands are unique enough to identify the framework even when the
    # surrounding code looks like vanilla PHP. Symfony uses the
    # `Symfony\\Component` and `App\\Controller` conventions plus the
    # `@Route(...)` annotation.
    "laravel": [
        "use Illuminate\\",
        "Illuminate\\Support",
        "Illuminate\\Http",
        "extends Controller",
        "Artisan::",
        "->middleware(",
    ],
    "symfony": [
        "use Symfony\\Component",
        "Symfony\\Bundle",
        "extends AbstractController",
        "#[Route(",
        "@Route(",
    ],
    # Elixir Phoenix uses `Phoenix.Router`, `Phoenix.Endpoint`, and the
    # pipe-through router macro. Keep these tight so a bare Elixir
    # snippet still classifies as plain Elixir at the language layer.
    "phoenix": [
        "use Phoenix.Router",
        "Phoenix.Endpoint",
        "Phoenix.LiveView",
        "pipe_through ",
    ],
}


def detect_language(code: str) -> str | None:
    if not code.strip():
        return None
    # Substring match is fine for our needles because we picked tokens
    # that are reasonably distinctive within each language's slot in
    # the ordered list. Match case-insensitively so SQL keywords work
    # regardless of how the screenshot vendor cased them.
    upper = code.upper()
    for lang, needles in _FAST_HINTS:
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


def detect_framework(code: str) -> str | None:
    """Return a popular-framework tag (``react``, ``django``, ``rails``,
    ``spring`` etc.) or ``None`` if no strong signal is present.

    Used by the API and dashboards to group code-snippet captures by
    the stack the operator is most likely working on, without forcing
    a heavier LLM round trip.
    """
    if not code or not code.strip():
        return None
    body = code  # case-sensitive checks; framework needles include exact tokens
    for tag, needles in _FRAMEWORK_HINTS.items():
        if any(n in body for n in needles):
            return tag
    return None


# SQL dialect detection. Returns a lowercase dialect tag for SQL
# snippets so dashboards can group MySQL vs PostgreSQL vs SQLite vs
# MSSQL captures, or ``None`` when the code is not SQL (or doesn't
# emit enough signal to pick a dialect confidently).
#
# Signals (case-insensitive comparisons unless noted) -- the FIRST
# matching dialect wins, in this priority order:
#
#   mssql     - ``TOP n`` after SELECT, ``NVARCHAR``, ``GETDATE()``,
#               ``[col]`` square-bracket quoting, ``WITH (NOLOCK)``.
#   postgres  - ``RETURNING`` clause, ``::TYPE`` casts, ``$1``/``$N``
#               placeholders, ``SERIAL`` column type, ``ILIKE``.
#   mysql     - ``AUTO_INCREMENT`` (snake), ``ENGINE=``, ``\`column\``
#               backtick quoting, ``LIMIT n OFFSET m``.
#   sqlite    - ``AUTOINCREMENT`` (no underscore, single word),
#               ``pragma`` directives, ``sqlite_master`` table.
#
# Ambiguous SQL (e.g. ANSI-style ``SELECT * FROM t WHERE x = ?``)
# returns ``None`` -- the caller already knows the language is SQL
# from ``detect_language``; we only commit to a dialect when at least
# one strong signal is present.
_SQL_DIALECT_HINTS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "mssql",
        (
            re.compile(r"\bSELECT\s+TOP\s+\d+\b", re.IGNORECASE),
            re.compile(r"\bNVARCHAR\s*\(", re.IGNORECASE),
            re.compile(r"\bGETDATE\s*\(\s*\)", re.IGNORECASE),
            re.compile(r"\bWITH\s*\(\s*NOLOCK\s*\)", re.IGNORECASE),
            # Square-bracket identifier quoting. Require it to wrap a
            # plausible identifier so a JSON path / generic ``[0]``
            # doesn't trigger. Followed by an operator, comma, paren,
            # whitespace, or end-of-string so a query that ends with
            # ``FROM [Users]`` still tags.
            re.compile(r"\[[A-Za-z_][A-Za-z0-9_ ]*\](?=[\s=,)]|$)"),
            re.compile(r"@@(?:IDENTITY|ROWCOUNT|VERSION)\b", re.IGNORECASE),
        ),
    ),
    (
        "postgres",
        (
            re.compile(r"\bRETURNING\b", re.IGNORECASE),
            # ``$1`` / ``$2`` placeholders. Require a word boundary on
            # the left so a regex pattern like ``r'\$1'`` in surrounding
            # code doesn't trigger.
            re.compile(r"(?<![\w])\$\d+\b"),
            re.compile(r"::(?:int|integer|bigint|text|varchar|uuid|jsonb?|"
                       r"timestamp(?:tz)?|date|bool(?:ean)?|numeric|float|"
                       r"double precision)\b", re.IGNORECASE),
            re.compile(r"\bSERIAL\b|\bBIGSERIAL\b", re.IGNORECASE),
            re.compile(r"\bILIKE\b", re.IGNORECASE),
            re.compile(r"\bON CONFLICT\b", re.IGNORECASE),
        ),
    ),
    (
        "mysql",
        (
            re.compile(r"\bAUTO_INCREMENT\b", re.IGNORECASE),
            re.compile(r"\bENGINE\s*=\s*(?:InnoDB|MyISAM|MEMORY|ARCHIVE)\b", re.IGNORECASE),
            # Backtick-quoted identifier. Same defence as MSSQL: needs
            # to look like an identifier.
            re.compile(r"`[A-Za-z_][A-Za-z0-9_]*`"),
            re.compile(r"\bLIMIT\s+\d+\s*,\s*\d+\b", re.IGNORECASE),
            re.compile(r"\bUNSIGNED\b", re.IGNORECASE),
            re.compile(r"\bDEFAULT CHARSET\s*=\s*\w+", re.IGNORECASE),
        ),
    ),
    (
        "sqlite",
        (
            # SQLite uses one-word AUTOINCREMENT (no underscore).
            re.compile(r"\bAUTOINCREMENT\b"),
            re.compile(r"\bPRAGMA\b", re.IGNORECASE),
            re.compile(r"\bsqlite_master\b", re.IGNORECASE),
            re.compile(r"\bWITHOUT\s+ROWID\b", re.IGNORECASE),
        ),
    ),
)


def detect_sql_dialect(code: str) -> str | None:
    """Return ``mssql`` / ``postgres`` / ``mysql`` / ``sqlite`` for
    SQL snippets with a strong dialect signal, or ``None`` otherwise.

    The detection iterates dialects in priority order and returns the
    first match. Order matters because some dialect features overlap
    (e.g. MySQL and PostgreSQL both accept ``LIMIT n``); we anchor on
    the dialect-specific features (``AUTO_INCREMENT``, ``RETURNING``,
    ``TOP``, ``AUTOINCREMENT``) so ambiguous ANSI SQL falls through to
    ``None``.
    """
    if not code or not code.strip():
        return None
    for tag, patterns in _SQL_DIALECT_HINTS:
        if any(p.search(code) for p in patterns):
            return tag
    return None


# TypeScript-specific feature extraction. The simple language detector
# already tags a snippet as TypeScript when it sees ``: string`` /
# ``: number`` / ``interface `` / ``type ``, but those are only the
# minimum signals. Dashboards want richer information about which
# TypeScript-only constructs the snippet uses:
#
#   decorator         - leading ``@`` on a class/method (``@Component``)
#   as_cast           - the ``foo as Bar`` type assertion (TS-only;
#                       JS does not have this syntax)
#   angle_cast        - the legacy ``<Bar>foo`` type assertion (used
#                       in .ts files but not .tsx because the angle
#                       brackets collide with JSX)
#   generic           - generic type parameter declaration on a
#                       function / class / interface / type (``<T>`` /
#                       ``<T, U>``)
#   enum              - ``enum X { ... }`` declaration (TS-only)
#   readonly          - ``readonly`` modifier on a property / param
#   abstract          - ``abstract class`` / ``abstract method`` (TS-only)
#   access_modifier   - ``public`` / ``private`` / ``protected`` on
#                       a class member (TS-only; JS has private fields
#                       via ``#name`` but not these keywords)
#   namespace         - ``namespace X { ... }`` declaration (TS-only)
#   optional_chain    - ``foo?.bar`` (also in ES2020 JS, but TS code
#                       commonly uses it -- surfaced for dashboards)
#   non_null_assert   - ``foo!`` non-null assertion (TS-only)
#
# We compile each pattern once at module load. Detection is a single
# pass through the patterns (none overlap, none feed back). The
# result list preserves the iteration order so dashboards can render
# consistently.
_TS_FEATURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Decorator: leading ``@`` followed by an Identifier at the start
    # of a line (after optional indent). The ``(?!`` lookahead excludes
    # mid-line ``@`` (a template / object key like ``key@1``).
    ("decorator", re.compile(r"^\s*@[A-Z]\w*(?:\([^)]*\))?\s*$", re.MULTILINE)),
    # ``as`` cast: ``foo as Bar`` / ``foo as Bar<T>``. We anchor on
    # the preceding identifier / paren and the trailing TypeName so a
    # plain English ``treat as constant`` won't fire.
    ("as_cast", re.compile(
        r"[\w)\]]\s+as\s+(?:[A-Z]\w*(?:<[^>]*>)?|unknown|any|string|number|"
        r"boolean|object|void|never)\b",
    )),
    # Legacy angle-bracket cast: ``<Bar>foo`` / ``<Bar<T>>foo``. The
    # body must start with an uppercase letter (a type name) so JSX
    # tags ``<div>`` / ``<MyComponent ...>`` don't false-positive.
    ("angle_cast", re.compile(r"<[A-Z]\w*(?:<[^>]+>)?>(?=[\w\(\[])")),
    # Generic type parameter on a function / class / interface / type
    # declaration. We anchor on the declaration keyword to avoid
    # confusing comparison operators ``a < b`` and JSX ``<div>``.
    ("generic", re.compile(
        r"\b(?:function|class|interface|type|const|let|var)\s+\w+\s*<[A-Z]\w*"
        r"(?:\s*(?:extends\s+[\w<>.,\s]+|,\s*[A-Z]\w*))*\s*>",
    )),
    # Bare ``enum X``. The keyword is unique to TS and never appears as
    # a plain identifier in modern JS.
    ("enum", re.compile(r"\benum\s+[A-Z]\w*\s*[{=]")),
    # ``readonly`` modifier on a property / param. Word-bounded so a
    # comment containing the word ``readonly`` doesn't trigger.
    ("readonly", re.compile(r"\breadonly\s+[\w_$]+\s*[:?]")),
    # ``abstract`` modifier on a class / method.
    ("abstract", re.compile(r"\babstract\s+(?:class|[\w_$]+\s*\()")),
    # Access modifier: ``public`` / ``private`` / ``protected`` on a
    # class member. Word-bounded on the left so a generic comment
    # containing ``public foo`` would still tag (acceptable -- the
    # word is a reserved keyword in TS). The trailing identifier must
    # be followed by ``:`` (property), ``(`` (method), or ``?`` /
    # ``=`` (optional / default) so prose words after ``private``
    # don't false-positive.
    ("access_modifier", re.compile(
        r"\b(?:public|private|protected)\s+(?:readonly\s+|static\s+|"
        r"abstract\s+)?[\w_$]+\s*[:(?=]",
    )),
    # ``namespace X { ... }``. Keyword unique to TS.
    ("namespace", re.compile(r"\bnamespace\s+[A-Z]\w*\s*\{")),
    # Optional chaining: ``foo?.bar``. Bracketed optional chain
    # (``foo?.[x]``) and function call optional chain (``foo?.()``)
    # also count. Anchored on a word char before the ``?`` so a ternary
    # ``a ? b : c`` doesn't false-positive.
    ("optional_chain", re.compile(r"[\w\])]\?\.(?:\w|\(|\[)")),
    # Non-null assertion: ``foo!`` / ``foo!.bar``. Word-bounded on
    # both sides so a logical-not ``!foo`` and an inequality ``foo !=``
    # don't false-positive. The ``!`` must be followed by ``.`` /
    # ``(`` / ``[`` / ``;`` / whitespace / end-of-string.
    ("non_null_assert", re.compile(r"\w!(?=[.(\[;,\s]|$)")),
)


def detect_ts_features(code: str) -> list[str]:
    """Return the set of TypeScript-only features ``code`` exercises.

    Each tag fires at most once per snippet (de-duped by tag name);
    the order matches the declared pattern catalogue so dashboards
    render consistently across snippets.
    """
    if not code or not code.strip():
        return []
    found: list[str] = []
    seen: set[str] = set()
    for tag, pattern in _TS_FEATURE_PATTERNS:
        if tag in seen:
            continue
        if pattern.search(code):
            seen.add(tag)
            found.append(tag)
    return found


def enrich_code(existing: CodeFields | None, ocr: OCRResult) -> CodeFields:
    code = (existing.code if existing and existing.code else ocr.text or "").strip()
    language = (existing.language if existing and existing.language else None) or detect_language(code)
    # Dialect narrowing runs only when the inferred language looks like
    # SQL -- it's a no-op for every other language, so the cost is a
    # single string check per snippet. The LLM-supplied dialect (if any)
    # always wins so a caller that already knows the dialect is not
    # second-guessed by the heuristic.
    dialect = existing.dialect if existing and existing.dialect else None
    if dialect is None and language and language.lower().startswith("sql"):
        dialect = detect_sql_dialect(code)
    # TypeScript-specific feature extraction. Runs only when language
    # is typescript / tsx so we don't mis-tag a plain JS snippet that
    # happens to contain ``as`` as a regular identifier. Caller-
    # supplied ts_features are preserved verbatim; the heuristic only
    # fills the slot when the caller left it empty.
    ts_features: list[str] = (
        list(existing.ts_features) if existing and existing.ts_features else []
    )
    if not ts_features and language and language.lower() in {"typescript", "tsx", "ts"}:
        ts_features = detect_ts_features(code)
    return CodeFields(
        language=language,
        code=code,
        line_count=len(code.splitlines()),
        dialect=dialect,
        ts_features=ts_features,
    )
