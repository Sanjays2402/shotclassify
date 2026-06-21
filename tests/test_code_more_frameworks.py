"""Additional framework guesses: Laravel, Symfony, Phoenix, Quarkus, Micronaut.

These join the existing catalog (React/Vue/Angular/Next/Django/Flask/
FastAPI/Rails/Spring/Express/Gin/Actix/Tokio) without disturbing the
ordering that previous tests rely on. The new entries cover PHP web
(Laravel + Symfony), Elixir Phoenix, and the two JVM Spring rivals
(Quarkus + Micronaut), which together account for the majority of
backend snippets the original set missed.
"""
from __future__ import annotations

import pytest
from shotclassify_extract.code import detect_framework


@pytest.mark.parametrize(
    "code,framework",
    [
        # Laravel: Illuminate facades + the canonical controller base.
        (
            "<?php\nuse Illuminate\\Support\\Facades\\Route;\n"
            "Route::get('/', function () { return 'hi'; });\n",
            "laravel",
        ),
        (
            "<?php\nnamespace App\\Http\\Controllers;\n"
            "use Illuminate\\Http\\Request;\n"
            "class HomeController extends Controller { }\n",
            "laravel",
        ),
        # Symfony: components + AbstractController + the route attribute.
        (
            "<?php\nuse Symfony\\Component\\HttpFoundation\\Response;\n"
            "use Symfony\\Component\\Routing\\Annotation\\Route;\n"
            "class HomeController extends AbstractController { "
            "#[Route('/')] public function index(): Response { } }\n",
            "symfony",
        ),
        # Phoenix: router macros + endpoint.
        (
            "defmodule MyAppWeb.Router do\n"
            "  use Phoenix.Router\n"
            "  pipeline :browser do\n  end\n"
            "  scope \"/\" do\n    pipe_through :browser\n  end\nend\n",
            "phoenix",
        ),
        (
            "defmodule MyAppWeb.Endpoint do\n"
            "  use Phoenix.Endpoint, otp_app: :my_app\nend\n",
            "phoenix",
        ),
        # Quarkus: io.quarkus import + scope annotation.
        (
            "package org.acme;\n"
            "import io.quarkus.runtime.Quarkus;\n"
            "@ApplicationScoped\npublic class GreetingService { }\n",
            "quarkus",
        ),
        (
            "import io.quarkus.test.junit.QuarkusTest;\n"
            "@QuarkusTest\npublic class GreetingResourceTest { }\n",
            "quarkus",
        ),
        # Micronaut: io.micronaut import + the test annotation.
        (
            "package example.micronaut;\n"
            "import io.micronaut.http.MediaType;\n"
            "import io.micronaut.http.annotation.Controller;\n"
            "@Controller(\"/\")\npublic class HomeController { }\n",
            "micronaut",
        ),
        (
            "import io.micronaut.test.extensions.junit5.annotation.MicronautTest;\n"
            "@MicronautTest\nclass HelloControllerTest { }\n",
            "micronaut",
        ),
    ],
)
def test_new_frameworks_detected(code, framework):
    assert detect_framework(code) == framework


def test_quarkus_wins_when_spring_compat_shim_is_present():
    """A Quarkus extension that adopts Spring's `@RestController` for
    compatibility must still tag Quarkus -- our iteration order puts
    `quarkus` before `spring`, and the io.quarkus needle is the more
    specific signal."""
    code = (
        "import io.quarkus.runtime.Quarkus;\n"
        "import io.quarkus.spring.web.runtime.SpringWebRecorder;\n"
        "@RestController\npublic class HelloController { }\n"
    )
    assert detect_framework(code) == "quarkus"


def test_micronaut_wins_over_spring_when_both_imports_present():
    """Same as above but for Micronaut: the io.micronaut needle is the
    operator's intent; a stray @RestController must not steal the tag."""
    code = (
        "import io.micronaut.http.annotation.Controller;\n"
        "@RestController\npublic class C { }\n"
    )
    assert detect_framework(code) == "micronaut"


def test_existing_spring_still_wins_for_pure_spring():
    """Regression: no Quarkus / Micronaut needle present -> Spring."""
    code = (
        "@SpringBootApplication\npublic class App { "
        "public static void main(String[] a) {} }\n"
    )
    assert detect_framework(code) == "spring"


def test_existing_rails_still_wins():
    """Regression: rails detection still fires for ActiveRecord +
    ApplicationController code (no PHP / Elixir / JVM needles)."""
    code = (
        "class Post < ActiveRecord::Base\nend\n"
        "class HomeController < ApplicationController\nend\n"
    )
    assert detect_framework(code) == "rails"


def test_plain_php_without_framework_returns_none():
    """`<?php echo "hi";` is PHP but not a framework -- return None."""
    code = "<?php\necho \"hi\";\n"
    assert detect_framework(code) is None


def test_plain_elixir_without_phoenix_returns_none():
    """Bare Elixir defmodule without Phoenix needles -> None."""
    code = (
        "defmodule Calc do\n"
        "  def add(a, b), do: a + b\nend\n"
    )
    assert detect_framework(code) is None
