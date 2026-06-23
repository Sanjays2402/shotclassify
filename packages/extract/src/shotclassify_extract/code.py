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


# Minified JS / TS detection. Bundlers (webpack, esbuild, rollup,
# terser, uglify) collapse JS / TS sources into one or a few very long
# lines with near-zero whitespace. Common signals:
#
#   * one or a small number of very long source lines (avg line
#     length above ~250 chars is a strong indicator),
#   * very few newlines after ``;`` / ``{`` / ``}`` separators
#     (hand-written code newlines after most of these),
#   * single-character identifiers everywhere (``t``, ``e``, ``n``,
#     ``r``) -- not enforced as a hard rule because some prod code
#     still uses them, but contributes to the score,
#   * a leading IIFE wrapper ``!function(){...}()`` or webpack
#     runtime preamble ``(self.webpackChunk...``.
#
# We combine these into a tiny scoring function. The heuristic is
# intentionally conservative: it returns True only when the avg line
# length is high AND the newline-after-separator ratio is low. A
# 30-line minified-ish snippet that still pretty-prints will return
# False -- prefer recall on real bundles over precision on edge cases.
_BUNDLER_PREAMBLES = (
    "(self.webpackChunk",
    "webpackBootstrap",
    "webpackJsonp",
    "function(modules)",
    "!function(",
    "var __webpack_modules__",
    "globalThis.webpackChunk",
    "// minified",
)


def detect_minified_js(code: str, language: str | None = None) -> bool:
    """Return ``True`` when ``code`` looks like minified / bundled JS or TS.

    Only relevant for JS-family languages (javascript / typescript /
    jsx / tsx). For other languages we return ``False`` unconditionally
    because the heuristics (avg line length, separators) are tuned to
    JS bundle output.
    """
    if not code or not code.strip():
        return False
    if language is not None:
        lang = language.lower()
        if lang not in {"javascript", "typescript", "jsx", "tsx", "js", "ts"}:
            return False
    # Direct hit on a known bundler preamble => minified for sure.
    head = code[:400]
    for sig in _BUNDLER_PREAMBLES:
        if sig in head:
            return True
    lines = code.splitlines()
    if not lines:
        return False
    # Strip trailing empties so the avg isn't dragged down by them.
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return False
    # Avg non-empty line length.
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return False
    avg_len = sum(len(ln) for ln in non_empty) / len(non_empty)
    max_len = max(len(ln) for ln in non_empty)
    # Count semicolons / braces that DON'T have a newline immediately
    # after them. Hand-written code newlines after most of these; a
    # bundle packs them onto one line.
    sep_total = code.count(";") + code.count("{") + code.count("}")
    if sep_total == 0:
        # No JS separators at all -- can't conclude minified.
        return False
    # Count separators that have a newline within the next 2 chars
    # (covers ``;\n``, ``;\r\n``, ``; \n``).
    sep_with_newline = 0
    for i, ch in enumerate(code):
        if ch in ";{}":
            for j in range(i + 1, min(i + 3, len(code))):
                if code[j] == "\n":
                    sep_with_newline += 1
                    break
                if not code[j].isspace():
                    break
    newline_ratio = sep_with_newline / sep_total
    # Decision rule:
    #   * Avg line length > 250  OR  any line > 500 chars  AND
    #   * Fewer than 30% of separators have a newline after them.
    # The "max_len > 500" catch handles bundles that have a few short
    # comments above one giant minified body (common with sourcemap
    # comments). Both branches require the low newline-ratio so a
    # legitimate long-template-literal snippet doesn't false-positive.
    long_lines = avg_len > 250 or max_len > 500
    low_newline_ratio = newline_ratio < 0.30
    return long_lines and low_newline_ratio


# Shebang interpreter detection. The leading ``#!/path/to/x`` line
# (the "shebang") gives Unix-flavoured scripts a portable way to
# declare their interpreter. We pull the short interpreter name --
# the last path segment, or the argument when ``env`` is used as the
# wrapper -- so dashboards can group "ran under bash" without having
# to parse the full path.
#
# Recognised shapes:
#
#   #!/bin/bash                  -> bash
#   #!/usr/bin/bash              -> bash
#   #!/usr/bin/env bash          -> bash      (env-wrapped form)
#   #!/usr/bin/env -S python3 -O -> python3   (env -S split-args form)
#   #!/usr/bin/python3.11        -> python3.11
#   #!/usr/bin/perl              -> perl
#   #!/usr/local/bin/ruby        -> ruby
#   #!/usr/bin/env node          -> node
#   #!/bin/sh                    -> sh
#
# Edge cases handled:
#
# * leading whitespace before the ``#!`` is rejected -- a real
#   shebang MUST be the first two bytes of the file. OCR noise can
#   strip the leading line; we conservatively require the strict
#   form.
# * ``env`` invocations capture the FIRST non-flag argument as the
#   interpreter. ``env -S python3 -O`` -> ``python3``;
#   ``env --split-string=python3`` is also handled.
# * Windows ``rem`` / ``::`` comments and DOS BOM-prefixed scripts
#   are NOT shebangs -- we don't try to parse them.
# * A shebang inside a docstring / heredoc / multiline string is
#   NOT pulled because we only look at the first line of the
#   snippet.
_SHEBANG_RE = re.compile(
    r"^#!\s*(?P<path>\S+)(?:\s+(?P<args>[^\n]*))?$"
)
# ``env`` flag set we know how to skip: short flags (``-S``,
# ``-i``), long flags (``--ignore-environment``, ``--split-string``,
# ``--null``, ``--debug``, ``--unset=NAME``). When ``--split-string``
# carries the interpreter inline (``--split-string=python3``) we
# pull the value after the ``=``.
_ENV_FLAG_RE = re.compile(r"^-{1,2}[A-Za-z]")


def detect_interpreter(code: str) -> str | None:
    """Return the interpreter named in the leading shebang, or None.

    Only the FIRST line of ``code`` is consulted -- a shebang
    further down the snippet isn't a real shebang (it's just a
    comment in the body). ``env``-wrapped invocations are handled
    so ``#!/usr/bin/env bash`` returns ``bash``; ``env -S python3
    -O`` returns ``python3``. Leading whitespace before the ``#!``
    is rejected because a real shebang must occupy the first two
    bytes of the file.
    """
    if not code:
        return None
    first_line = code.split("\n", 1)[0]
    # Reject a leading-whitespace shebang -- the kernel exec(2)
    # parser does too.
    if first_line[:2] != "#!":
        return None
    m = _SHEBANG_RE.match(first_line)
    if not m:
        return None
    path = m.group("path")
    args = (m.group("args") or "").strip()
    # Last path segment is the candidate interpreter (``/bin/bash``
    # -> ``bash``). Strip any drive prefix from a Windows-style path
    # (``C:\bash``) by splitting on both separators.
    candidate = path.rsplit("/", 1)[-1]
    candidate = candidate.rsplit("\\", 1)[-1]
    # ``env`` wrapper: the interpreter is the first non-flag arg.
    # Also handle ``env --split-string=python3`` inline form.
    if candidate == "env" and args:
        for token in args.split():
            # Inline ``--key=value`` -- pull the value when key is
            # ``--split-string`` (the only env flag that carries
            # the interpreter inline).
            if token.startswith("--split-string="):
                return token.split("=", 1)[1] or None
            if _ENV_FLAG_RE.match(token):
                # Skip env's own flag and continue scanning.
                continue
            # First non-flag token IS the interpreter.
            return token
        # Only flags after ``env`` -> can't determine interpreter.
        return None
    # Non-env shebang: candidate is the interpreter directly.
    return candidate or None


# Comment-density heuristic. We map a language tag to the leading
# token(s) that open a line comment in that language, then count
# what fraction of NON-BLANK lines start with one of those tokens.
#
# Single-line comment leaders by language family:
#
#   ``#``    Python / Ruby / Shell / Bash / Zsh / Fish / Perl /
#            Elixir / R / Make / YAML / Conf / Dockerfile / TOML.
#   ``//``   C / C++ / Java / JavaScript / TypeScript / Go / Rust /
#            C# / Kotlin / Swift / Scala / PHP / Dart / Groovy / D.
#   ``--``   SQL / Lua / Haskell / Ada / VHDL / Eiffel.
#   ``;``    Lisp / Scheme / Clojure / Common Lisp / Racket / Asm.
#   ``%``    Erlang / MATLAB / LaTeX / Prolog.
#   ``'``    VB / VB.NET / VBScript / Smalltalk.
#   ``REM``  BASIC / Batch.
#   ``<!--`` HTML / XML / SVG (line-leading XML/HTML comments).
#
# Block-comment leaders that count when sitting at the start of a
# line:
#
#   ``/*``  C-family multi-line.
#   ``"""``  Python triple-quoted docstring (also ``'''``).
#   ``=begin``  Ruby multi-line.
#
# Languages we DON'T recognise default to the ``#`` set because that
# leader is the most common across configuration / scripting languages
# and gives a reasonable answer for any uncatalogued language.
_COMMENT_LEADERS_BY_LANGUAGE: dict[str, tuple[str, ...]] = {
    # ``#`` family
    "python": ("#", '"""', "'''"),
    "ruby": ("#", "=begin"),
    "shell": ("#",),
    "bash": ("#",),
    "sh": ("#",),
    "zsh": ("#",),
    "fish": ("#",),
    "perl": ("#",),
    "elixir": ("#",),
    "r": ("#",),
    "make": ("#",),
    "makefile": ("#",),
    "yaml": ("#",),
    "yml": ("#",),
    "toml": ("#",),
    "conf": ("#",),
    "dockerfile": ("#",),
    # ``//`` family
    "c": ("//", "/*"),
    "cpp": ("//", "/*"),
    "c++": ("//", "/*"),
    "java": ("//", "/*"),
    "javascript": ("//", "/*"),
    "js": ("//", "/*"),
    "typescript": ("//", "/*"),
    "ts": ("//", "/*"),
    "tsx": ("//", "/*"),
    "jsx": ("//", "/*"),
    "go": ("//", "/*"),
    "rust": ("//", "/*"),
    "c#": ("//", "/*"),
    "csharp": ("//", "/*"),
    "kotlin": ("//", "/*"),
    "swift": ("//", "/*"),
    "scala": ("//", "/*"),
    "php": ("//", "#", "/*"),  # PHP accepts both ``//`` and ``#``
    "dart": ("//", "/*"),
    "groovy": ("//", "/*"),
    # ``--`` family
    "sql": ("--", "/*"),
    "lua": ("--", "--[["),
    "haskell": ("--", "{-"),
    # ``;`` family
    "lisp": (";",),
    "scheme": (";",),
    "clojure": (";",),
    # ``%`` family
    "erlang": ("%",),
    "matlab": ("%", "%{"),
    "latex": ("%",),
    # ``<!--`` (HTML / XML)
    "html": ("<!--",),
    "xml": ("<!--",),
    "svg": ("<!--",),
}
# Languages we recognise but want to treat as having no defined
# comment leader (so the density is always 0.0). Pure data formats
# only -- ``text`` is NOT in this set because a snippet whose
# language detection landed on ``text`` (the catchall fallback)
# is often a script-like body where the ``#`` leader gives the
# right answer. We default ``text`` through the generic ``#``
# fallback rather than zeroing it out.
_NO_COMMENT_LANGUAGES = {"json", "csv", "tsv"}


def _comment_leaders_for(language: str | None) -> tuple[str, ...]:
    """Return the comment-leader tokens for ``language``.

    Unknown languages default to ``("#",)`` because ``#`` is the most
    common single-character leader across configuration / scripting
    files. Pure data languages (JSON, CSV) return an empty tuple so
    their density is always 0.0.
    """
    if not language:
        return ("#",)
    lang = language.lower().strip()
    if lang in _NO_COMMENT_LANGUAGES:
        return ()
    return _COMMENT_LEADERS_BY_LANGUAGE.get(lang, ("#",))


def detect_comment_density(code: str, language: str | None = None) -> float:
    """Return the fraction of NON-BLANK lines that open with a comment
    leader for ``language``, as a float in ``[0.0, 1.0]``.

    Blank lines are excluded from the denominator so a snippet padded
    with blank rows doesn't artificially lower the density. The
    numerator counts every non-blank line whose first non-whitespace
    token matches one of the language's comment leaders (including
    block-comment openers like ``/*`` and ``\"\"\"``). When the
    snippet is empty or has no recognisable comment leader for the
    language, the result is ``0.0``.

    Rounded to 2 decimal places because finer precision is meaningless
    given OCR noise and small snippet sizes.
    """
    if not code or not code.strip():
        return 0.0
    leaders = _comment_leaders_for(language)
    if not leaders:
        return 0.0
    total = 0
    comments = 0
    for raw in code.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        total += 1
        for leader in leaders:
            if stripped.startswith(leader):
                comments += 1
                break
    if total == 0:
        return 0.0
    return round(comments / total, 2)


# TODO / FIXME action-comment marker catalogue. The seven common
# action-comment markers used across virtually every codebase. We
# enforce ALL-CAPS to avoid matching prose words (a sentence about
# "the bug we fixed" contains the lowercase ``bug`` but isn't an
# action marker). The markers must be preceded by a comment leader
# (the language's leader, falling back to ``#``) and followed by a
# non-alphanumeric boundary so ``TODOIST`` / ``FIXMEAGAIN`` /
# ``XXXX`` are NOT counted as markers.
_TODO_MARKERS: tuple[str, ...] = (
    "TODO",
    "FIXME",
    "XXX",
    "HACK",
    "BUG",
    "NOTE",
    "OPTIMIZE",
)


def detect_todo_count(code: str, language: str | None = None) -> int:
    """Return the count of TODO / FIXME / XXX / HACK / BUG / NOTE /
    OPTIMIZE action-comment markers in ``code``.

    Each marker must satisfy ALL of:

    1. ALL-CAPS spelling (case-sensitive). A prose mention like
       ``the bug we fixed`` is not a marker.
    2. Preceded somewhere on the same line by a comment leader for
       ``language`` (or ``#`` for unknown languages). Block-comment
       openers (``/*``, ``\"\"\"``, ``'''``) count when they sit at the
       start of a line OR earlier on the same line.
    3. Followed by a non-alphanumeric / non-underscore boundary so a
       longer identifier (``TODOIST``, ``BUGGY``, ``XXXX``) is NOT
       counted.

    Returns ``0`` for an empty snippet or a snippet whose language has
    no comment syntax (JSON / CSV / TSV). Multiple markers on the
    same line count separately (``# TODO / FIXME bug``).

    Pure data languages (json / csv / tsv) return 0 unconditionally
    because they have no comment syntax to host action markers.
    """
    if not code or not code.strip():
        return 0
    leaders = _comment_leaders_for(language)
    if not leaders:
        return 0
    # Build the marker regex once. The boundary lookahead rejects
    # contiguous alphanumerics so TODOIST / XXXX don't match.
    marker_re = re.compile(
        r"\b(" + "|".join(re.escape(m) for m in _TODO_MARKERS) + r")(?![A-Z0-9_])",
    )
    count = 0
    for raw in code.splitlines():
        # Find the FIRST comment opener on the line. We accept any
        # leader at any position (so inline ``foo = 1  # TODO`` counts)
        # and treat the substring AFTER the leader as the search area
        # for markers.
        first_leader_pos: int | None = None
        for leader in leaders:
            pos = raw.find(leader)
            if pos == -1:
                continue
            if first_leader_pos is None or pos < first_leader_pos:
                first_leader_pos = pos
        if first_leader_pos is None:
            continue
        comment_body = raw[first_leader_pos:]
        # Count every marker occurrence in the comment body. Multiple
        # markers on the same line each count.
        count += len(marker_re.findall(comment_body))
    return count


