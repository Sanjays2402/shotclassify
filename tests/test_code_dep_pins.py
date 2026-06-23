"""Code dependency version-pin extraction tests.

Many code captures show package.json / requirements.txt /
Cargo.toml / Gemfile / composer.json / go.mod / pyproject.toml
content, and a dashboard reviewing the snippet wants to know
which packages it pins:

  "react": "^18.2.0"           (package.json)
  requests==2.31.0             (requirements.txt)
  serde = "1.0"                (Cargo.toml)
  gem 'rails', '~> 7.0'        (Gemfile)
  "monolog/monolog": "^2.5"    (composer.json)
  require github.com/x v1.2.3  (go.mod)
  implementation 'com.example:lib:1.0'  (build.gradle)

Each entry is a ``{package, version, ecosystem}`` dict where the
ecosystem tag is one of ``npm`` / ``pip`` / ``cargo`` / ``gem`` /
``composer`` / ``go`` / ``maven`` / ``gradle``.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_dep_pins

# ---- npm / package.json -------------------------------------


def test_npm_basic():
    result = extract_dep_pins('"react": "^18.2.0"')
    assert result == [{"ecosystem": "npm", "package": "react", "version": "^18.2.0"}]


def test_npm_scoped():
    result = extract_dep_pins('"@types/react": "^18.2"')
    assert result == [{"ecosystem": "npm", "package": "@types/react", "version": "^18.2"}]


def test_npm_exact_pin():
    result = extract_dep_pins('"vue": "3.4.0"')
    assert result == [{"ecosystem": "npm", "package": "vue", "version": "3.4.0"}]


def test_npm_caret():
    result = extract_dep_pins('"axios": "^1.6.0"')
    assert result[0]["version"] == "^1.6.0"


def test_npm_tilde():
    result = extract_dep_pins('"lodash": "~4.17.20"')
    assert result[0]["version"] == "~4.17.20"


def test_npm_wildcard():
    result = extract_dep_pins('"express": "*"')
    assert result[0]["version"] == "*"


def test_npm_pre_release():
    result = extract_dep_pins('"next": "14.0.0-rc.1"')
    assert result[0]["version"] == "14.0.0-rc.1"


def test_npm_multiple_deps():
    text = '"react": "^18.2.0"\n"vue": "3.4.0"\n"angular": "^17.0.0"'
    result = extract_dep_pins(text)
    assert len(result) == 3
    packages = {r["package"] for r in result}
    assert packages == {"react", "vue", "angular"}


def test_npm_full_package_json_snippet():
    text = """{
  "name": "my-app",
  "version": "1.0.0",
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "axios": "^1.6.0"
  },
  "devDependencies": {
    "typescript": "^5.0.0",
    "@types/react": "^18.2"
  }
}"""
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "react" in packages
    assert "react-dom" in packages
    assert "axios" in packages
    assert "typescript" in packages
    assert "@types/react" in packages
    # "name" and "version" top-level fields must NOT register
    assert "name" not in packages
    assert "version" not in packages


# ---- pip / requirements.txt --------------------------------


def test_pip_exact():
    result = extract_dep_pins("requests==2.31.0")
    assert result == [{"ecosystem": "pip", "package": "requests", "version": "==2.31.0"}]


def test_pip_range():
    result = extract_dep_pins("flask>=2.0,<3.0")
    assert result[0]["version"] == ">=2.0,<3.0"


def test_pip_minimum():
    result = extract_dep_pins("numpy>=1.20")
    assert result[0]["version"] == ">=1.20"


def test_pip_maximum():
    result = extract_dep_pins("django<5.0")
    assert result[0]["version"] == "<5.0"


def test_pip_compatible_release():
    result = extract_dep_pins("requests~=2.31")
    assert result[0]["version"] == "~=2.31"


def test_pip_with_extras():
    result = extract_dep_pins("requests[socks]==2.31.0")
    assert result[0]["package"] == "requests"
    assert result[0]["version"] == "==2.31.0"


def test_pip_with_multi_extras():
    result = extract_dep_pins("requests[socks,brotli]>=2.31")
    assert result[0]["package"] == "requests"


def test_pip_strips_inline_comment():
    result = extract_dep_pins("requests==2.31.0  # pinned for stability")
    assert result == [{"ecosystem": "pip", "package": "requests", "version": "==2.31.0"}]


def test_pip_full_requirements_snippet():
    text = """# Production dependencies
