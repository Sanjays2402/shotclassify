"""Static checks for the production Dockerfiles.

These do not require a Docker daemon. They verify the multi-stage structure
and key hardening properties (non-root user, healthcheck, runtime stage
without compilers) so a refactor that regresses these properties fails CI.
"""
from __future__ import annotations

from pathlib import Path

import pytest

DOCKER_DIR = Path(__file__).resolve().parent.parent / "infra" / "docker"


def _read(name: str) -> str:
    p = DOCKER_DIR / name
    assert p.exists(), f"{p} missing"
    return p.read_text()


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.worker", "Dockerfile.web"])
def test_dockerfile_is_multi_stage(name: str) -> None:
    text = _read(name)
    from_lines = [ln for ln in text.splitlines() if ln.strip().upper().startswith("FROM ")]
    assert len(from_lines) >= 2, f"{name} must be multi-stage (>=2 FROM): got {from_lines}"
    # Each FROM must declare an explicit stage alias for clarity.
    for ln in from_lines:
        assert " AS " in ln.upper(), f"{name} stage missing alias: {ln}"


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.worker", "Dockerfile.web"])
def test_dockerfile_runs_as_non_root(name: str) -> None:
    text = _read(name)
    user_lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("USER ")]
    assert user_lines, f"{name} must declare a USER directive"
    last = user_lines[-1]
    assert "root" not in last.lower(), f"{name} final USER must not be root: {last}"


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.web"])
def test_dockerfile_has_healthcheck(name: str) -> None:
    text = _read(name)
    assert "HEALTHCHECK" in text, f"{name} must declare a HEALTHCHECK"


def test_api_runtime_stage_has_no_build_toolchain() -> None:
    """The runtime stage should not install build-essential / -dev headers."""
    text = _read("Dockerfile")
    # Split on the runtime stage marker.
    parts = text.split("AS runtime")
    assert len(parts) >= 2, "Dockerfile must have a stage named 'runtime'"
    runtime = parts[1]
    forbidden = ["build-essential", "libpq-dev", "libffi-dev", "libssl-dev", "libtesseract-dev"]
    for token in forbidden:
        assert token not in runtime, (
            f"runtime stage must not install build dep '{token}'; keep it in the builder stage"
        )


def test_api_runtime_has_tini_entrypoint() -> None:
    text = _read("Dockerfile")
    assert 'ENTRYPOINT ["/usr/bin/tini"' in text, "API runtime must use tini for signal handling"


def test_dockerignore_present_and_excludes_secrets() -> None:
    root = DOCKER_DIR.parent.parent
    ign = root / ".dockerignore"
    assert ign.exists(), ".dockerignore must exist at repo root"
    content = ign.read_text()
    for pat in [".git", ".env", "node_modules", "*.db"]:
        assert pat in content, f".dockerignore missing pattern: {pat}"