# Author-tagged TODO matcher. Recognises the standard
# ``MARKER(author):`` and ``MARKER(author)`` forms used across most
# codebases. The author handle is captured up to the closing
# parenthesis. Whitespace-only authors and empty parens are
# rejected; a leading ``@`` on the handle is preserved verbatim
# because some codebases prefix GitHub handles with ``@``.
_TODO_AUTHOR_RE = re.compile(
    r"\b(?P<marker>" + "|".join(re.escape(m) for m in _TODO_MARKERS) + r")"
    r"\((?P<author>[^()\n]{1,64})\)"
)


# Maximum number of author-tagged TODOs returned. A snippet with
# more than 50 author-tagged TODOs is extraordinarily unusual; the
# cap is purely defensive.
_MAX_TODO_AUTHORS = 50


def extract_todo_authors(
    code: str, language: str | None = None
) -> list[dict[str, str]]:
    """Return the author-tagged TODO / FIXME / XXX / HACK / BUG /
    NOTE / OPTIMIZE markers found in ``code``.

    Output is a list of ``{"marker", "author"}`` dicts preserving
    first-seen order. Dedupe is intentionally NOT performed because
    the same author may legitimately own multiple TODOs in one
    snippet.

    The matcher recognises the canonical ``MARKER(author):`` and
    ``MARKER(author)`` forms used across most codebases:

    * ``# TODO(alice): hook up retries``
    * ``// FIXME(bob): off-by-one``
    * ``/* HACK(carol-87): rewrite once we drop py3.9 */``
    * ``; XXX(@dave): clean up``

    Each marker must satisfy ALL of:

    1. ALL-CAPS spelling (case-sensitive). A prose mention
       ``the bug we fixed`` is not a marker.
    2. Preceded somewhere on the same line by a comment leader
       for ``language`` (or ``#`` for unknown languages). Block-
       comment openers (``/*``, ``\"\"\"``, ``'''``) count when
       they sit earlier on the same line.
    3. Followed immediately by ``(`` + 1..64 chars (non-paren,
       non-newline) + ``)`` capturing the author handle.

    The author capture is post-processed:

    * Trailing ``,`` / ``;`` / ``:`` / ``-`` whitespace is
      stripped.
    * Leading whitespace is stripped.
    * Empty-after-stripping authors are dropped (a ``TODO()``
      with an empty paren is not an author tag).

    Pure data languages (json / csv / tsv) return an empty list
    unconditionally because they have no comment syntax to host
    action markers.
    """
    if not code or not code.strip():
        return []
    leaders = _comment_leaders_for(language)
    if not leaders:
        return []
    out: list[dict[str, str]] = []
    for raw in code.splitlines():
        # Find the FIRST comment opener on the line (mirrors
        # detect_todo_count -- markers in a non-commented line are
        # not action-comment markers).
        first_leader_pos: int | None = None
        for leader in leaders:
            pos = raw.find(leader)
            if pos == -1:
                continue
            if first_leader_pos is None or pos < first_leader_pos:
                first_leader_pos = pos
        if first_leader_pos is None:
            continue
        comment_body = raw[first_leader_pos:]
        for m in _TODO_AUTHOR_RE.finditer(comment_body):
            marker = m.group("marker")
            author = m.group("author").strip().rstrip(",;:- \t")
            if not author:
                continue
            out.append({"marker": marker, "author": author})
            if len(out) >= _MAX_TODO_AUTHORS:
                return out
    return out


# TODO ticket-link matcher. Recognises three ticket-reference shapes
# that commonly appear alongside a TODO / FIXME / XXX / HACK / BUG /
# NOTE / OPTIMIZE marker in code comments:
#
# * JIRA-style ``PROJECT-NUMBER``: ``JIRA-1234`` / ``ABC-99`` /
#   ``ENG-455`` / ``PROJ-100`` / ``GH-789``. Project tag is 2..10
#   ALL-CAPS letters; number is 1..6 digits. The hyphen separator
#   is required.
# * GitHub-style hash-prefixed number: ``#1234`` / ``#42``. The
#   number is 1..6 digits.
# * Hash-prefixed slug ``#identifier-NUMBER`` (some trackers use
#   this shape): ``#issue-42`` / ``#bug-99``. The leading identifier
#   is 2..20 ALL-LOWERCASE letters; trailing number is 1..6 digits.
#
# All three forms must sit on the SAME LINE as a recognised marker
# and inside the comment body (preceded by the language's comment
# leader, mirroring detect_todo_count + extract_todo_authors).
# Multiple ticket refs per line each count as a separate entry --
# a TODO that cites two issues yields two entries.
#
# Patterns are ordered most-specific-first so the JIRA matcher
# claims its spans before the GitHub-slug matcher (which could
# otherwise mis-tag ``JIRA-1234`` as a slug). The matcher tracks
# claimed spans within a line.
_TODO_TICKET_JIRA_RE = re.compile(
    r"\b(?P<ticket>[A-Z]{2,10}-\d{1,6})\b"
)
_TODO_TICKET_HASH_SLUG_RE = re.compile(
    r"#(?P<slug>[a-z]{2,20}-\d{1,6})\b"
)
_TODO_TICKET_HASH_NUM_RE = re.compile(
    r"#(?P<num>\d{1,6})\b"
)

# Maximum number of ticket-tagged TODOs returned. Defensive cap.
_MAX_TODO_TICKETS = 50


def extract_todo_tickets(
    code: str, language: str | None = None
) -> list[dict[str, str]]:
    """Return the ticket-tagged TODO / FIXME / XXX / HACK / BUG /
    NOTE / OPTIMIZE markers found in ``code``.

    Output is a list of ``{"marker", "ticket"}`` dicts preserving
    first-seen order. Dedupe is intentionally NOT performed because
    the same ticket may legitimately appear on multiple TODOs
    (different code paths blocked by the same issue).

    The matcher recognises three ticket shapes:

    * JIRA-style ``PROJECT-NUMBER``: ``JIRA-1234`` / ``ABC-99``.
    * GitHub-style hash-number: ``#1234`` / ``#42``.
    * Hash-slug ``#identifier-NUMBER``: ``#issue-42`` / ``#bug-99``.

    Each marker must satisfy ALL of:

    1. ALL-CAPS spelling (case-sensitive). A prose mention
       ``the bug we fixed`` is not a marker.
    2. Preceded somewhere on the same line by a comment leader
       for ``language`` (or ``#`` for unknown languages). Block-
       comment openers (``/*``, ``\"\"\"``, ``'''``) count when
       they sit earlier on the same line.
    3. Followed somewhere on the same line by at least one ticket
       reference (JIRA / hash-num / hash-slug).

    Within a single line, the three ticket matchers run in
    priority order (JIRA -> hash-slug -> hash-num) with spans
    claimed by the earlier matcher excluded from later passes.
    This prevents ``JIRA-1234`` from being mis-tagged as a slug
    or having its trailing digits picked up as a hash-num.

    Pure data languages (json / csv / tsv) return an empty list
    unconditionally because they have no comment syntax to host
    action markers.
    """
    if not code or not code.strip():
        return []
    leaders = _comment_leaders_for(language)
    if not leaders:
        return []
    out: list[dict[str, str]] = []
    marker_re = re.compile(
        r"\b(?P<marker>" + "|".join(re.escape(m) for m in _TODO_MARKERS) + r")(?![A-Z0-9_])"
    )
    for raw in code.splitlines():
        # Find the FIRST comment opener on the line.
        first_leader_pos: int | None = None
        for leader in leaders:
            pos = raw.find(leader)
            if pos == -1:
                continue
            if first_leader_pos is None or pos < first_leader_pos:
                first_leader_pos = pos
        if first_leader_pos is None:
            continue
        comment_body = raw[first_leader_pos:]
        # Find the LAST marker on the line so any ticket reference
        # after the marker (but on the same line) attributes to that
        # marker. Most real-world lines have one marker; multi-marker
        # cases use the last-marker rule for attribution determinism.
        marker_match: re.Match[str] | None = None
        for mm in marker_re.finditer(comment_body):
            marker_match = mm
        if marker_match is None:
            continue
        marker = marker_match.group("marker")
        # Search for tickets in the WHOLE comment body (not just
        # after the marker) because some codebases put the ticket
        # BEFORE the marker (``// #1234 TODO: fix this``).
        claimed: list[tuple[int, int]] = []
        # Pass 1: JIRA-style.
        for m in _TODO_TICKET_JIRA_RE.finditer(comment_body):
            ticket = m.group("ticket")
            out.append({"marker": marker, "ticket": ticket})
            claimed.append((m.start(), m.end()))
            if len(out) >= _MAX_TODO_TICKETS:
                return out
        # Pass 2: hash-slug (skip if overlaps a JIRA match).
        for m in _TODO_TICKET_HASH_SLUG_RE.finditer(comment_body):
            if _spans_overlap(m.start(), m.end(), claimed):
                continue
            ticket = "#" + m.group("slug")
            out.append({"marker": marker, "ticket": ticket})
            claimed.append((m.start(), m.end()))
            if len(out) >= _MAX_TODO_TICKETS:
                return out
        # Pass 3: hash-number (skip if overlaps anything earlier).
        for m in _TODO_TICKET_HASH_NUM_RE.finditer(comment_body):
            if _spans_overlap(m.start(), m.end(), claimed):
                continue
            ticket = "#" + m.group("num")
            out.append({"marker": marker, "ticket": ticket})
            claimed.append((m.start(), m.end()))
            if len(out) >= _MAX_TODO_TICKETS:
                return out
    return out


def _spans_overlap(start: int, end: int, claimed: list[tuple[int, int]]) -> bool:
    """Return True when (start, end) overlaps any (c_start, c_end) in claimed."""
    for c_start, c_end in claimed:
        if start < c_end and end > c_start:
            return True
    return False


# License-header detection. We scan the first ~30 lines of the snippet
# for the distinctive opening phrase of each common open-source
# license. Each license catalogues:
#
# * SPDX-style tag returned to the caller.
# * One or more substring "needles" that uniquely identify the
#   license. Needles are checked CASE-INSENSITIVELY and the FIRST
#   matching license in priority order wins.
#
# Priority order (longest / most distinctive first):
#
#   1. Apache-2.0   - "Licensed under the Apache License, Version 2.0"
#   2. AGPL-3.0    - "GNU Affero General Public License" + "version 3"
#   3. GPL-3.0     - "GNU General Public License" + "version 3"
#   4. GPL-2.0     - "GNU General Public License" + "version 2"
#   5. LGPL-3.0    - "GNU Lesser General Public License" + "version 3"
#   6. MPL-2.0     - "Mozilla Public License Version 2.0"
#   7. BSD-3-Clause - "All advertising materials" CLAUSE forbidden + 3-clause
#   8. BSD-2-Clause - "Redistributions of source code" + "Redistributions in binary form"
#   9. CC0-1.0     - "CC0 1.0 Universal" / "Creative Commons Zero"
#  10. Unlicense   - "This is free and unencumbered software released into the public domain"
#  11. ISC         - "Permission to use, copy, modify, and/or distribute"
#  12. MIT         - "Permission is hereby granted, free of charge"
#
# The MIT and ISC entries sit LAST because their distinctive phrasing
# overlaps with BSD headers (BSD also contains "permission is granted"
# wording). With this ordering, a full BSD-3-Clause header tags as
# ``bsd-3-clause`` -- not MIT. The scanner stops at the first hit.
_LICENSE_CATALOGUE: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    # Each license is (tag, ((needle_group_1), (needle_group_2), ...)).
    # ALL needles in a SINGLE group must be present (AND); ANY group
    # passing is enough to identify the license (OR across groups).
    ("apache-2.0", (
        ("apache license", "version 2.0"),
        ("licensed under the apache license",),
    )),
    ("agpl-3.0", (
        ("gnu affero general public license", "version 3"),
        ("agpl", "version 3"),
    )),
    ("gpl-3.0", (
        ("gnu general public license", "version 3"),
        ("gpl-3.0",),
        ("gplv3",),
    )),
    ("gpl-2.0", (
        ("gnu general public license", "version 2"),
        ("gpl-2.0",),
        ("gplv2",),
    )),
    ("lgpl-3.0", (
        ("gnu lesser general public license", "version 3"),
        ("lgpl-3.0",),
        ("lgplv3",),
    )),
    ("mpl-2.0", (
        ("mozilla public license", "version 2.0"),
        ("mpl-2.0",),
    )),
    ("bsd-3-clause", (
        ("redistribution and use", "neither the name", "redistributions in binary form"),
        ("bsd 3-clause",),
        ("bsd-3-clause",),
    )),
    ("bsd-2-clause", (
        ("redistribution and use", "redistributions of source code", "redistributions in binary form"),
        ("bsd 2-clause",),
        ("bsd-2-clause",),
    )),
    ("cc0-1.0", (
        ("cc0 1.0 universal",),
        ("creative commons zero",),
        ("cc0-1.0",),
    )),
    ("unlicense", (
        ("this is free and unencumbered software released into the public domain",),
        ("the unlicense",),
    )),
    ("isc", (
        ("permission to use, copy, modify, and/or distribute",),
        ("isc license",),
    )),
    ("mit", (
        ("permission is hereby granted, free of charge",),
        ("mit license",),
    )),
)
# Max lines of the snippet's header that we scan. A real license
# block is rarely longer than ~25 lines (the longest is GPL-3.0's
# preamble at 21 lines). We use 30 as a comfortable upper bound that
# still rules out a full file with one license-keyword comment buried
# halfway down.
_LICENSE_HEADER_LINES = 30


def detect_license(code: str) -> str | None:
    """Return the SPDX-style tag of an open-source license header
    detected in the first :data:`_LICENSE_HEADER_LINES` lines of
    ``code``, or ``None``.

    Recognised tags: ``apache-2.0`` / ``mit`` / ``gpl-3.0`` /
    ``gpl-2.0`` / ``lgpl-3.0`` / ``agpl-3.0`` / ``bsd-2-clause`` /
    ``bsd-3-clause`` / ``mpl-2.0`` / ``isc`` / ``unlicense`` /
    ``cc0-1.0``.

    Detection scans the snippet's header for the distinctive opening
    phrase of each license (catalogued in :data:`_LICENSE_CATALOGUE`).
    The first license whose needle group matches wins. Order matters:
    the longer / more-distinctive licenses (BSD-3-Clause, Apache 2.0)
    are checked BEFORE the shorter ones (MIT, ISC) so a full BSD
    header tags as ``bsd-3-clause`` rather than MIT (BSD headers also
    contain the ``permission is granted`` phrasing).

    Case-insensitive matching throughout. Whitespace and line breaks
    are flattened so a header wrapped onto multiple lines still
    matches the multi-needle requirement.
    """
    if not code or not code.strip():
        return None
    # Flatten the header to a single lowercased string with normalised
    # whitespace so multi-line needles (``Licensed under the Apache
    # License, Version 2.0``) still match when wrapped across two
    # comment lines. We also strip leading comment markers (``*``,
    # ``//``, ``#``, ``--``, ``;``) per-line so a C-style multi-line
    # comment with ``* `` line continuations doesn't break a needle
    # like ``mozilla public license`` across the asterisk boundary.
    header_lines = code.splitlines()[:_LICENSE_HEADER_LINES]
    cleaned: list[str] = []
    for raw in header_lines:
        line = raw.strip()
        # Strip the comment-leader prefix so wrapped phrases collapse
        # cleanly. We accept the four common single-char leaders and
        # the two-char ones.
        for leader in ("//", "/*", "*/", "--", "*", "#", ";", "%"):
            if line.startswith(leader):
                line = line[len(leader):].lstrip()
                break
        cleaned.append(line)
    flat = " ".join(cleaned).lower()
    # Collapse runs of whitespace so the comparison is robust to OCR
    # noise (multiple spaces / tabs between words).
    flat = re.sub(r"\s+", " ", flat)
    for tag, needle_groups in _LICENSE_CATALOGUE:
        for group in needle_groups:
            if all(needle in flat for needle in group):
                return tag
    return None