requests==2.31.0
flask>=2.0,<3.0
sqlalchemy==2.0.21
celery>=5.3.0
# Development
pytest>=7.0
black>=23.0"""
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "requests" in packages
    assert "flask" in packages
    assert "sqlalchemy" in packages
    assert "celery" in packages
    assert "pytest" in packages
    assert "black" in packages


def test_pip_does_not_match_assignment():
    # ``x = 5`` should NOT register as pip (no operator)
    result = extract_dep_pins("x = 5\ny = 10")
    assert result == []


# ---- cargo / Cargo.toml ------------------------------------


def test_cargo_simple_form():
    result = extract_dep_pins('serde = "1.0"')
    assert result == [{"ecosystem": "cargo", "package": "serde", "version": "1.0"}]


def test_cargo_table_form():
    text = 'tokio = { version = "1.0", features = ["full"] }'
    result = extract_dep_pins(text)
    assert result == [{"ecosystem": "cargo", "package": "tokio", "version": "1.0"}]


def test_cargo_table_form_with_path():
    text = 'mylib = { path = "../mylib", version = "0.1.0" }'
    result = extract_dep_pins(text)
    assert result == [{"ecosystem": "cargo", "package": "mylib", "version": "0.1.0"}]


def test_cargo_caret_version():
    result = extract_dep_pins('serde = "^1.0"')
    assert result[0]["version"] == "^1.0"


def test_cargo_multiple_deps():
    text = '[dependencies]\nserde = "1.0"\ntokio = { version = "1.32", features = ["full"] }\nclap = "4.4"\n'
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "serde" in packages
    assert "tokio" in packages
    assert "clap" in packages


def test_cargo_does_not_double_count_table_form():
    text = 'tokio = { version = "1.0", features = ["full"] }'
    result = extract_dep_pins(text)
    # Only one tokio entry, not two from simple + table matching
    tokio = [r for r in result if r["package"] == "tokio"]
    assert len(tokio) == 1


# ---- gem / Gemfile -----------------------------------------


def test_gem_double_quotes():
    result = extract_dep_pins('gem "rails", "~> 7.0"')
    assert result == [{"ecosystem": "gem", "package": "rails", "version": "~> 7.0"}]


def test_gem_single_quotes():
    result = extract_dep_pins("gem 'puma', '~> 6.4'")
    assert result == [{"ecosystem": "gem", "package": "puma", "version": "~> 6.4"}]


def test_gem_multiple():
    text = """gem 'rails', '~> 7.0'
gem 'puma', '~> 6.4'
gem 'sidekiq', '~> 7.2'"""
    result = extract_dep_pins(text)
    assert len(result) == 3
    packages = {r["package"] for r in result}
    assert packages == {"rails", "puma", "sidekiq"}


# ---- composer / composer.json ------------------------------


def test_composer_basic():
    result = extract_dep_pins('"monolog/monolog": "^2.5"')
    assert result == [{"ecosystem": "composer", "package": "monolog/monolog", "version": "^2.5"}]


def test_composer_symfony():
    result = extract_dep_pins('"symfony/console": "^6.0"')
    assert result[0]["ecosystem"] == "composer"
    assert result[0]["package"] == "symfony/console"


def test_composer_vs_npm_priority():
    # composer's vendor/package shape should win over generic npm,
    # which we restrict to bare names + @scoped/names only.
    text = '"monolog/monolog": "^2.5"\n"react": "^18.0"'
    result = extract_dep_pins(text)
    composer_entries = [r for r in result if r["ecosystem"] == "composer"]
    npm_entries = [r for r in result if r["ecosystem"] == "npm"]
    assert len(composer_entries) == 1
    assert len(npm_entries) == 1


# ---- go / go.mod -------------------------------------------


def test_go_mod_with_require():
    result = extract_dep_pins("require github.com/x/y v1.2.3")
    assert result == [{"ecosystem": "go", "package": "github.com/x/y", "version": "v1.2.3"}]


def test_go_mod_bare_inside_block():
    # Inside ``require ( ... )`` block, each line has no ``require`` prefix.
    text = """require (
    github.com/spf13/cobra v1.7.0
    github.com/sirupsen/logrus v1.9.3
)"""
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "github.com/spf13/cobra" in packages
    assert "github.com/sirupsen/logrus" in packages


def test_go_mod_pre_release():
    result = extract_dep_pins("require golang.org/x/sys v0.0.0-20210630005230-0f9fa26af87c")
    assert result[0]["package"] == "golang.org/x/sys"
    assert "v0.0.0-20210630005230-0f9fa26af87c" in result[0]["version"]


def test_go_mod_incompatible():
    result = extract_dep_pins("require github.com/foo/bar v2.1.0+incompatible")
    assert result[0]["version"].endswith("+incompatible")


def test_go_no_dot_in_name_rejected():
    # ``require module v1.2.3`` (no dot in path) is rejected because
    # real go module paths always contain a hostname.
    result = extract_dep_pins("require module v1.2.3")
    assert result == []


# ---- maven / pom.xml ---------------------------------------


def test_maven_inline_xml():
    text = "<groupId>org.apache</groupId><artifactId>commons</artifactId><version>3.12</version>"
    result = extract_dep_pins(text)
    assert result == [
        {"ecosystem": "maven", "package": "org.apache:commons", "version": "3.12"}
    ]


def test_maven_with_whitespace():
    text = """<groupId>com.google.guava</groupId>
