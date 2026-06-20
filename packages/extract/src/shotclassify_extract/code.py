"""Code snippet extractor: Pygments lexer guess, line count, code body."""
from __future__ import annotations

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


def enrich_code(existing: CodeFields | None, ocr: OCRResult) -> CodeFields:
    code = (existing.code if existing and existing.code else ocr.text or "").strip()
    return CodeFields(
        language=(existing.language if existing and existing.language else None)
        or detect_language(code),
        code=code,
        line_count=len(code.splitlines()),
    )