# Docstring / JSDoc extraction. We surface the first structured
# documentation block we can find at the top of the snippet so
# dashboards can show a one-sentence summary on a code-snippet card
# without an LLM round trip. Three families of documentation comment
# are recognised:
#
#   * Python triple-quoted docstrings (``\"\"\"...\"\"\"`` or ``'''...'''``)
#     either at module level (the very first non-blank statement) or
#     as the first statement inside the first top-level ``def`` /
#     ``class`` body. Both single-line and multi-line triple-quoted
#     strings are accepted; per-line indentation matching the wrapping
#     block is stripped from the surfaced body.
#   * JSDoc-style ``/** ... */`` blocks immediately above the first
#     top-level declaration (``function`` / ``class`` / ``const`` /
#     ``let`` / ``var`` in JS-family; ``public``/``private``/etc. in
#     Java/C#/Kotlin; ``func`` in Go/Swift; ``fn``/``pub fn`` in
#     Rust; ``def`` in Python and Ruby for completeness). The
#     ``/**`` / ``*/`` delimiters and the per-line ``*`` continuation
#     prefixes are stripped so the surfaced body reads as natural
#     prose.
#   * Rust ``///`` line-doc-comment runs (collapsed into one paragraph)
#     and ``//!`` inner-doc-comment runs. The ``///`` prefix is
#     stripped from each line; consecutive lines are joined with a
#     single space so dashboards render a clean one-paragraph summary.
#
# Detection rules:
#
#   1. We only look at the first 60 lines of the snippet. A docstring
#      that sits deeper than that is unlikely to be the top-level one
#      we want.
#   2. The block must be the FIRST documentation comment in the
#      snippet (we don't merge multiple blocks). If a JSDoc block
#      precedes a Python docstring (a weird hybrid case) the JSDoc
#      wins because it appears first.
#   3. The block must precede or be the body of a top-level
#      declaration. A floating ``/** ... */`` with no following
#      declaration is rejected as a free-form comment.
#
# We return the cleaned body verbatim -- no truncation, no summary
# extraction, no JSDoc-tag parsing (``@param`` / ``@returns`` are
# preserved as-is in the output). Future tickets can add structured
# tag parsing if dashboards ask for it.
_DOC_DECLARATION_RE = re.compile(
    r"^\s*(?:export\s+|public\s+|private\s+|protected\s+|static\s+|"
    r"async\s+|abstract\s+|final\s+|virtual\s+|override\s+|"
    r"@\w+(?:\([^)]*\))?\s+|pub\s+)*"
    r"(?:function|class|interface|type|enum|namespace|const|let|var|"
    r"def|func|fn|module|trait|impl|struct|object|companion)\b"
)

# Python decorator line. A docstring can sit below a string of
# decorators; we look past them to find the def/class.
_PYTHON_DECORATOR_RE = re.compile(r"^\s*@[\w.]+(?:\([^)]*\))?\s*$")

# Python def / class header. Followed by ``:`` so we don't bite into
# a type annotation that happens to use the word ``def``.
_PYTHON_DEF_HEADER_RE = re.compile(
    r"^(\s*)(?:async\s+)?(?:def|class)\s+\w+.*:\s*(?:#.*)?$"
)


def _clean_jsdoc_body(block: str) -> str:
    """Strip ``/**`` / ``*/`` delimiters and per-line ``*`` continuations.

    Joins the cleaned lines with ``\\n`` and trims leading/trailing
    whitespace so the surfaced body reads as natural prose.
    """
    body = block.strip()
    # Strip the leading ``/**`` and trailing ``*/``.
    if body.startswith("/**"):
        body = body[3:]
    elif body.startswith("/*"):
        body = body[2:]
    if body.endswith("*/"):
        body = body[:-2]
    # Per-line strip of ``*`` continuations. A line is either entirely
    # ``*`` whitespace (a separator) or ``* ...`` content (strip the
    # leader and one separator space).
    cleaned: list[str] = []
    for raw in body.splitlines():
        ln = raw.rstrip()
        stripped = ln.lstrip()
        if stripped.startswith("*"):
            after = stripped[1:]
            # Strip one separator space / tab if present.
            if after.startswith((" ", "\t")):
                after = after[1:]
            cleaned.append(after.rstrip())
        else:
            cleaned.append(stripped.rstrip())
    # Collapse leading / trailing blank lines and trim outer whitespace.
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return "\n".join(cleaned).strip()


def _clean_python_docstring(body: str) -> str:
    """Dedent and trim a Python docstring body.

    Mirrors ``inspect.cleandoc`` semantics: strips leading/trailing
    blank lines, then dedents by the minimum indentation of the
    non-first lines. The triple-quote delimiters are expected to be
    already stripped before this is called.
    """
    lines = body.splitlines()
    if not lines:
        return ""
    first = lines[0]
    rest = lines[1:]
    # Strip leading / trailing blank lines from rest.
    while rest and not rest[-1].strip():
        rest.pop()
    if rest:
        indents = [len(ln) - len(ln.lstrip()) for ln in rest if ln.strip()]
        if indents:
            common = min(indents)
            rest = [ln[common:] if ln.strip() else "" for ln in rest]
    out = first.strip() + ("\n" + "\n".join(rest) if rest else "")
    return out.strip()


def _extract_jsdoc_block(lines: list[str]) -> str | None:
    """Find a ``/** ... */`` block immediately above a declaration.

    Scans the first 60 lines for a ``/**`` start, walks forward until
    the matching ``*/``, then checks that the NEXT non-blank line
    (skipping decorator-only lines) looks like a top-level
    declaration. Returns the cleaned docstring body on success,
    ``None`` otherwise.
    """
    window = lines[:60]
    n = len(window)
    i = 0
    while i < n:
        ln = window[i].lstrip()
        is_jsdoc = (
            ln.startswith("/**")
            or (
                ln.startswith("/*")
                and "*/" not in ln
                and i + 1 < n
                and window[i + 1].lstrip().startswith("*")
            )
        )
        if is_jsdoc:
            # Walk forward to find ``*/``.
            block_lines = [window[i]]
            if "*/" in ln:
                # Single-line ``/** ... */``.
                end = i
            else:
                end = -1
                for j in range(i + 1, n):
                    block_lines.append(window[j])
                    if "*/" in window[j]:
                        end = j
                        break
                if end < 0:
                    return None
            # Find the next non-blank line after the block, walking
            # past any decorator-only lines (``@Foo(...)`` on its own
            # line is common for Angular / NestJS / Java annotations).
            k = end + 1
            while k < n:
                stripped = window[k].strip()
                if not stripped:
                    k += 1
                    continue
                # A pure decorator/annotation line followed by a
                # declaration on the next line is treated as part of
                # the declaration -- skip past it.
                if re.match(r"^@\w[\w.]*(?:\([^)]*\))?\s*$", stripped):
                    k += 1
                    continue
                break
            if k >= n:
                # Block sits at the very tail of our window with no
                # following declaration -- treat as a floating comment.
                return None
            following = window[k]
            if not _DOC_DECLARATION_RE.match(following):
                return None
            return _clean_jsdoc_body("\n".join(block_lines))
        # Skip non-doc comments and shebang lines without consuming
        # them as the doc block.
        i += 1
    return None


def _extract_rust_doc_block(lines: list[str]) -> str | None:
    """Collapse a run of ``///`` or ``//!`` line-doc comments.

    Returns the joined paragraph (lines joined with ``\\n``) when at
    least one such line is found AND a top-level declaration follows
    the run. ``None`` otherwise.
    """
    window = lines[:60]
    n = len(window)
    i = 0
    # Skip leading blanks and a possible shebang line.
    while i < n and (not window[i].strip() or window[i].lstrip().startswith("#!")):
        i += 1
    if i >= n:
        return None
    # Identify the start of a doc-comment run.
    start = i
    has_doc = False
    prefix: str | None = None
    while i < n:
        stripped = window[i].lstrip()
        if stripped.startswith("///"):
            if prefix is None:
                prefix = "///"
            if prefix == "///":
                has_doc = True
                i += 1
                continue
            break
        if stripped.startswith("//!"):
            if prefix is None:
                prefix = "//!"
            if prefix == "//!":
                has_doc = True
                i += 1
                continue
            break
        break
    if not has_doc:
        return None
    # The run is window[start:i]. The next non-blank line must look
    # like a Rust top-level declaration so we don't grab a free-form
    # doc comment that floats in the middle of a file.
    k = i
    while k < n and not window[k].strip():
        k += 1
    if k < n and not _DOC_DECLARATION_RE.match(window[k]):
        # Inner-doc-comments (``//!``) often sit at the top of a
        # module without an immediately-following declaration --
        # accept that case unconditionally.
        if prefix != "//!":
            return None
    # Strip the prefix from each line of the run and trim whitespace.
    cleaned: list[str] = []
    assert prefix is not None
    for ln in window[start:i]:
        stripped = ln.lstrip()
        body = stripped[len(prefix):]
        if body.startswith((" ", "\t")):
            body = body[1:]
        cleaned.append(body.rstrip())
    return "\n".join(cleaned).strip()


def _extract_python_docstring(lines: list[str]) -> str | None:
    """Find a Python triple-quoted docstring.

    Two valid positions:
      * Module-level: the very first non-blank, non-comment statement.
      * Inside the first top-level def/class body, as the first
        statement (after any decorators).

    Returns the cleaned docstring body (dedented, surrounding
    quotes stripped) or ``None``.
    """
    window = lines[:60]
    n = len(window)
    i = 0
    # Skip leading blanks, shebangs, encoding comments, and bare
    # comment lines.
    while i < n:
        stripped = window[i].strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("#"):
            i += 1
            continue
        # `from __future__` lines are allowed before a module docstring
        # in some snippet shapes; we still look past them when scanning.
        break
    if i >= n:
        return None
    # 1) Module-level docstring: first statement is a triple-quoted string.
    first = window[i].lstrip()
    for quote in ('"""', "'''"):
        if first.startswith(quote):
            return _read_python_triple_string(window, i, quote)
    # 2) Look for the first top-level def/class and inspect its body
    #    for a docstring. Skip past decorator lines.
    while i < n:
        ln = window[i]
        stripped = ln.strip()
        if not stripped:
            i += 1
            continue
        if _PYTHON_DECORATOR_RE.match(ln):
            i += 1
            continue
        m = _PYTHON_DEF_HEADER_RE.match(ln)
        if not m:
            return None
        # Body starts on the next non-blank line.
        j = i + 1
        while j < n and not window[j].strip():
            j += 1
        if j >= n:
            return None
        body_first = window[j].lstrip()
        for quote in ('"""', "'''"):
            if body_first.startswith(quote):
                return _read_python_triple_string(window, j, quote)
        return None
    return None


def _read_python_triple_string(lines: list[str], start: int, quote: str) -> str | None:
    """Read a triple-quoted Python string starting at ``lines[start]``."""
    head = lines[start].lstrip()
    # Single-line form: ``\"\"\"summary\"\"\"`` on one line.
    rest_of_head = head[len(quote):]
    if quote in rest_of_head:
        end_idx = rest_of_head.index(quote)
        body = rest_of_head[:end_idx]
        return body.strip()
    # Multi-line form: walk until the closing triple-quote.
    captured: list[str] = [rest_of_head]
    for j in range(start + 1, min(len(lines), start + 60)):
        ln = lines[j]
        if quote in ln:
            end_idx = ln.index(quote)
            captured.append(ln[:end_idx])
            return _clean_python_docstring("\n".join(captured))
        captured.append(ln)
    return None


def detect_docstring(code: str, language: str | None = None) -> str | None:
    """Return the cleaned top-level docstring / JSDoc body, or ``None``.

    Recognised positions (matched in declaration-order):

    * JSDoc ``/** ... */`` block immediately above the first top-level
      declaration. Works for JS / TS / Java / Go / C / C++ / C# /
      Kotlin / Swift / Rust / PHP -- anywhere the JSDoc convention is
      used.
    * Rust ``///`` / ``//!`` line-doc-comment run (only when the
      detected language looks like Rust).
    * Python triple-quoted docstring at module level or as the first
      statement inside the first top-level ``def`` / ``class`` body.

    The first family that yields a non-empty body wins. The
    ``language`` argument biases the priority order so a Python
    snippet checks the Python form first (skipping the JSDoc scan),
    while a JS / TS snippet checks JSDoc first.
    """
    if not code or not code.strip():
        return None
    lines = code.splitlines()
    lang = (language or "").lower()
    # Python-family first when we know the language is Python.
    if lang in {"python", "py"}:
        py = _extract_python_docstring(lines)
        if py:
            return py
        return None
    # Rust-family: prefer ``///`` / ``//!`` line doc-comments.
    if lang in {"rust", "rs"}:
        rs = _extract_rust_doc_block(lines)
        if rs:
            return rs
        js = _extract_jsdoc_block(lines)
        if js:
            return js
        return None
    # Default ordering: JSDoc -> Python -> Rust line-doc. The JSDoc
    # form is by far the most common in mixed-language repos.
    js = _extract_jsdoc_block(lines)
    if js:
        return js
    py = _extract_python_docstring(lines)
    if py:
        return py
    rs = _extract_rust_doc_block(lines)
    if rs:
        return rs
    return None


# Import / require / use extraction. We scan the snippet for the
# major import syntaxes used across mainstream languages and surface
# the most-canonical short identifier for each. The detector is
# deliberately deterministic and regex-based -- we don't want a
# heavyweight per-language parser dependency, and OCR text is messy
# enough that a strict parser would reject many real-world snippets.
#
# Recognised syntaxes (regex priority is most-specific-first):
#
#   * Python ``from X import a, b``  -> X (just the module)
#   * Python ``import X.Y as Z``     -> X.Y
#   * Python ``import X, Y, Z``      -> X, Y, Z (comma-separated list)
#   * JS / TS ``import { a, b } from 'X'`` / ``import X from 'X'`` ->
#     X (the quoted module name)
#   * JS / TS ``import 'X'``         -> X (side-effect import)
#   * JS ``require('X')`` / ``require("X")`` -> X
#   * Java / Kotlin / Scala ``import X.Y.Z`` / ``import X.*`` -> X.Y.Z / X.*
#   * Go ``import "X"`` (single) / parenthesised group with one quoted
#     module per line.
#   * Rust ``use X::Y::Z;`` -> X::Y::Z; also handles braced re-export
#     ``use X::Y::{A, B};`` by capturing the prefix ``X::Y``.
#   * Ruby ``require 'X'`` / ``require_relative './X'`` -> X / ./X.
#   * PHP ``use Foo\\Bar\\Baz`` / ``require_once 'X'`` -> Foo\\Bar\\Baz / X.
#
# Capped at 50 entries; de-duplicated case-sensitively (mirrors how
# package managers treat the names); first-seen order preserved.
_MAX_IMPORTS = 50

# Python `from X import ...`. We capture X.
_PY_FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+(?P<mod>\.+|\.*[A-Za-z_][\w.]*)\s+import\s+",
    re.MULTILINE,
)
# Python `import X` / `import X as Y` / `import X, Y, Z`. We capture
# the comma list, then split.
_PY_IMPORT_RE = re.compile(
    r"^\s*import\s+(?P<mods>[\w. ,]+?)(?:\s+as\s+\w+)?\s*$",
    re.MULTILINE,
)