<artifactId>guava</artifactId>
<version>32.1.3-jre</version>"""
    result = extract_dep_pins(text)
    assert result[0]["package"] == "com.google.guava:guava"
    assert result[0]["version"] == "32.1.3-jre"


# ---- gradle / build.gradle ---------------------------------


def test_gradle_implementation():
    result = extract_dep_pins("implementation 'com.example:lib:1.0'")
    assert result == [
        {"ecosystem": "gradle", "package": "com.example:lib", "version": "1.0"}
    ]


def test_gradle_test_implementation():
    result = extract_dep_pins('testImplementation "junit:junit:4.13.2"')
    assert result[0]["package"] == "junit:junit"
    assert result[0]["version"] == "4.13.2"


def test_gradle_api():
    result = extract_dep_pins("api 'org.slf4j:slf4j-api:2.0.7'")
    assert result[0]["package"] == "org.slf4j:slf4j-api"


def test_gradle_kapt():
    result = extract_dep_pins("kapt 'com.google.dagger:dagger-compiler:2.48'")
    assert result[0]["ecosystem"] == "gradle"


# ---- Cross-ecosystem mixed snippet -------------------------


def test_mixed_manifest_snippet():
    # A blog post that quotes from both a package.json and a
    # requirements.txt -- each line tags independently.
    text = """// package.json
"react": "^18.2.0"

# requirements.txt
django>=4.0
"""
    result = extract_dep_pins(text)
    npm = [r for r in result if r["ecosystem"] == "npm"]
    pip = [r for r in result if r["ecosystem"] == "pip"]
    assert len(npm) == 1
    assert npm[0]["package"] == "react"
    assert len(pip) == 1
    assert pip[0]["package"] == "django"


# ---- Deduplication -----------------------------------------


def test_duplicate_pins_deduped():
    text = '"react": "^18.2.0"\n"react": "^18.2.0"'
    result = extract_dep_pins(text)
    assert len(result) == 1


def test_different_versions_kept():
    # Same package with different versions is two entries.
    text = '"react": "^18.2.0"\n"react": "^17.0.0"'
    result = extract_dep_pins(text)
    assert len(result) == 2


# ---- Empty / edge cases ------------------------------------


def test_empty_code_returns_empty_list():
    assert extract_dep_pins("") == []


def test_none_code_returns_empty_list():
    assert extract_dep_pins(None) == []  # type: ignore[arg-type]


def test_function_body_no_pins():
    text = """def foo(x: int) -> int:
    return x + 1"""
    result = extract_dep_pins(text)
    assert result == []


def test_class_body_no_pins():
    text = """class MyClass:
    def __init__(self):
        self.x = 1"""
    result = extract_dep_pins(text)
    assert result == []


def test_prose_no_pins():
    text = "This is a paragraph of plain English text."
    result = extract_dep_pins(text)
    assert result == []


# ---- Blocklist for placeholder names -----------------------


def test_package_header_rejected():
    # A doc-table that prints ``"package": "1.0"`` should NOT
    # register because ``package`` is a generic header word.
    result = extract_dep_pins('"package": "1.0"')
    assert result == []


def test_version_header_rejected():
    result = extract_dep_pins('"version": "1.0"')
    assert result == []


def test_name_header_rejected():
    result = extract_dep_pins('"name": "my-app"')
    assert result == []


# ---- Pipeline integration via enrich_code ------------------


def test_enrich_code_populates_dep_pins():
    text = """// package.json snippet
"react": "^18.2.0"
"vue": "3.4.0\""""
    fields = enrich_code(None, OCRResult(text=text))
    assert len(fields.dep_pins) == 2
    packages = {p["package"] for p in fields.dep_pins}
    assert "react" in packages
    assert "vue" in packages


def test_enrich_code_existing_dep_pins_preserved():
    # Caller-supplied dep_pins should NOT be overwritten by the heuristic.
    existing = CodeFields(
        code='"react": "^18.2.0"',
        dep_pins=[{"ecosystem": "npm", "package": "react", "version": "^17.0.0"}],
    )
    fields = enrich_code(existing, OCRResult(text=""))
    # Existing list preserved (the LLM-supplied ^17 wins over the
    # heuristic-detected ^18 because callers are trusted).
    assert len(fields.dep_pins) == 1
    assert fields.dep_pins[0]["version"] == "^17.0.0"


