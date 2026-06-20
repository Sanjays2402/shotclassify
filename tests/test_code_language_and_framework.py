"""Expanded code language hints + framework guesses.

Adds language detection for Kotlin, Swift, C#, Elixir, Scala, PHP,
Haskell on top of the existing Python/JS/TS/Go/Rust/Java/Ruby/Shell/
SQL set, and a new ``detect_framework`` helper that identifies popular
libraries from imports + top-level identifiers (React, Vue, Angular,
Next, Django, Flask, FastAPI, Rails, Spring, Express, Gin, Actix,
Tokio).

The bare-language ``detect_language`` ordering MUST not break any
existing test. We swap the storage from a dict to an ordered tuple of
(tag, needles) so more-specific languages can win over generic ones.
"""
from __future__ import annotations

import pytest
from shotclassify_extract.code import detect_framework, detect_language


@pytest.mark.parametrize(
    "code,expected",
    [
        # Kotlin (fun main, println)
        ("fun main() {\n    println(\"hi\")\n}\n", "kotlin"),
        # Kotlin with companion object
        (
            "class Service {\n  companion object {\n    fun create() = Service()\n  }\n}\n",
            "kotlin",
        ),
        # Swift (import Foundation is unambiguous)
        ("import Foundation\nlet greeting = \"Hello\"\nprint(greeting)\n", "swift"),
        # Swift @objc
        ("@objc class Bridge: NSObject { }\n", "swift"),
        # C# Console.WriteLine
        (
            "namespace Acme {\n  using System;\n  "
            "class P { static void Main() { Console.WriteLine(\"hi\"); } }\n}\n",
            "c#",
        ),
        # Elixir
        (
            "defmodule Greeter do\n  def hello(name), do: IO.puts(\"Hello, \" <> name)\nend\n",
            "elixir",
        ),
        # Scala (extends App is a reliable Scala-only signal)
        (
            "object Hello extends App {\n  println(\"hi\")\n}\n",
            "scala",
        ),
        # PHP
        ("<?php\necho \"hi\";\n", "php"),
        # Haskell
        ("import qualified Data.Map as M\nmain = putStrLn \"hi\"\n", "haskell"),
    ],
)
def test_new_languages_detected(code, expected):
    assert detect_language(code) == expected


def test_existing_python_still_wins():
    """Regression: a typical Python snippet still classifies as python
    (after Kotlin/Swift/etc. fail to match)."""
    code = "import os\n\ndef greet(name):\n    return f'hi {name}'\n"
    assert detect_language(code) == "python"


def test_existing_javascript_still_wins():
    code = "const x = 1\nlet y = 2\nfunction add(a, b) { return a + b; }\n"
    assert detect_language(code) == "javascript"


def test_existing_rust_still_wins_with_fn_main():
    """`fn main()` is now a Rust-specific needle (the original bare
    `fn ` was ambiguous with Swift)."""
    code = "fn main() {\n    let mut v: Vec<i32> = vec![1, 2];\n}\n"
    assert detect_language(code) == "rust"


def test_rust_result_option_hints_match():
    code = "fn parse(s: &str) -> Result<i32, String> { Ok(0) }\n"
    assert detect_language(code) == "rust"


def test_existing_go_still_wins():
    code = "package main\nimport \"fmt\"\nfunc main() {\n    fmt.Println(\"hi\")\n}\n"
    assert detect_language(code) == "go"


def test_existing_sql_still_wins():
    code = "SELECT id, name FROM users WHERE active = 1\n"
    assert detect_language(code) == "sql"


def test_existing_shell_still_wins():
    code = "#!/bin/bash\nset -e\nfor f in $(ls); do\n  echo $f\ndone\n"
    assert detect_language(code) == "shell"


def test_detect_language_empty_returns_none():
    assert detect_language("") is None
    assert detect_language("   \n  ") is None


@pytest.mark.parametrize(
    "code,framework",
    [
        ("import React from 'react'\nfunction A() { return <div/> }\n", "react"),
        (
            "import { useState, useEffect } from 'react'\n"
            "function C() {\n  const [n, setN] = useState(0)\n  useEffect(() => {}, [])\n}\n",
            "react",
        ),
        (
            "import { createApp, defineComponent } from 'vue'\n"
            "createApp(defineComponent({ }))\n",
            "vue",
        ),
        ("@Component({ selector: 'a' })\nclass A {}\n", "angular"),
        (
            "import Link from 'next/link'\nexport async function getServerSideProps() {}\n",
            "nextjs",
        ),
        (
            "from django.db import models\nclass U(models.Model):\n    pass\n",
            "django",
        ),
        ("from flask import Flask\napp = Flask(__name__)\n@app.route('/')\ndef i(): ...\n", "flask"),
        ("from fastapi import FastAPI\napp = FastAPI()\n@app.get('/')\ndef r(): ...\n", "fastapi"),
        (
            "class Post < ActiveRecord::Base\nend\nclass HomeController < ApplicationController\nend\n",
            "rails",
        ),
        (
            "@SpringBootApplication\npublic class App { public static void main(String[] a) {} }\n",
            "spring",
        ),
        ("const e = require('express'); const app = express(); app.get('/', (req, res) => {})", "express"),
        ("r := gin.New()\nr.GET(\"/\", func(c *gin.Context) {})", "gin"),
        (
            "use actix_web::{web, App, HttpServer};\nHttpServer::new(|| App::new())\n",
            "actix",
        ),
        ("#[tokio::main]\nasync fn main() {}\n", "tokio"),
    ],
)
def test_framework_detection(code, framework):
    assert detect_framework(code) == framework


def test_detect_framework_none_for_plain_code():
    code = "def add(a, b):\n    return a + b\n"
    assert detect_framework(code) is None


def test_detect_framework_none_for_empty():
    assert detect_framework("") is None
    assert detect_framework("   ") is None


def test_react_wins_when_react_and_next_present():
    """A typical Next.js page also imports React. React is checked
    first in iteration order and wins. A downstream rule that wants
    to special-case Next can match on its own ``next/`` needles."""
    code = (
        "import React from 'react'\n"
        "import Link from 'next/link'\n"
        "export default function P() {}\n"
    )
    assert detect_framework(code) == "react"