# JS / TS `import ... from 'X'` / `import ... from "X"`. Captures X.
# The leading import head can be a default name, a `{ a, b }` named
# list, a `* as ns` namespace import, or any combination.
_JS_IMPORT_FROM_RE = re.compile(
    r"""^\s*import\s+
        (?:
            [\w*${},\s]+
            \s+from\s+
        )?
        ['"](?P<mod>[^'"]+)['"]\s*;?\s*$
    """,
    re.MULTILINE | re.VERBOSE,
)
# JS `require('X')` / `require("X")`. Anchored on the call so a string
# argument elsewhere in the snippet doesn't false-positive.
_JS_REQUIRE_RE = re.compile(r"\brequire\s*\(\s*['\"](?P<mod>[^'\"]+)['\"]\s*\)")

# Java / Kotlin / Scala `import com.foo.Bar;` or `import com.foo.*;`.
# Bounded so we don't capture trailing whitespace / comment.
_JVM_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:static\s+)?(?P<mod>[\w.]+(?:\.\*)?)\s*;?\s*(?://.*)?$",
    re.MULTILINE,
)

# Go single-line `import "X"`. Captures X. Distinct from Python's
# `import X` because Go requires quotes around the import path.
_GO_IMPORT_SINGLE_RE = re.compile(
    r"^\s*import\s+(?:\w+\s+)?\"(?P<mod>[^\"]+)\"\s*$",
    re.MULTILINE,
)

# Rust `use std::collections::HashMap;` / `use foo::{a, b};`.
_RUST_USE_RE = re.compile(
    r"^\s*(?:pub\s+)?use\s+(?P<mod>[\w:]+(?:::\{[^}]*\})?)\s*;?\s*$",
    re.MULTILINE,
)

# Ruby `require 'X'` / `require "X"` / `require_relative './X'`.
_RUBY_REQUIRE_RE = re.compile(
    r"^\s*(?:require|require_relative|load|autoload)\s+(?:['\"])(?P<mod>[^'\"]+)(?:['\"])\s*$",
    re.MULTILINE,
)

# PHP `use Foo\\Bar\\Baz;` (namespace import).
_PHP_USE_RE = re.compile(
    r"^\s*use\s+(?:function\s+|const\s+)?(?P<mod>\\?[A-Za-z_][\\\w]*(?:\\[A-Za-z_][\\\w]*)*)"
    r"(?:\s+as\s+\w+)?\s*;\s*$",
    re.MULTILINE,
)
# PHP `require 'X'` / `require_once "X"` / `include "X"`.
_PHP_INCLUDE_RE = re.compile(
    r"^\s*(?:require_once|require|include_once|include)\s*\(?\s*['\"](?P<mod>[^'\"]+)['\"]\s*\)?\s*;\s*$",
    re.MULTILINE,
)


def _extract_go_grouped_imports(text: str) -> list[tuple[int, str]]:
    """Return ``(offset, module)`` tuples for Go ``import ( ... )`` blocks.

    Walks the snippet for parenthesised import groups and extracts
    each quoted module path from inside. Returns the source-text
    offset of each match for stable ordering.
    """
    out: list[tuple[int, str]] = []
    for m in re.finditer(r"^\s*import\s*\(\s*$", text, re.MULTILINE):
        start = m.end()
        end = text.find(")", start)
        if end < 0:
            continue
        body = text[start:end]
        for sm in re.finditer(r"(?:\w+\s+)?\"([^\"]+)\"", body):
            out.append((start + sm.start(), sm.group(1)))
    return out


def extract_imports(code: str, language: str | None = None) -> list[str]:
    """Return the import / require / use statements found in ``code``.

    The detector runs every language's matcher against the snippet and
    deduplicates the result. We do NOT gate by ``language`` because OCR
    captures often mix shells, configs, and code -- a snippet tagged as
    ``shell`` may still contain an ``import`` line from a heredoc.
    Output preserves first-seen-in-text order across all matchers.

    The ``language`` argument is accepted but currently unused; we keep
    it in the signature so callers can pass a hint without rework if a
    future revision wants to use it.
    """
    if not code or not code.strip():
        return []
    _ = language  # reserved for future per-language tuning
    candidates: list[tuple[int, str]] = []

    # 1) Python `from X import ...` -- captures the module side only.
    for m in _PY_FROM_IMPORT_RE.finditer(code):
        mod = m.group("mod").strip()
        if mod:
            candidates.append((m.start(), mod))

    # 2) Python `import X` / `import X.Y as Z` / `import X, Y`.
    #    Split on commas to handle the multi-import form.
    for m in _PY_IMPORT_RE.finditer(code):
        mods_raw = m.group("mods").strip()
        # Skip the JVM-style `import com.foo.Bar;` which the JVM regex
        # picks up too -- but harmless because we de-dupe afterward.
        # Reject if the body contains characters Python imports don't
        # have (e.g. starting with `*`, common in JVM `.*` wildcards).
        if "*" in mods_raw:
            continue
        for mod in mods_raw.split(","):
            mod = mod.strip()
            # Strip trailing `as alias` from individual entries (rare
            # but legal: `import x as a, y as b`).
            if " as " in mod:
                mod = mod.split(" as ", 1)[0].strip()
            if mod:
                candidates.append((m.start(), mod))

    # 3) JS / TS `import ... from 'X'` and bare `import 'X'`.
    for m in _JS_IMPORT_FROM_RE.finditer(code):
        candidates.append((m.start(), m.group("mod")))

    # 4) JS `require('X')`.
    for m in _JS_REQUIRE_RE.finditer(code):
        candidates.append((m.start(), m.group("mod")))

    # 5) Java / Kotlin / Scala `import com.foo.Bar;` -- captured by
    #    the JVM regex which requires the trailing `;`. We accept
    #    `import com.foo.*;` (wildcard) as a single entry.
    for m in _JVM_IMPORT_RE.finditer(code):
        candidates.append((m.start(), m.group("mod")))

    # 6) Go single-line `import "X"` and grouped `import ( ... )`.
    for m in _GO_IMPORT_SINGLE_RE.finditer(code):
        candidates.append((m.start(), m.group("mod")))
    for offset, mod in _extract_go_grouped_imports(code):
        candidates.append((offset, mod))

    # 7) Rust `use a::b::c;` / `use a::b::{c, d};`.
    for m in _RUST_USE_RE.finditer(code):
        mod = m.group("mod").strip()
        # If the import uses a braced re-export, strip the brace tail
        # and keep the prefix.
        if "::{" in mod:
            mod = mod.split("::{", 1)[0]
        if mod:
            candidates.append((m.start(), mod))

    # 8) Ruby `require 'X'`.
    for m in _RUBY_REQUIRE_RE.finditer(code):
        candidates.append((m.start(), m.group("mod")))

    # 9) PHP `use Foo\\Bar\\Baz;` and `require_once 'X';`.
    for m in _PHP_USE_RE.finditer(code):
        mod = m.group("mod").lstrip("\\")
        if mod:
            candidates.append((m.start(), mod))
    for m in _PHP_INCLUDE_RE.finditer(code):
        candidates.append((m.start(), m.group("mod")))

    # Order by source-text offset so the list matches reading order.
    candidates.sort(key=lambda x: x[0])
    seen: set[str] = set()
    out: list[str] = []
    for _off, mod in candidates:
        if mod in seen:
            continue
        seen.add(mod)
        out.append(mod)
        if len(out) >= _MAX_IMPORTS:
            break
    return out


# Copyright-holder extraction. We scan the first 30 lines of the
# snippet for a ``Copyright`` / ``(c)`` / ``(C)`` header and capture
# each ``{holder, year}`` pair found. The same header window is used
# by ``detect_license`` so the two detectors run against the same
# slice of the snippet.
#
# Recognised vocabularies (case-insensitive):
#
#   Copyright (c) 2024 ACME Corp
#   Copyright (C) 2020-2024 Alice Author
#   (c) 2024 ACME, All rights reserved.
#   (C) 2024 ACME Corp.
#   Copyright 2024 ACME Corp           (no (c) marker)
#   COPYRIGHT 2024 ACME CORP           (uppercase)
#
# Year shapes captured (preserved as printed):
#
#   2024                       single year
#   2020-2024                  range
#   2020, 2021, 2024           list (commas + spaces preserved)
#   2020, 2022-2024            mixed list + range
#
# Edge cases handled:
#
# * Per-line comment leaders (``//``, ``/*``, ``*``, ``#``, ``--``,
#   ``;``, ``%``) are stripped before parsing so a C-style header
#   comment doesn't carry the leader into the captured holder name.
# * ``All rights reserved`` and trailing ``.`` / ``,`` are stripped
#   from the captured holder name.
# * Multiple holders printed across multiple lines (a derived work
#   with both upstream and downstream copyrights) all surface as
#   separate entries. De-duplication is on the (holder, year)
#   pair, NOT on holder alone -- two copyrights with different
#   years are kept distinct.
_COPYRIGHT_HEADER_LINES = 30

# Year-token regex: a 4-digit year, or a list of comma- or hyphen-
# separated years. We allow whitespace between the separators so the
# printer can choose its preferred style.
_YEAR_TOKEN = r"\d{4}(?:\s*[-,]\s*\d{4})*"

# Holder-name regex: everything from after the year up to a sentence
# terminator (``.`` at end of line) or a hard separator (``;``).
# Trailing ``All rights reserved`` is stripped post-match.
_HOLDER_TAIL = r"(?P<holder>.+?)(?:\s*[.;]?\s*(?:all\s+rights\s+reserved)?\s*)?$"

# Full copyright regex. The leading marker is one of:
#   * ``copyright`` word
#   * literal ``(c)`` / ``(C)``
#   * literal ``©`` (Unicode copyright sign)
# followed optionally by an additional ``(c)`` / ``(C)`` / ``©``
# marker, then the year-token, then the holder name.
_COPYRIGHT_RE = re.compile(
    r"(?:copyright|\(c\)|©)"
    r"(?:\s*(?:\(c\)|©))?"
    r"\s+(?P<year>" + _YEAR_TOKEN + r")"
    r"(?:\s+by)?"
    r"\s+" + _HOLDER_TAIL,
    re.IGNORECASE | re.MULTILINE,
)


def _strip_copyright_leader(line: str) -> str:
    """Strip the leading comment leader from a header line."""
    s = line.strip()
    # Two-char leaders first so ``//`` and ``/*`` don't get clipped to ``/``.
    for leader in ("//", "/*", "*/", "--"):
        if s.startswith(leader):
            return s[len(leader):].lstrip()
    # Single-char leaders.
    if s and s[0] in "*#;%":
        return s[1:].lstrip()
    return s


def _clean_holder(raw: str) -> str:
    """Trim the trailing ``All rights reserved`` / punctuation cruft."""
    s = raw.strip()
    # Strip a trailing ``All rights reserved`` (the word "rights" is
    # the unique signal so we don't accidentally clip a real name).
    s = re.sub(r"\s*[,.]?\s*all\s+rights\s+reserved\.?$", "", s, flags=re.IGNORECASE)
    # Strip a final block-comment terminator if the holder ends adjacent
    # to a C-style header (`/* ... ACME Corp */`).
    s = re.sub(r"\s*\*/\s*$", "", s)
    # Strip trailing punctuation.
    s = s.rstrip(".,;:")
    return s.strip()


def extract_copyrights(code: str) -> list[dict[str, str]]:
    """Return a list of ``{holder, year}`` dicts found in the snippet's header.

    Scans the first :data:`_COPYRIGHT_HEADER_LINES` lines and matches
    every distinct copyright statement. Multiple holders on separate
    lines (or comma-separated on the same line) all surface. The
    captured year is the as-printed token (a single year, a range, or
    a list); the holder is trimmed of trailing ``All rights reserved``
    boilerplate and punctuation.
    """
    if not code or not code.strip():
        return []
    header_lines = code.splitlines()[:_COPYRIGHT_HEADER_LINES]
    cleaned = [_strip_copyright_leader(ln) for ln in header_lines]
    body = "\n".join(cleaned)
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in _COPYRIGHT_RE.finditer(body):
        year = m.group("year").strip()
        # Collapse the year token whitespace so ``2020 - 2024`` becomes
        # ``2020-2024`` and ``2020 , 2021`` becomes ``2020, 2021``.
        year = re.sub(r"\s*-\s*", "-", year)
        year = re.sub(r"\s*,\s*", ", ", year)
        holder = _clean_holder(m.group("holder"))
        if not holder:
            continue
        key = (holder.lower(), year)
        if key in seen:
            continue
        seen.add(key)
        out.append({"holder": holder, "year": year})
    return out


# Feature-flag SDK call detection. Modern feature-flag clients expose
# a small set of canonical call shapes per vendor. We recognise the
# top-of-mind vendors -- LaunchDarkly, Statsig, Unleash, Optimizely,
# Split.io, PostHog, Flagsmith, ConfigCat -- and capture the flag key
# argument.
#
# Recognised SDK shapes (regex priority is vendor-specific so a
# given call site can only match one vendor):
#
#   LaunchDarkly:
#     ldClient.variation("flag-key", user, false)
#     client.variation("flag-key", ...)
#     boolVariation("flag-key", ...)
#     stringVariation("flag-key", ...)
#     jsonVariation("flag-key", ...)
#     numberVariation("flag-key", ...)
#     ld.variation_detail("flag-key", ...)            (Python SDK)
#
#   Statsig:
#     Statsig.checkGate("flag-key")
#     statsig.check_gate("flag-key")                   (Python SDK)
#     getExperiment("exp-name")
#     statsig.getExperiment("exp-name")
#     getConfig("config-name")
#     statsig.getConfig("config-name")
#
#   Unleash:
#     unleash.isEnabled("flag-key")
#     client.isEnabled("flag-key")                     (Node / Java)
#     is_enabled("flag-key")                           (Python)
#
#   Optimizely:
#     optimizely.isFeatureEnabled("flag-key", userId)
#     optimizelyClient.activate("exp-key", userId)
#     is_feature_enabled("flag-key", userId)           (Python)
#     get_feature_variable_string("flag-key", ...)
#
#   Split.io:
#     client.getTreatment("flag-key", userId)
#     splitClient.getTreatment("flag-key", ...)
#     get_treatment("flag-key", userId)                (Python)
#
#   PostHog:
#     posthog.isFeatureEnabled("flag-key", userId)
#     posthog.is_feature_enabled("flag-key", userId)
#     posthog.getFeatureFlag("flag-key", userId)
#     getFeatureFlag("flag-key")
#
#   Flagsmith:
#     flagsmith.hasFeature("flag-key")
#     flagsmith.has_feature("flag-key")                (Python)
#     flags.is_feature_enabled("flag-key")
#
#   ConfigCat:
#     configcat.getValue("flag-key", false)
#     configcat.get_value("flag-key", false)           (Python)
#     configCatClient.getValue("flag-key", false)
#
# Flag keys captured: 1..128 chars from the set ``[A-Za-z0-9._-]`` so
# we accept the dashed (``feature-new-checkout``), dotted
# (``new.checkout.feature``), and snake_case (``feature_new_checkout``)
# conventions all three SDKs encourage. Spaces and special chars in
# flag keys are rejected because every vendor's documentation
# discourages them.
#
# Each pattern uses a named capture group ``key`` so the calling
# code can pull the flag key by name. The shape is documented per-
# vendor in the regex comments so the catalogue stays maintainable.
_FLAG_KEY = r"[A-Za-z][A-Za-z0-9._-]{0,127}"
_QUOTED_FLAG_KEY = rf"['\"](?P<key>{_FLAG_KEY})['\"]"