def test_enrich_code_no_pins_yields_empty_list():
    text = "def foo(): return 1"
    fields = enrich_code(None, OCRResult(text=text))
    assert fields.dep_pins == []


def test_enrich_code_with_pip_format():
    text = """requests==2.31.0
flask>=2.0
sqlalchemy~=2.0"""
    fields = enrich_code(None, OCRResult(text=text))
    assert len(fields.dep_pins) >= 3
    assert all(p["ecosystem"] == "pip" for p in fields.dep_pins)


def test_enrich_code_with_cargo_format():
    text = """[dependencies]
serde = "1.0"
tokio = { version = "1.32", features = ["full"] }
"""
    fields = enrich_code(None, OCRResult(text=text))
    cargo = [p for p in fields.dep_pins if p["ecosystem"] == "cargo"]
    assert len(cargo) >= 2


# ---- Realistic full snippets -------------------------------


def test_real_package_json():
    text = """{
  "name": "my-react-app",
  "version": "0.1.0",
  "dependencies": {
    "next": "^14.0.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0"
  }
}"""
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "next" in packages
    assert "react" in packages
    assert "react-dom" in packages


def test_real_requirements_txt():
    text = """fastapi==0.104.1
uvicorn[standard]>=0.24
pydantic>=2.5,<3.0
sqlalchemy==2.0.23
alembic>=1.13"""
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "fastapi" in packages
    assert "uvicorn" in packages
    assert "pydantic" in packages
    assert "sqlalchemy" in packages
    assert "alembic" in packages


def test_real_cargo_toml():
    text = """[package]
name = "my-app"
version = "0.1.0"

[dependencies]
clap = "4.4"
serde = { version = "1.0", features = ["derive"] }
tokio = { version = "1.32", features = ["full"] }
reqwest = "0.11"
"""
    result = extract_dep_pins(text)
    # name/version are header keys -- the simple regex would catch
    # them too but the blocklist prevents that.
    packages = {r["package"] for r in result}
    assert "clap" in packages
    assert "serde" in packages
    assert "tokio" in packages
    assert "reqwest" in packages
    assert "name" not in packages
    assert "version" not in packages


def test_real_gemfile():
    text = """source 'https://rubygems.org'
gem 'rails', '~> 7.1.0'
gem 'puma', '~> 6.4'
gem 'pg', '~> 1.5'
group :development do
  gem 'rspec-rails', '~> 6.0'
  gem 'rubocop', require: false
end"""
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "rails" in packages
    assert "puma" in packages
    assert "pg" in packages
    assert "rspec-rails" in packages
    # rubocop has no version pin, so it should NOT register
    assert "rubocop" not in packages


def test_real_composer_json():
    text = """{
    "require": {
        "php": "^8.1",
        "laravel/framework": "^10.0",
        "monolog/monolog": "^3.0",
        "guzzlehttp/guzzle": "^7.5"
    }
}"""
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "laravel/framework" in packages
    assert "monolog/monolog" in packages
    assert "guzzlehttp/guzzle" in packages


def test_real_go_mod():
    text = """module github.com/me/myapp

go 1.21

require (
    github.com/spf13/cobra v1.7.0
    github.com/spf13/viper v1.18.2
    github.com/stretchr/testify v1.8.4
    google.golang.org/grpc v1.59.0
)"""
    result = extract_dep_pins(text)
    packages = {r["package"] for r in result}
    assert "github.com/spf13/cobra" in packages
    assert "github.com/spf13/viper" in packages
    assert "github.com/stretchr/testify" in packages
    assert "google.golang.org/grpc" in packages


# ---- Cap enforcement ---------------------------------------


def test_cap_at_100():
    # Construct >100 npm dep lines.
    text = "\n".join(
        f'"pkg-{i}": "^1.{i}.0"' for i in range(150)
    )
    result = extract_dep_pins(text)
    assert len(result) <= 100


# ---- LLM wire format ---------------------------------------


def test_llm_wire_format_dep_pins():
    from shotclassify_classify.client import _parse_llm_payload
    payload = {
        "primary": "code_snippet",
        "confidences": [],
        "rationale": "",
        "fields": {
            "code": {
                "language": "json",
                "code": '"react": "^18"',
                "dep_pins": [
                    {"ecosystem": "npm", "package": "react", "version": "^18"}
                ],
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.code is not None
    assert len(fields.code.dep_pins) == 1
    assert fields.code.dep_pins[0]["package"] == "react"