# Each entry is (vendor_tag, regex). Vendor tag is the lowercase
# short name. Regex must include a (?P<key>...) named group.
_FEATURE_FLAG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # LaunchDarkly: ``.variation(...)`` family. The ``\b\w*variation\b``
    # form catches ``variation`` / ``boolVariation`` / ``stringVariation``
    # / ``variation_detail`` etc. Same for the ``\w*Variation``
    # casing.
    (
        "launchdarkly",
        re.compile(
            r"\b(?:ld[A-Za-z]*Client|ldClient|ld|client)?"
            r"\.?(?:bool|string|number|json|int)?[Vv]ariation"
            r"(?:_detail|Detail)?"
            r"\s*\(\s*" + _QUOTED_FLAG_KEY,
        ),
    ),
    # Statsig: ``checkGate`` (camelCase JS/Java) /
    # ``check_gate`` (snake Python). Also ``getExperiment`` /
    # ``get_experiment``, ``getConfig`` / ``get_config``.
    (
        "statsig",
        re.compile(
            r"\b(?:[Ss]tatsig\.)?"
            r"(?:checkGate|check_gate|getExperiment|get_experiment"
            r"|getConfig|get_config|getLayer|get_layer)"
            r"\s*\(\s*" + _QUOTED_FLAG_KEY,
        ),
    ),
    # Unleash: ``isEnabled`` (JS/Java) / ``is_enabled`` (Python).
    # The prefix is one of ``unleash`` / ``client`` / ``Unleash`` /
    # bare (Python convenience).
    (
        "unleash",
        re.compile(
            r"\b(?:unleash|Unleash|client|toggleClient)"
            r"\.(?:isEnabled|is_enabled|isToggleEnabled)"
            r"\s*\(\s*" + _QUOTED_FLAG_KEY,
        ),
    ),
    # Optimizely: ``isFeatureEnabled`` / ``is_feature_enabled``,
    # ``activate`` / ``getVariation`` / ``getFeatureVariableString``
    # / ``get_feature_variable_string``.
    (
        "optimizely",
        re.compile(
            r"\b(?:optimizely|optimizelyClient|Optimizely)"
            r"\.(?:isFeatureEnabled|is_feature_enabled|activate"
            r"|getVariation|get_variation"
            r"|getFeatureVariable[A-Za-z]*|get_feature_variable_[a-z]+)"
            r"\s*\(\s*" + _QUOTED_FLAG_KEY,
        ),
    ),
    # Split.io: ``getTreatment`` / ``get_treatment`` / ``getTreatments``
    # / ``get_treatments``. Prefix is one of ``client`` /
    # ``splitClient`` / ``split`` / ``factory``.
    (
        "split",
        re.compile(
            r"\b(?:client|splitClient|split|factoryClient|SplitClient)"
            r"\.(?:getTreatment|get_treatment|getTreatments|get_treatments"
            r"|getTreatmentWithConfig|get_treatment_with_config)"
            r"\s*\(\s*" + _QUOTED_FLAG_KEY,
        ),
    ),
    # PostHog: ``isFeatureEnabled`` / ``is_feature_enabled`` /
    # ``getFeatureFlag`` / ``get_feature_flag``.
    (
        "posthog",
        re.compile(
            r"\b(?:posthog|PostHog)"
            r"\.(?:isFeatureEnabled|is_feature_enabled"
            r"|getFeatureFlag|get_feature_flag|getFeatureFlagPayload"
            r"|get_feature_flag_payload)"
            r"\s*\(\s*" + _QUOTED_FLAG_KEY,
        ),
    ),
    # Flagsmith: ``hasFeature`` / ``has_feature`` /
    # ``is_feature_enabled`` (the latter conflicts with PostHog name
    # but the prefix differs).
    (
        "flagsmith",
        re.compile(
            r"\b(?:flagsmith|flags|Flagsmith)"
            r"\.(?:hasFeature|has_feature|is_feature_enabled|isFeatureEnabled"
            r"|getValue|get_value|getFeatureValue|get_feature_value)"
            r"\s*\(\s*" + _QUOTED_FLAG_KEY,
        ),
    ),
    # ConfigCat: ``getValue`` / ``get_value`` / ``getValueAsync``.
    (
        "configcat",
        re.compile(
            r"\b(?:configcat|configCatClient|ConfigCat|configCat)"
            r"\.(?:getValue|get_value|getValueAsync|getValueDetails"
            r"|get_value_details)"
            r"\s*\(\s*" + _QUOTED_FLAG_KEY,
        ),
    ),
)

# Max entries returned. Real snippets reference at most a handful of
# flags; the cap is defensive.
_MAX_FEATURE_FLAGS = 50


def extract_feature_flags(code: str) -> list[dict[str, str]]:
    """Return the feature-flag SDK call sites found in ``code``.

    Output is a list of ``{"vendor", "key"}`` dicts. The ``vendor``
    tag is the lowercase short name of the recognised feature-flag
    vendor (``launchdarkly`` / ``statsig`` / ``unleash`` /
    ``optimizely`` / ``split`` / ``posthog`` / ``flagsmith`` /
    ``configcat``). The ``key`` is the flag key passed as the first
    string argument to the call.

    Each pattern is vendor-specific so a given call site only matches
    one vendor. The matchers run in catalogue order; a snippet that
    contains multiple vendors' calls yields multiple entries (one per
    distinct ``(vendor, key)`` pair).

    De-duplicates on the ``(vendor, key)`` pair, preserving first-seen-
    in-text order. Capped at :data:`_MAX_FEATURE_FLAGS` entries.

    Flag keys are matched as ``[A-Za-z][A-Za-z0-9._-]{0,127}`` so the
    common dashed / dotted / snake_case conventions all parse, but a
    space-containing key (which every vendor's documentation
    discourages) is rejected.

    Returns an empty list when no recognised SDK call site is present.
    """
    if not code or not code.strip():
        return []
    candidates: list[tuple[int, str, str]] = []
    for vendor, pattern in _FEATURE_FLAG_PATTERNS:
        for m in pattern.finditer(code):
            key = m.group("key")
            if key:
                candidates.append((m.start(), vendor, key))
    # Sort by source-text offset so the order matches reading order.
    candidates.sort(key=lambda x: x[0])
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _off, vendor, key in candidates:
        dedupe_key = (vendor, key)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append({"vendor": vendor, "key": key})
        if len(out) >= _MAX_FEATURE_FLAGS:
            break
    return out


# CSS vendor-prefix detection. CSS-family snippets (css / scss /
# sass / less / stylus) sometimes still ship vendor-prefixed
# properties for legacy browser support. We surface the unique set
# of prefixes used so dashboards can flag stylesheets that can be
# modernised:
#
#   ``-webkit-``  -- Chrome / Safari / Edge (still common for
#                    text-fill / appearance / scrollbar shadow)
#   ``-moz-``     -- Firefox (almost-extinct now; some -moz-osx-
#                    rules linger on macOS-specific code paths)
#   ``-ms-``      -- Internet Explorer / legacy Edge (essentially
#                    dead in modern stacks)
#   ``-o-``       -- Opera Presto (dead since 2013)
#   ``-khtml-``   -- Konqueror (dead since 2010)
#
# Detection rule: scan the CSS body for any token matching
# ``-(webkit|moz|ms|o|khtml)-`` followed by an identifier-start
# char (letter or hyphen). Both property names (``-webkit-transform``)
# and CSS function calls (``-webkit-linear-gradient(...)``) qualify.
# The detector is language-gated so non-CSS snippets that happen to
# contain a ``-webkit-`` substring in a comment / string don't
# false-positive.
#
# Output is the list of unique prefixes found, in first-seen-in-text
# order, each with its trailing hyphen preserved (``-webkit-``, NOT
# ``webkit``) so dashboards can render the canonical CSS-property
# form verbatim.
_CSS_VENDOR_PREFIX_RE = re.compile(r"-(?P<vendor>webkit|moz|ms|o|khtml)-[A-Za-z]")

# Languages where the prefix detector runs. CSS preprocessors share
# the property-declaration syntax so vendor prefixes appear in all of
# them. ``css`` is the obvious one; ``scss`` / ``sass`` / ``less`` /
# ``stylus`` all carry the same vendor-prefix vocabulary.
_CSS_LANGUAGES = frozenset({"css", "scss", "sass", "less", "stylus"})


def detect_css_vendor_prefixes(
    code: str, language: str | None = None
) -> list[str]:
    """Return the unique set of CSS vendor prefixes used in ``code``.

    Each entry includes the leading and trailing hyphen so the output
    is directly usable as a property-prefix in CSS rendering
    (``-webkit-``, ``-moz-``, ``-ms-``, ``-o-``, ``-khtml-``).

    Language-gated with a content fallback: we run the matcher when
    ``language`` is in :data:`_CSS_LANGUAGES` OR when the snippet
    contains BOTH a vendor-prefix candidate AND a property-declaration
    marker (``:`` followed by a value-like token and a ``;`` /
    closing brace within 200 chars). This double-check lets us still
    surface prefixes when the language detector mis-tagged a CSS
    snippet (pygments occasionally returns ``gas`` / ``text`` for
    short CSS bodies) while keeping a JS comment that mentions
    ``-webkit-`` from false-positiving.

    First-seen-in-text order preserved. The maximum theoretical
    output length is 5 (the 5 vendor prefixes), so no cap is enforced.
    """
    if not code or not code.strip():
        return []
    lang_ok = False
    if language is not None:
        lang = language.lower().strip()
        if lang in _CSS_LANGUAGES:
            lang_ok = True
    if not lang_ok:
        # Content fallback: require a vendor-prefix candidate AND a CSS-
        # like property declaration nearby. The check is intentionally
        # local (look at +/-200 chars around each candidate) so a
        # comment-only mention of ``-webkit-`` in a JS file does NOT
        # qualify.
        for m in _CSS_VENDOR_PREFIX_RE.finditer(code):
            start = max(0, m.start() - 200)
            end = min(len(code), m.end() + 200)
            window = code[start:end]
            # CSS property declaration shape: ``property: value;`` --
            # need a colon followed by characters then a semicolon
            # somewhere in the window.
            if _CSS_DECL_RE.search(window):
                lang_ok = True
                break
    if not lang_ok:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _CSS_VENDOR_PREFIX_RE.finditer(code):
        prefix = f"-{m.group('vendor')}-"
        if prefix in seen:
            continue
        seen.add(prefix)
        out.append(prefix)
    return out


# CSS-declaration shape used by the content fallback. ``: value;`` with
# the value containing a real char (not a comment continuation /
# attribute selector).
_CSS_DECL_RE = re.compile(r":\s*[^;{}\n]{1,200};")


# Regex-literal extraction. Many languages embed regular expressions
# as literals -- some with dedicated syntax (JS / Perl / Ruby slash-
# delimited), others through API calls (Python / Java / Go / Rust /
# C#). Dashboards want a single list of the patterns the snippet
# defines so reviewers can spot obviously-wrong patterns
# (catastrophic backtracking, double-escaping bugs, unanchored
# email regexes) without scanning the whole snippet.
#
# Output shape: list of ``{"flavor", "pattern", "flags"}`` dicts.
# ``flavor`` is the syntax family (``js`` / ``python`` / ``ruby`` /
# ``perl`` / ``go`` / ``java`` / ``rust`` / ``c#``). ``pattern`` is
# the regex source as written (delimiters / quotes stripped).
# ``flags`` is the flag string when present (JS-flavor ``g`` /
# ``i`` / ``m`` / ``s`` / ``u`` / ``y`` / ``d``; other flavors
# stored without flags).
#
# Recognised shapes:
#
# * JS slash-delimited: ``/pattern/flags`` -- the slash form is the
#   tricky one because ``/`` is also the division operator. We
#   require a left-context that rules out division (line start, an
#   operator like ``=`` / ``(`` / ``,`` / ``;`` / ``return`` / a
#   logical operator) and reject zero-length patterns.
# * Python ``re.compile("pattern")`` / ``re.match`` / ``re.search``
#   / ``re.findall`` / ``re.sub`` with both raw-string ``r"..."``
#   / ``r'...'`` and plain ``"..."`` / ``'...'`` arguments.
# * Ruby ``%r{...}`` / ``%r!...!`` / ``%r/.../`` percent-literal
#   shapes; the delimiter character selects the closer.
# * Perl ``qr/.../`` / ``qr{...}`` literals.
# * Go ``regexp.MustCompile(\`pattern\`)`` / ``regexp.Compile(...)``
#   with backtick raw-string OR double-quoted body.
# * Java ``Pattern.compile("pattern")`` / ``Pattern.compile("pattern", flags)``.
# * Rust ``Regex::new("pattern")`` / ``Regex::new(r"pattern")``.
# * C# ``new Regex("pattern")`` / ``Regex.Match(input, "pattern")``
#   / ``Regex.IsMatch(input, "pattern")``.

_MAX_REGEXES = 50

# JS slash-delimited regex. The key challenge is distinguishing the
# regex literal from the division operator. Heuristic: the regex
# literal must be preceded by a context where division would be
# unexpected -- line start, an opener / separator / operator / a
# control keyword.
_JS_REGEX_RE = re.compile(
    r"(?:(?<=^)|(?<=[\[\(,;=:!&|?+\-*/%~])|(?<=\breturn\b)|"
    r"(?<=\btypeof\b)|(?<=\bin\b)|(?<=\bof\b)|(?<=\binstanceof\b))"
    r"\s*"
    r"/(?P<pattern>(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n])+)"
    r"/(?P<flags>[gimsuyd]*)"
    r"(?![A-Za-z0-9_])",
    re.MULTILINE,
)

# Python re.* call with first-arg string. Both raw-string and plain
# string accepted. Triple-quoted strings handled by a second pattern
# because the inner content rules differ.
_PY_REGEX_CALL_RE = re.compile(
    r"\bre\.(?:compile|match|search|fullmatch|findall|finditer|sub|subn|split)\s*\(\s*"
    r"(?P<rawmark>r)?(?P<q>['\"])(?P<pattern>(?:\\.|(?!(?P=q)).)+?)(?P=q)"
)

# Ruby %r{...} percent-literal. Each opener/closer pair gets its
# own pattern so the inner character class cannot accidentally
# terminate the match (e.g. ``%r{[a-z]+}`` -- the inner ``]`` is
# part of the character class, not the closer for the regex).
_RB_REGEX_CURLY_RE = re.compile(
    r"%r\{(?P<pattern>(?:\\.|[^}\\])+?)\}(?P<flags>[imxoesun]*)"
)
_RB_REGEX_PAREN_RE = re.compile(
    r"%r\((?P<pattern>(?:\\.|[^)\\])+?)\)(?P<flags>[imxoesun]*)"
)
_RB_REGEX_BRACKET_RE = re.compile(
    r"%r\[(?P<pattern>(?:\\.|[^\]\\])+?)\](?P<flags>[imxoesun]*)"
)
_RB_REGEX_ANGLE_RE = re.compile(
    r"%r<(?P<pattern>(?:\\.|[^>\\])+?)>(?P<flags>[imxoesun]*)"
)
_RB_REGEX_SAME_RE = re.compile(
    r"%r(?P<delim>[!|@#~/+\-])"
    r"(?P<pattern>(?:\\.|(?!(?P=delim)).)+?)"
    r"(?P=delim)"
    r"(?P<flags>[imxoesun]*)"
)

# Perl qr literal. Same per-delimiter-pair scheme as Ruby.
_PERL_REGEX_CURLY_RE = re.compile(
    r"\bqr\{(?P<pattern>(?:\\.|[^}\\])+?)\}(?P<flags>[imsxoadlu]*)"
)
_PERL_REGEX_PAREN_RE = re.compile(
    r"\bqr\((?P<pattern>(?:\\.|[^)\\])+?)\)(?P<flags>[imsxoadlu]*)"
)
_PERL_REGEX_BRACKET_RE = re.compile(
    r"\bqr\[(?P<pattern>(?:\\.|[^\]\\])+?)\](?P<flags>[imsxoadlu]*)"
)
_PERL_REGEX_ANGLE_RE = re.compile(
    r"\bqr<(?P<pattern>(?:\\.|[^>\\])+?)>(?P<flags>[imsxoadlu]*)"
)
_PERL_REGEX_SAME_RE = re.compile(
    r"\bqr(?P<delim>[!|/@#~+\-])"
    r"(?P<pattern>(?:\\.|(?!(?P=delim)).)+?)"
    r"(?P=delim)"
    r"(?P<flags>[imsxoadlu]*)"
)

# Go regexp.MustCompile / regexp.Compile. Both backtick-raw and
# double-quoted forms accepted.
_GO_REGEX_RAW_RE = re.compile(
    r"\bregexp\.(?:MustCompile|Compile)\s*\(\s*"
    r"`(?P<pattern>[^`]+)`"
)
_GO_REGEX_QUOTED_RE = re.compile(
    r"\bregexp\.(?:MustCompile|Compile)\s*\(\s*"
    r"\"(?P<pattern>(?:\\.|[^\"\\])+?)\""
)

# Java Pattern.compile. Single-string and string+flags both fit.
_JAVA_REGEX_RE = re.compile(
    r"\bPattern\.compile\s*\(\s*"
    r"\"(?P<pattern>(?:\\.|[^\"\\])+?)\""
)

# Rust Regex::new. Both raw-string and plain string.
_RUST_REGEX_RAW_RE = re.compile(
    r"\bRegex::new\s*\(\s*"
    r"r#*\"(?P<pattern>(?:[^\"\\]|\\.)+?)\"#*"
)
_RUST_REGEX_QUOTED_RE = re.compile(
    r"\bRegex::new\s*\(\s*"
    r"\"(?P<pattern>(?:\\.|[^\"\\])+?)\""
)

# C# new Regex(...) / Regex.Match(input, pattern) / Regex.IsMatch.
_CS_REGEX_NEW_RE = re.compile(
    r"\bnew\s+Regex\s*\(\s*"
    r"@?\"(?P<pattern>(?:\\.|[^\"\\])+?)\""
)
_CS_REGEX_STATIC_RE = re.compile(
    r"\bRegex\.(?:Match|IsMatch|Matches|Replace|Split)\s*\([^,)]*,\s*"
    r"@?\"(?P<pattern>(?:\\.|[^\"\\])+?)\""
)


def extract_regex_literals(
    code: str, language: str | None = None
) -> list[dict[str, str]]:
    """Return regex literals found in ``code``.

    Output is a list of ``{"flavor", "pattern", "flags"}`` dicts.
    ``flavor`` tags the syntax family. ``pattern`` is the regex
    source as written (delimiters / quotes stripped). ``flags`` is
    the flag string when present (empty string when absent).

    Recognised flavors: ``js``, ``python``, ``ruby``, ``perl``,
    ``go``, ``java``, ``rust``, ``c#``.

    De-dupes on ``(flavor, pattern, flags)`` tuple. Preserves first-
    seen-in-text order. Capped at :data:`_MAX_REGEXES` entries.

    Returns an empty list when no regex literal is present.

    The matcher runs every flavor's matcher against every snippet
    (not gated by language) because OCR captures often mix shells +
    configs + code and a hard language gate would lose hits. The
    flavor tag in the output preserves which syntax was matched.
    """
    if not code or not code.strip():
        return []
    candidates: list[tuple[int, str, str, str]] = []

    # Python re.* calls.
    for m in _PY_REGEX_CALL_RE.finditer(code):
        candidates.append((m.start(), "python", m.group("pattern"), ""))

    # Ruby percent-literal regexes.
    for pat in (
        _RB_REGEX_CURLY_RE,
        _RB_REGEX_PAREN_RE,
        _RB_REGEX_BRACKET_RE,
        _RB_REGEX_ANGLE_RE,
        _RB_REGEX_SAME_RE,
    ):
        for m in pat.finditer(code):
            candidates.append((
                m.start(), "ruby", m.group("pattern"), m.group("flags") or ""
            ))

    # Perl qr literals.
    for pat in (
        _PERL_REGEX_CURLY_RE,
        _PERL_REGEX_PAREN_RE,
        _PERL_REGEX_BRACKET_RE,
        _PERL_REGEX_ANGLE_RE,
        _PERL_REGEX_SAME_RE,
    ):
        for m in pat.finditer(code):
            candidates.append((
                m.start(), "perl", m.group("pattern"), m.group("flags") or ""
            ))

    # Go regexp.MustCompile.
    for m in _GO_REGEX_RAW_RE.finditer(code):
        candidates.append((m.start(), "go", m.group("pattern"), ""))
    for m in _GO_REGEX_QUOTED_RE.finditer(code):
        candidates.append((m.start(), "go", m.group("pattern"), ""))

    # Java Pattern.compile.
    for m in _JAVA_REGEX_RE.finditer(code):
        candidates.append((m.start(), "java", m.group("pattern"), ""))

    # Rust Regex::new.
    for m in _RUST_REGEX_RAW_RE.finditer(code):
        candidates.append((m.start(), "rust", m.group("pattern"), ""))
    for m in _RUST_REGEX_QUOTED_RE.finditer(code):
        candidates.append((m.start(), "rust", m.group("pattern"), ""))

    # C# new Regex / Regex.Static.
    for m in _CS_REGEX_NEW_RE.finditer(code):
        candidates.append((m.start(), "c#", m.group("pattern"), ""))
    for m in _CS_REGEX_STATIC_RE.finditer(code):
        candidates.append((m.start(), "c#", m.group("pattern"), ""))

    # JS slash-delimited LAST because it has the most false-positive
    # risk (division ambiguity) and we want the explicit API-call
    # forms above to land first.
    for m in _JS_REGEX_RE.finditer(code):
        pattern = m.group("pattern")
        if not pattern:
            continue
        candidates.append((
            m.start(), "js", pattern, m.group("flags") or ""
        ))

    candidates.sort(key=lambda x: x[0])
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for _off, flavor, pattern, flags in candidates:
        key = (flavor, pattern, flags)
        if key in seen:
            continue
        seen.add(key)
        entry: dict[str, str] = {"flavor": flavor, "pattern": pattern}
        if flags:
            entry["flags"] = flags
        else:
            entry["flags"] = ""
        out.append(entry)
        if len(out) >= _MAX_REGEXES:
            break
    return out



# Markdown code-fence language detection. Markdown wraps code in
# triple-backtick fences with an optional language tag immediately
# after the opening fence:
#
#   ```python
#   def foo(): ...
#   ```
#
#   ~~~rust
#   fn main() {}
#   ~~~
#
#   ```js title="example.js"
#   const x = 1;
#   ```
#
# We surface the tag as a high-confidence language signal because the
# author explicitly declared it -- more reliable than the heuristic
# ``detect_language`` pass for OCR captures of docs, blog posts,
# GitHub README sections, and chat captures of code snippets shared
# with a fenced block.
#
# Recognised opening fence shapes (CommonMark + GFM compatible):
#
# * ``` ```LANG `` -- canonical CommonMark form
# * ``` ```LANG title="..." `` -- GFM with title/info string after the tag
# * ``` ```LANG hl_lines=... `` -- mkdocs / pandoc info-string form
# * ``~~~LANG`` -- tilde-fence alternative (CommonMark)
# * 4+ backticks / tildes (CommonMark allows ANY 3+ run -- a 4-fence
#   wraps content that itself contains a 3-fence)
#
# Detection rules:
#
# 1. Scan every line for a fence opener. The fence MUST sit at the
#    start of the line (optionally indented up to 3 spaces per the
#    CommonMark spec; 4 spaces would make it an indented code block,
#    not a fence).
# 2. The language tag is the FIRST whitespace-bounded token after the
#    backtick / tilde run. We capture only ``[A-Za-z][\w+#.-]*`` so a
#    info-string title (e.g. ``title="example.py"``) doesn't bleed in.
# 3. The fence must be CLOSED somewhere later in the snippet with a
#    matching backtick / tilde fence of equal-or-greater length. A
#    snippet that opens a fence but never closes it is treated as
#    incomplete and the tag is still surfaced (since the author's
#    intent was clear).
# 4. When the snippet contains MULTIPLE fences with different tags,
#    we return the FIRST tag (the first author-declared language wins).
#
# Tag normalisation:
#
# * Lowercased before returning (``Python`` -> ``python``,
#   ``JavaScript`` -> ``javascript``).
# * We do NOT canonicalise short forms (``js`` stays ``js``,
#   ``py`` stays ``py``) because the original tag carries the
#   author's choice of vocabulary.
# * Whitespace-only / empty tags return None (a bare ``` ``` `` fence
#   has no language declaration).
_MARKDOWN_FENCE_RE = re.compile(
    r"^[ ]{0,3}(?P<fence>`{3,}|~{3,})[ \t]*"
    r"(?P<lang>[A-Za-z][\w+#.-]*)?",
    re.MULTILINE,
)


def detect_fence_language(code: str) -> str | None:
    """Return the language tag of the first markdown code fence in ``code``.

    Recognised fence shapes (CommonMark + GFM):

    * ``` ```LANG `` -- canonical
    * ``` ```LANG title="..." `` -- GFM info-string
    * ``~~~LANG`` -- tilde-fence alternative
    * 4+ backticks / tildes (CommonMark allows any 3+ run)

    The tag is lowercased before returning. ``None`` when no fence
    is present, when the fence has no language tag, or when the
    snippet contains only bare fences.

    When multiple fences with different tags appear, the FIRST tag
    wins (it reflects the author's primary language choice).
    """
    if not code or not code.strip():
        return None
    for m in _MARKDOWN_FENCE_RE.finditer(code):
        lang = m.group("lang")
        if not lang:
            # Bare fence (no language tag) -- keep scanning for a
            # later fence that DOES declare a language.
            continue
        return lang.lower()
    return None


# Line-number prefix patterns. Each candidate captures (1) the number
# itself and (2) the separator + trailing space(s), so we can strip
# the matched prefix from the line. Tried in order most-specific-first
# so an ambiguous line like ``1: foo`` lands on the ``: `` shape,
# not the bare ``1 foo`` shape (which would also match but with a
# different separator semantic).
_LINE_NUMBER_PATTERNS = (
    # Each entry is ``(regex, strip_one_separator_space)``. When the
    # second element is True, a leading space in the captured ``rest``
    # is consumed as the separator before storing -- this lets
    # ``2| return 1`` collapse to ``return 1`` while ``2|    return 1``
    # keeps its 4-space indentation.
    #
    # ``  1: foo()`` -- pasted from a doc / blog with leading whitespace.
    # Requires exactly one separator space / tab; further leading
    # spaces in rest are preserved as code indentation.
    (re.compile(r"^[ \t]*(?P<num>\d{1,5}):[ \t](?P<rest>.*)$"), False),
    # ``1| foo()`` -- code review / diff style. Sticky form
    # ``1|foo()`` is also accepted (no space after pipe); when a
    # space IS present it's consumed as the separator.
    (re.compile(r"^[ \t]*(?P<num>\d{1,5})\|(?P<rest>.*)$"), True),
    # ``  1\tfoo()`` -- cat -n / pr -n style (tab separator). The tab
    # is consumed; the rest is preserved verbatim (including any
    # leading spaces that are part of the code's indentation).
    (re.compile(r"^[ \t]*(?P<num>\d{1,5})\t(?P<rest>.*)$"), False),
    # ``  1  foo()`` -- right-aligned column with 2+ spaces. The
    # 2-space minimum is the separator boundary; any further leading
    # spaces in ``rest`` are kept as code indentation.
    (re.compile(r"^[ \t]*(?P<num>\d{1,5})[ \t]{2}(?P<rest>.*)$"), False),
)

# Minimum number of NON-BLANK lines required before we even attempt
# line-number detection. A 1- or 2-line snippet is too short to
# distinguish a numbered listing from "two ints on consecutive lines".
_MIN_NUMBERED_LINES = 3

# Minimum fraction of non-blank lines that must satisfy a numbered
# pattern before we declare the snippet numbered. 1.0 - tolerance =
# strict pass; we set the tolerance to 0.0 because real numbered
# listings number EVERY line, and even one un-numbered line in the
# middle is a strong signal that the snippet is NOT numbered.
_NUMBERED_THRESHOLD = 1.0


def detect_numbered(code: str) -> tuple[bool, str]:
    """Decide whether ``code`` was captured with a line-number prefix
    column, and if so return the de-numbered body.

    Returns a ``(is_numbered, body)`` tuple. ``body`` is the original
    code when ``is_numbered`` is False, or the de-numbered code (with
    the prefix column stripped from every non-blank line) when
    ``is_numbered`` is True. Blank lines in the input are preserved
    in the output regardless.

    Detection rules:

    1. There must be at least :data:`_MIN_NUMBERED_LINES` non-blank
       lines to attempt detection (too short and the signal is
       unreliable).
    2. Every non-blank line must match the SAME prefix pattern; the
       pattern can be any of: ``<n>:`` / ``<n>|`` / ``<n>\\t`` /
       ``<n>  `` (right-aligned column with 2+ spaces). Mixing
       patterns within a single snippet rejects detection.
    3. The numbers don't have to be strictly sequential -- a code
       review excerpt might paste lines 45..47 then 78..80 -- but
       they all have to be ascending non-decreasing.

    When the matched separator is a single space / tab (``: `` or
    ``| `` or the trailing space of the right-aligned column), that
    boundary character is consumed but any further spaces are
    preserved as code indentation. This means ``2|    return 1``
    keeps all four indent spaces, while ``2| return 1`` consumes
    the one separator space and yields ``return 1``.

    This is intentionally strict. A loose detector would mis-tag a
    code snippet whose first column happens to look numeric (e.g.,
    a CSV / table) as a numbered listing and silently drop the
    leading column. Strict matching keeps that false-positive risk
    bounded.
    """
    if not code or not code.strip():
        return False, code
    lines = code.splitlines()
    non_blank_indices = [i for i, ln in enumerate(lines) if ln.strip()]
    if len(non_blank_indices) < _MIN_NUMBERED_LINES:
        return False, code

    for pattern, strip_one_space in _LINE_NUMBER_PATTERNS:
        matches: list[re.Match[str]] = []
        ok = True
        last_num = -1
        for i in non_blank_indices:
            m = pattern.match(lines[i])
            if m is None:
                ok = False
                break
            num = int(m.group("num"))
            if num < last_num:
                # Numbers must be non-decreasing across the snippet.
                ok = False
                break
            last_num = num
            matches.append(m)
        if not ok:
            continue
        # If we reached here every non-blank line matched the same
        # pattern with non-decreasing numbers. Build the de-numbered
        # body. We preserve blank lines verbatim.
        #
        # Separator-space handling: when the pattern supports the
        # sticky form (e.g. ``2|code`` alongside ``2| code``), we use
        # the FIRST matched line as the reference. If that line's
        # rest starts with a space, we treat the snippet as "spaced
        # form" and strip exactly one leading space from every line's
        # rest (preserving deeper indentation). If the first line's
        # rest does NOT start with a space, we treat the snippet as
        # "sticky form" and don't strip anything -- in which case
        # rest is already correct.
        spaced_form = (
            strip_one_space
            and bool(matches)
            and matches[0].group("rest").startswith(" ")
        )
        out_lines: list[str] = []
        m_iter = iter(matches)
        for ln in lines:
            if not ln.strip():
                out_lines.append(ln)
                continue
            m = next(m_iter)
            rest = m.group("rest")
            if spaced_form and rest.startswith(" "):
                rest = rest[1:]
            out_lines.append(rest)
        return True, "\n".join(out_lines)

    return False, code


# Build-tool / package-manager / task-runner command detection.
# Code snippets and terminal captures often include recipe lines
# (``$ npm install`` / ``cargo build --release`` / ``docker build .``)
# alongside the actual source. We recognise the most common 25
# package-manager / build-tool / runtime / cloud-CLI commands and
# surface each as a ``{tool, command}`` dict so dashboards can
# annotate "uses npm + cargo + docker" toolchains at a glance.
#
# Detection rules:
#   * The line MUST start the command at its first non-prompt token.
#     A leading shell prompt (``$ `` / ``# `` / ``> `` / ``PS> ``
#     / ``[user@host]$ ``) is stripped first.
#   * The tool name MUST match one of the catalogue keys.
#   * The line MUST have at least one space-separated subcommand
#     or flag after the tool name (``npm`` alone is the executable
#     name, not a command). EXCEPTION: ``make`` accepts a bare
#     invocation since ``make`` with no target is meaningful
#     (it runs the first target in the Makefile).

# Canonical tool catalogue. Keys are the lowercase executable names
# we recognise; values are tuples of subcommands the tool typically
# takes (used to harden matches -- a line with a recognised tool
# but no recognised subcommand is allowed through but flagged as
# generic). For tools where any subcommand is plausible (docker,
# kubectl, terraform, helm, etc.) we use the wildcard tuple ``()``
# which accepts anything after the tool name.
_BUILD_TOOLS: dict[str, tuple[str, ...]] = {
    # Node ecosystem -- npm / yarn / pnpm / npx / bun
    "npm": ("install", "run", "test", "build", "start", "init", "publish",
            "audit", "update", "ci", "rebuild", "exec", "outdated",
            "uninstall", "link", "view", "version", "dedupe", "fund",
            "pack"),
    "yarn": ("install", "add", "remove", "run", "test", "build", "start",
             "init", "publish", "upgrade", "remove", "outdated",
             "create", "exec", "global", "workspace", "workspaces"),
    "pnpm": ("install", "add", "remove", "run", "test", "build", "start",
             "init", "publish", "update", "outdated", "exec", "create",
             "dlx", "store"),
    "bun": ("install", "add", "remove", "run", "test", "build", "create",
            "init", "x", "link"),
    "npx": (),
    # Python ecosystem
    "pip": ("install", "uninstall", "freeze", "list", "show", "search",
            "download", "wheel", "check", "config", "cache", "debug"),
    "pip3": ("install", "uninstall", "freeze", "list"),
    "pipx": ("install", "run", "uninstall", "upgrade", "list", "inject",
             "runpip", "ensurepath", "completions"),
    "poetry": ("add", "install", "update", "remove", "publish", "build",
               "run", "init", "lock", "show", "env", "config", "shell",
               "version", "new", "export"),
    "uv": ("sync", "add", "remove", "run", "pip", "tool", "init",
           "lock", "build", "publish", "venv", "cache", "self",
           "python"),
    "conda": ("install", "create", "activate", "env", "update", "remove",
              "search", "list", "info"),
    "pipenv": ("install", "uninstall", "update", "lock", "shell", "run",
               "graph", "check"),
    # Ruby
    "bundle": ("install", "update", "exec", "add", "remove", "outdated",
               "lock", "init", "show", "info", "platform"),
    "gem": ("install", "uninstall", "update", "list", "search", "build",
            "push", "fetch", "outdated", "cleanup", "which"),
    # Rust
    "cargo": ("build", "run", "test", "check", "install", "publish",
              "new", "init", "update", "fmt", "clippy", "doc", "tree",
              "add", "remove", "search", "bench", "fix", "audit",
              "expand"),
    "rustup": ("install", "update", "default", "show", "self", "component",
               "target", "toolchain", "completions"),
    # Go
    "go": ("build", "run", "test", "get", "install", "mod", "fmt",
           "vet", "tool", "doc", "version", "env", "generate", "list",
           "clean", "work"),
    # PHP
    "composer": ("install", "require", "update", "remove", "init",
                 "dump-autoload", "create-project", "search", "show",
                 "outdated", "self-update", "global"),
    # Java / JVM
    "mvn": ("install", "clean", "test", "package", "compile", "verify",
            "deploy", "site", "dependency", "archetype", "wrapper"),
    "gradle": ("build", "test", "run", "clean", "tasks", "init", "wrapper",
               "publish", "assemble", "check", "dependencies"),
    "sbt": ("compile", "test", "run", "clean", "assembly", "publish",
            "console", "stage"),
    # .NET
    "dotnet": ("build", "run", "test", "publish", "new", "restore", "add",
               "remove", "list", "pack", "tool", "nuget", "watch",
               "format", "clean"),
    "nuget": ("install", "update", "restore", "push", "pack", "list"),
    # Make / build runners
    "make": (),
    "just": (),
    "task": (),
    # Containers / orchestration
    "docker": ("build", "run", "push", "pull", "compose", "exec", "ps",
               "images", "rmi", "rm", "tag", "save", "load", "inspect",
               "stop", "start", "restart", "logs", "kill", "cp",
               "network", "volume", "system"),
    "podman": ("build", "run", "push", "pull", "exec", "ps", "images",
               "rmi", "rm", "tag", "inspect", "stop", "start"),
    "kubectl": ("apply", "get", "delete", "create", "describe", "logs",
                "exec", "edit", "patch", "rollout", "scale", "expose",
                "run", "port-forward", "cp", "explain", "config",
                "annotate", "label"),
    "helm": ("install", "upgrade", "uninstall", "list", "repo", "search",
             "show", "template", "lint", "package", "history", "rollback",
             "status", "version"),
    "terraform": ("init", "plan", "apply", "destroy", "validate", "fmt",
                  "show", "import", "output", "workspace", "state",
                  "providers", "version", "console", "graph", "refresh"),
    # OS package managers
    "brew": ("install", "uninstall", "update", "upgrade", "list", "search",
             "info", "outdated", "cleanup", "doctor", "tap", "cask",
             "services", "bundle"),
    "apt": ("install", "update", "upgrade", "remove", "purge", "search",
            "show", "list", "autoremove", "full-upgrade", "policy",
            "edit-sources"),
    "apt-get": ("install", "update", "upgrade", "remove", "purge",
                "autoremove", "clean"),
    "yum": ("install", "update", "remove", "search", "info", "list",
            "clean", "check-update", "history"),
    "dnf": ("install", "update", "remove", "search", "info", "list",
            "clean", "upgrade", "history"),
    "pacman": ("-S", "-R", "-U", "-Q", "-Sy", "-Syu", "-Syyu", "-Ss",
               "-Si", "-Qi"),
    "apk": ("add", "del", "update", "upgrade", "info", "search", "fix"),
    # CI / version control / others worth catching
    "act": ("-l", "-j", "push", "pull_request"),
    "gh": ("repo", "pr", "issue", "auth", "release", "workflow", "run",
           "api", "browse", "label", "secret"),
}

# Maximum number of build_commands entries surfaced per snippet.
_MAX_BUILD_COMMANDS = 50

# Shell prompts recognised on the leading position of a line. The
# regex strips them so the cleaned command line can be tokenised.
# Supports bash / zsh / fish ``$``, root ``#``, PowerShell ``PS>``
# and ``>``, conda env ``(env) $``, bracket-then-prompt
# ``[user@host project]$``, and continuation ``$ \\``.
_PROMPT_RE = re.compile(
    r"^\s*"
    r"(?:"
    # ``(env) `` virtualenv / conda env prefix
    r"\([\w./@\-]+\)\s+"
    # ``[user@host project]$ `` brackets
    r"|\[[^\]]+\]\s*"
    # ``user@host:path# `` shell-style prompt (consumed up to the ``$``/``#``/``>``)
    r"|[\w.@\-]+@[\w.@\-]+:[^$#>]*"
    r")?"
    r"(?:"
    # PowerShell ``PS C:\path>`` or ``PS>``. Accepts the bare ``PS``
    # form OR ``PS`` + space + drive-letter + ``:`` + path + ``>``.
    r"PS(?:\s+[A-Z]:[^\s>]*)?\s*>\s+"
    r"|\$\s+"                     # bash / zsh ``$ ``
    r"|#\s+"                      # root ``# `` (must be followed by space)
    r"|>\s+"                      # generic ``> ``
    r")"
)


def extract_build_commands(code: str) -> list[dict[str, str]]:
    """Return build / package-manager command entries found in ``code``.

    Each entry is a ``{"tool": str, "command": str}`` dict. ``tool``
    is the lowercase canonical executable name. ``command`` is the
    full command line as printed, with any leading shell prompt
    stripped so the cleaned form is directly executable.

    Detection rules:
      * Per-line scan over the snippet body.
      * Leading shell prompt (``$ ``, ``# ``, ``> ``, ``PS> ``,
        ``(env) $ ``, ``[user@host]$ ``) stripped.
      * The first token MUST match a tool key in the catalogue.
      * The tool name MUST be followed by at least one space-
        separated subcommand or flag (exception: ``make`` /
        ``just`` / ``task`` / ``npx`` accept bare invocations).
      * The match must be at the START of the cleaned line so a
        prose mention of ``npm install`` mid-sentence doesn't
        false-positive.

    De-duped on the (tool, command) tuple; first-seen order
    preserved. Capped at 50 entries.
    """
    if not code:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    bare_ok = {"make", "just", "task", "npx"}
    for raw_line in code.splitlines():
        # Strip a leading shell prompt if present.
        m = _PROMPT_RE.match(raw_line)
        if m:
            line = raw_line[m.end():].lstrip()
        else:
            line = raw_line.lstrip()
        if not line:
            continue
        # First token = tool name. Tokenise on whitespace.
        toks = line.split()
        if not toks:
            continue
        tool = toks[0].lower()
        # ``./mvnw`` / ``./gradlew`` wrapper forms re-map to the
        # underlying tool so dashboards group wrapper + bare calls.
        if tool in ("./mvnw", "mvnw"):
            tool = "mvn"
        elif tool in ("./gradlew", "gradlew", "gradlew.bat"):
            tool = "gradle"
        if tool not in _BUILD_TOOLS:
            continue
        # Tools that need at least one subcommand or flag.
        if tool not in bare_ok and len(toks) < 2:
            continue
        # Clean the captured command: drop trailing prompt continuations
        # and normalise internal runs of whitespace.
        cleaned = re.sub(r"\s+", " ", line).strip()
        key = (tool, cleaned)
        if key in seen:
            continue
        seen.add(key)
        out.append({"tool": tool, "command": cleaned})
        if len(out) >= _MAX_BUILD_COMMANDS:
            break
    return out


# ---------------------------------------------------------------------
# Dependency version-pin extraction. Many code captures show
# package.json / requirements.txt / Cargo.toml / Gemfile / composer.json
# / go.mod / pyproject.toml content. We detect the recognised
# pin shapes for each ecosystem and emit ``{ecosystem, package,
# version}`` dicts.
#
# Ecosystem detection uses per-line pattern matching -- we do NOT
# rely on the surrounding language tag because OCR captures often
# mix multiple manifest snippets. The same line that matches an
# ecosystem-specific shape determines the tag for THAT line; lines
# can come from different ecosystems within the same snippet.
# ---------------------------------------------------------------------

# A version specifier accepts the common operators across ecosystems:
# exact (1.0), caret (^1.0), tilde (~1.0, ~> 1.0), >= / <= / != / < / >,
# wildcard (*, x), pre-release tail (-alpha, -beta.1, -rc1),
# build metadata (+build), single-quoted / double-quoted forms.
# The ``[ <>=!^~*]?`` family of leading operator chars is captured
# but we keep them in the version output verbatim.
_VERSION_BODY = r"[\w.+\-*x]"
_VERSION_SPEC = (
    r"(?:[<>=!^~]{1,2}\s*)?" + _VERSION_BODY + r"+"
    + r"(?:\s*,\s*[<>=!^~]{1,2}\s*" + _VERSION_BODY + r"+)*"
)

# npm / package.json:  "react": "^18.2.0"  /  "@types/react": "^18.2"
# The leading-name shape allows the @scoped/name form.
_NPM_DEP_RE = re.compile(
    r'^\s*"(?P<name>(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+)"\s*:\s*"(?P<ver>[^"]+)"',
    re.MULTILINE,
)

# pip / requirements.txt: requests==2.31.0   flask>=2.0,<3.0
# Allows extras: requests[socks]==2.31.0
# Quietly rejects comments (#), URL-based deps (-e .), git/file URLs.
_PIP_DEP_RE = re.compile(
    r"^\s*"
    r"(?P<name>[A-Za-z][A-Za-z0-9._-]{0,127})"
    r"(?:\[[A-Za-z0-9_,\s]+\])?"  # optional extras [socks, brotli]
    r"\s*"
    r"(?P<spec>(?:==|>=|<=|!=|~=|>|<)\s*"
    + _VERSION_BODY + r"+"
    + r"(?:\s*,\s*(?:==|>=|<=|!=|~=|>|<)\s*" + _VERSION_BODY + r"+)*"
    + r")\s*(?:#.*)?$",
    re.MULTILINE,
)

# Cargo.toml: serde = "1.0"   /   serde = { version = "1.0", features = ["foo"] }
# We capture the simple form first; the table-form needs a separate
# pattern.
_CARGO_DEP_SIMPLE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z][A-Za-z0-9._-]{0,127})"
    r'\s*=\s*"(?P<ver>[^"]+)"',
    re.MULTILINE,
)
_CARGO_DEP_TABLE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z][A-Za-z0-9._-]{0,127})"
    r"\s*=\s*\{[^}]*?\bversion\s*=\s*"
    r'"(?P<ver>[^"]+)"',
    re.MULTILINE | re.DOTALL,
)

# Gemfile:  gem 'rails', '~> 7.0'   /   gem "puma", "~> 6.4"
_GEM_DEP_RE = re.compile(
    r"^\s*gem\s+['\"](?P<name>[A-Za-z][A-Za-z0-9._-]{0,127})['\"]"
    r"\s*,\s*['\"](?P<ver>[^'\"]+)['\"]",
    re.MULTILINE,
)

# composer.json: "monolog/monolog": "^2.5"
# Always uses the vendor/package shape.
_COMPOSER_DEP_RE = re.compile(
    r'^\s*"(?P<name>[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)"'
    r'\s*:\s*"(?P<ver>[^"]+)"',
    re.MULTILINE,
)

# go.mod: require github.com/x/y v1.2.3   /   github.com/x/y v1.2.3
# Inside a require ( ... ) block, the require keyword is absent on
# each line so we match both shapes.
_GO_MOD_DEP_RE = re.compile(
    r"^\s*(?:require\s+)?"
    r"(?P<name>[a-z0-9.][a-z0-9./_-]{2,127})\s+"
    r"v(?P<ver>\d+\.\d+\.\d+(?:[\-+][\w.]+)*"
    r"(?:\+incompatible)?)",
    re.MULTILINE,
)

# Maven (pom.xml): <dependency>
#                    <groupId>foo</groupId>
#                    <artifactId>bar</artifactId>
#                    <version>1.0</version>
#                  </dependency>
# We capture the inline-XML form that's common in OCR captures.
_MAVEN_DEP_RE = re.compile(
    r"<groupId>(?P<group>[^<\s]+)</groupId>\s*"
    r"<artifactId>(?P<artifact>[^<\s]+)</artifactId>\s*"
    r"<version>(?P<ver>[^<\s]+)</version>",
    re.IGNORECASE,
)

# Gradle: implementation 'com.example:lib:1.0'   /   compile "com.example:lib:1.0"
# Also: implementation group: 'com.example', name: 'lib', version: '1.0'
_GRADLE_DEP_RE = re.compile(
    r"\b(?:implementation|compile|api|testImplementation|runtimeOnly|"
    r"compileOnly|annotationProcessor|kapt|ksp)\s+"
    r"['\"](?P<name>[a-zA-Z0-9.][a-zA-Z0-9._-]*:[a-zA-Z0-9.][a-zA-Z0-9._-]*)"
    r":(?P<ver>[^'\"]+)['\"]"
)

# Maximum number of dep_pins entries surfaced per snippet.
_MAX_DEP_PINS = 100

# Pip / npm names that look like names but are placeholders to skip
# (the ``Section name`` / ``Package`` headers on doc tables).
_DEP_NAME_BLOCKLIST = frozenset({
    "package", "name", "version", "library", "dependency",
    "deps", "section",
})


def extract_dep_pins(code: str) -> list[dict[str, str]]:
    """Return dependency version-pins found in ``code``.

    Each entry is a ``{"package": str, "version": str,
    "ecosystem": str}`` dict where ``ecosystem`` is one of
    ``npm`` / ``pip`` / ``cargo`` / ``gem`` / ``composer`` /
    ``go`` / ``maven`` / ``gradle``.

    Recognised shapes (per ecosystem):

    * **npm** -- ``"react": "^18.2.0"``,
      ``"@types/react": "^18.2"`` (package.json format)
    * **pip** -- ``requests==2.31.0`` / ``flask>=2.0,<3.0`` /
      ``requests[socks]==2.31.0`` (requirements.txt format)
    * **cargo** -- ``serde = "1.0"`` / ``tokio = { version = "1.0",
      features = ["full"] }`` (Cargo.toml format)
    * **gem** -- ``gem 'rails', '~> 7.0'`` (Gemfile format)
    * **composer** -- ``"monolog/monolog": "^2.5"`` (composer.json
      format with mandatory vendor/package shape)
    * **go** -- ``require github.com/x/y v1.2.3`` /
      ``github.com/x/y v1.2.3`` (go.mod format)
    * **maven** -- ``<groupId>foo</groupId>
      <artifactId>bar</artifactId><version>1.0</version>``
      (pom.xml format; emits ``foo:bar`` as the package name)
    * **gradle** -- ``implementation 'com.example:lib:1.0'``
      (build.gradle format)

    Ecosystem detection uses per-shape pattern matching -- we do NOT
    rely on the surrounding language tag. A snippet can mix multiple
    manifest formats (a tutorial blog post quoting BOTH a
    requirements.txt and a package.json fragment) and we tag each
    line according to its own format.

    Priority ordering: composer (mandatory vendor/package shape)
    runs BEFORE generic npm (which would also match composer's
    ``"foo/bar": "1.0"`` shape but tag it as npm). gradle runs
    BEFORE maven on a per-line basis (gradle has a more-specific
    prelude). Within the npm / cargo / pip / gem / go / maven
    branches, ordering doesn't matter because their shapes don't
    overlap.

    Duplicate suppression: de-duped on the
    ``(ecosystem, package, version)`` triple. First-seen order
    preserved. Capped at 100 entries.

    Empty list when no recognised pin is present (a plain function /
    class body, raw prose, etc).
    """
    if not code:
        return []

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(ecosystem: str, package: str, version: str) -> None:
        package = package.strip()
        version = version.strip()
        if not package or not version:
            return
        if package.lower() in _DEP_NAME_BLOCKLIST:
            return
        key = (ecosystem, package, version)
        if key in seen:
            return
        seen.add(key)
        out.append({
            "ecosystem": ecosystem,
            "package": package,
            "version": version,
        })

    # Track captured spans per line so we don't double-count -- but
    # only WITHIN the same line. Different ecosystems on different
    # lines are independent.
    #
    # Composer FIRST because its mandatory vendor/package format
    # is more specific than the generic npm key:value shape.
    for m in _COMPOSER_DEP_RE.finditer(code):
        name = m.group("name")
        if "/" not in name:  # composer requires vendor/package
            continue
        _add("composer", name, m.group("ver"))
        if len(out) >= _MAX_DEP_PINS:
            return out

    for m in _NPM_DEP_RE.finditer(code):
        name = m.group("name")
        if "/" in name and not name.startswith("@"):
            # Composer-style "vendor/package" was already handled
            # above. We only accept npm scoped form (@scope/pkg).
            continue
        if len(out) >= _MAX_DEP_PINS:
            return out
        _add("npm", name, m.group("ver"))

    for m in _PIP_DEP_RE.finditer(code):
        if len(out) >= _MAX_DEP_PINS:
            return out
        spec = m.group("spec").replace(" ", "")
        _add("pip", m.group("name"), spec)

    # Cargo: table-form FIRST because its body contains a quoted
    # version that the simple form would also match (with the wrong
    # name -- e.g. `tokio = { version = "1.0" }` would otherwise
    # also match the simple shape with name=tokio version=1.0
    # which is correct, but the table-form captures it cleaner).
    cargo_table_spans: list[tuple[int, int]] = []
    for m in _CARGO_DEP_TABLE_RE.finditer(code):
        if len(out) >= _MAX_DEP_PINS:
            return out
        _add("cargo", m.group("name"), m.group("ver"))
        cargo_table_spans.append((m.start(), m.end()))

    # Simple cargo form: skip matches whose span overlaps a table-form match.
    for m in _CARGO_DEP_SIMPLE_RE.finditer(code):
        if len(out) >= _MAX_DEP_PINS:
            return out
        # Skip if this match's span sits inside a table-form span.
        overlap = False
        for ts, te in cargo_table_spans:
            if ts <= m.start() < te:
                overlap = True
                break
        if overlap:
            continue
        _add("cargo", m.group("name"), m.group("ver"))

    for m in _GEM_DEP_RE.finditer(code):
        if len(out) >= _MAX_DEP_PINS:
            return out
        _add("gem", m.group("name"), m.group("ver"))

    for m in _GO_MOD_DEP_RE.finditer(code):
        if len(out) >= _MAX_DEP_PINS:
            return out
        name = m.group("name")
        # Defensive: go module paths always contain a dot (the TLD
        # in the registry host). Reject single-word names that
        # would otherwise misfire on random text like ``module v1``.
        if "." not in name:
            continue
        _add("go", name, "v" + m.group("ver"))

    for m in _GRADLE_DEP_RE.finditer(code):
        if len(out) >= _MAX_DEP_PINS:
            return out
        _add("gradle", m.group("name"), m.group("ver"))

    for m in _MAVEN_DEP_RE.finditer(code):
        if len(out) >= _MAX_DEP_PINS:
            return out
        name = f"{m.group('group')}:{m.group('artifact')}"
        _add("maven", name, m.group("ver"))

    return out


def enrich_code(existing: CodeFields | None, ocr: OCRResult) -> CodeFields:
    code = (existing.code if existing and existing.code else ocr.text or "").strip()
    # Markdown fence-language detection. Runs FIRST on the original
    # pre-strip body so fence markers (``` / ~~~) survive any
    # downstream line-number stripping. Caller-supplied value wins;
    # otherwise scan the snippet for a markdown code-fence opener
    # and surface the lowercased language tag.
    fence_language = (
        existing.fence_language if existing and existing.fence_language else None
    )
    if fence_language is None:
        fence_language = detect_fence_language(code)
    # Line-number prefix detection. Runs FIRST because every downstream
    # detector (language, dialect, ts_features, minified, interpreter,
    # comment density) wants to see the de-numbered code. Caller-
    # supplied ``numbered = True`` is preserved (we trust the caller's
    # signal) but we still re-run the strip so the code body is
    # canonical. When the caller hasn't set it, we run the detector and
    # use its result.
    caller_numbered = bool(existing.numbered) if existing else False
    is_numbered, stripped = detect_numbered(code)
    if caller_numbered or is_numbered:
        code = stripped
        numbered = True
    else:
        numbered = False
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
    # Minified-bundle detection. Caller-supplied value (if any) wins;
    # heuristic fills the default False when the caller didn't set it.
    minified = bool(existing.minified) if existing and existing.minified else False
    if not minified:
        minified = detect_minified_js(code, language)
    # Shebang interpreter. Caller-supplied value wins; otherwise pull
    # from the leading shebang line if present.
    interpreter = (
        existing.interpreter if existing and existing.interpreter else None
    )
    if interpreter is None:
        interpreter = detect_interpreter(code)
    # Comment density. Caller-supplied value wins (a non-zero value);
    # otherwise compute from the code body against the detected
    # language's comment leaders. Note the default 0.0 means "no
    # caller value"; we recompute whenever the existing field is at
    # the default so a caller that explicitly passed 0.0 will see
    # the recomputed value (which is also 0.0 for non-commented
    # snippets, so the behaviour is consistent).
    comment_density = (
        existing.comment_density
        if existing and existing.comment_density
        else 0.0
    )
    if comment_density == 0.0:
        comment_density = detect_comment_density(code, language)
    # TODO / FIXME marker count. Caller-supplied positive value wins;
    # otherwise we recount on the de-numbered code body against the
    # detected language's comment leaders. We recount whenever the
    # existing field is the default 0 because a caller that explicitly
    # passed 0 will see the same recomputed 0 for a TODO-free snippet
    # (behaviour is consistent either way).
    todo_count = (
        existing.todo_count
        if existing and existing.todo_count
        else 0
    )
    if todo_count == 0:
        todo_count = detect_todo_count(code, language)
    # Author-tagged TODO extraction. Caller-supplied list wins
    # (preserved verbatim); otherwise scan the snippet for the
    # canonical ``MARKER(author):`` form. Returns an empty list
    # when no author-tagged markers are present so a TODO-free
    # snippet stays at the default [].
    todo_authors = (
        list(existing.todo_authors)
        if existing and existing.todo_authors
        else []
    )
    if not todo_authors:
        todo_authors = extract_todo_authors(code, language)
    # Ticket-tagged TODO extraction. Caller-supplied list wins
    # (preserved verbatim); otherwise scan the snippet for ticket
    # references (JIRA-style PROJECT-NUMBER, GitHub #1234,
    # hash-slug #issue-42) attached to TODO / FIXME / etc markers.
    # Returns an empty list when no ticket references are present.
    todo_tickets = (
        list(existing.todo_tickets)
        if existing and existing.todo_tickets
        else []
    )
    if not todo_tickets:
        todo_tickets = extract_todo_tickets(code, language)
    # License-header detection. Caller-supplied value wins; otherwise
    # scan the snippet's header for a recognised open-source license.
    # The detector returns None when no header matches so a TODO-free
    # snippet with no license stays at the default None.
    license_tag = (
        existing.license if existing and existing.license else None
    )
    if license_tag is None:
        license_tag = detect_license(code)
    # Top-level docstring / JSDoc body. Caller-supplied value wins;
    # otherwise scan the snippet for the first structured doc block
    # (Python triple-quoted, JSDoc ``/** ... */``, or Rust ``///`` /
    # ``//!`` line-doc-comment run). Returns None when no doc block is
    # present so a code-only snippet stays at the default None.
    docstring = (
        existing.docstring if existing and existing.docstring else None
    )
    if docstring is None:
        docstring = detect_docstring(code, language)
    # Import / require / use statements. Caller-supplied list wins
    # (preserved verbatim); otherwise scan the snippet for the major
    # import syntaxes (Python / JS / TS / Java / Kotlin / Scala / Go /
    # Rust / Ruby / PHP) and surface the canonical short module names.
    imports = list(existing.imports) if existing and existing.imports else []
    if not imports:
        imports = extract_imports(code, language)
    # Copyright holders extracted from the snippet's header. Caller-
    # supplied list wins (preserved verbatim); otherwise scan the
    # first 30 header lines for ``Copyright ...`` / ``(c) ...`` /
    # ``©`` markers and surface each ``{holder, year}`` pair found.
    copyrights = list(existing.copyright) if existing and existing.copyright else []
    if not copyrights:
        copyrights = extract_copyrights(code)
    # Feature-flag SDK call sites. Caller-supplied list wins
    # (preserved verbatim); otherwise scan the snippet for
    # LaunchDarkly / Statsig / Unleash / Optimizely / Split.io /
    # PostHog / Flagsmith / ConfigCat client-call shapes and surface
    # each ``{vendor, key}`` pair. Returns an empty list when no
    # SDK call sites are present.
    feature_flags = (
        list(existing.feature_flags)
        if existing and existing.feature_flags
        else []
    )
    if not feature_flags:
        feature_flags = extract_feature_flags(code)
    # CSS vendor-prefix tags. Caller-supplied list wins (preserved
    # verbatim); otherwise scan the snippet for ``-webkit-`` /
    # ``-moz-`` / ``-ms-`` / ``-o-`` / ``-khtml-`` prefixes. The
    # detector is language-gated to CSS-family snippets so a JS
    # comment that mentions ``-webkit-`` doesn't false-positive.
    css_vendor_prefixes = (
        list(existing.css_vendor_prefixes)
        if existing and existing.css_vendor_prefixes
        else []
    )
    if not css_vendor_prefixes:
        css_vendor_prefixes = detect_css_vendor_prefixes(code, language)
    # Regex literal extraction. Caller-supplied list wins (preserved
    # verbatim); otherwise scan the snippet for embedded regex
    # literals across 8 language flavors (js / python / ruby / perl /
    # go / java / rust / c#) and surface each ``{flavor, pattern,
    # flags}`` triple found. Returns an empty list when no regex
    # literal is present.
    regexes = (
        list(existing.regexes)
        if existing and existing.regexes
        else []
    )
    if not regexes:
        regexes = extract_regex_literals(code, language)
    # Build-tool / package-manager command detection. Caller-supplied
    # list wins (preserved verbatim); otherwise scan the snippet for
    # recognised npm / yarn / pnpm / pip / poetry / uv / cargo / go /
    # make / bundle / gem / composer / mvn / gradle / dotnet / docker
    # / kubectl / terraform / helm / brew / apt / yum / dnf / pacman /
    # apk command lines and surface each ``{tool, command}`` pair.
    # Returns an empty list when no recognised command is present.
    build_commands = (
        list(existing.build_commands)
        if existing and existing.build_commands
        else []
    )
    if not build_commands:
        build_commands = extract_build_commands(code)
    # Dependency version-pin extraction. Caller-supplied list wins
    # (preserved verbatim); otherwise scan the snippet for recognised
    # npm / pip / cargo / gem / composer / go / maven / gradle pin
    # shapes and surface each {ecosystem, package, version} dict.
    # Ecosystem detection uses per-shape pattern matching so a
    # snippet that mixes multiple manifest formats (a blog post
    # quoting both a requirements.txt and package.json fragment)
    # tags each line independently. Returns an empty list when no
    # recognised pin is present.
    dep_pins = (
        list(existing.dep_pins)
        if existing and existing.dep_pins
        else []
    )
    if not dep_pins:
        dep_pins = extract_dep_pins(code)
    return CodeFields(
        language=language,
        code=code,
        line_count=len(code.splitlines()),
        dialect=dialect,
        ts_features=ts_features,
        minified=minified,
        interpreter=interpreter,
        comment_density=comment_density,
        numbered=numbered,
        todo_count=todo_count,
        todo_authors=todo_authors,
        todo_tickets=todo_tickets,
        license=license_tag,
        docstring=docstring,
        imports=imports,
        copyright=copyrights,
        fence_language=fence_language,
        feature_flags=feature_flags,
        css_vendor_prefixes=css_vendor_prefixes,
        regexes=regexes,
        build_commands=build_commands,
        dep_pins=dep_pins,
    )
