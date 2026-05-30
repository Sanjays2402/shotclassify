"""Static checks for the Helm chart.

These do not require a live cluster. They invoke `helm lint` plus `helm
template` against the bundled chart and assert that the rendered manifests
expose the availability and pod-security properties we expect in production
(PodDisruptionBudgets, non-root securityContext on every workload, resource
limits, probes). A regression that drops one of these guarantees fails CI.

The tests skip cleanly if `helm` is not on PATH (e.g. minimal dev shells).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

try:
    import yaml  # PyYAML ships as a dep of the API/worker already
except ImportError:  # pragma: no cover - yaml is in deps
    yaml = None  # type: ignore[assignment]

CHART_DIR = Path(__file__).resolve().parent.parent / "infra" / "helm" / "shotclassify"


def _helm_available() -> bool:
    return shutil.which("helm") is not None


pytestmark = pytest.mark.skipif(
    not _helm_available() or yaml is None,
    reason="helm binary or PyYAML not available",
)


def _render(extra_values: dict | None = None) -> list[dict]:
    cmd = ["helm", "template", "release", str(CHART_DIR)]  # noqa: S603, S607
    if extra_values:
        for k, v in extra_values.items():
            cmd += ["--set", f"{k}={v}"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
    docs = [d for d in yaml.safe_load_all(out.stdout) if d]
    return docs


def test_helm_lint_passes() -> None:
    res = subprocess.run(  # noqa: S603
        ["helm", "lint", str(CHART_DIR)],  # noqa: S607
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"helm lint failed:\n{res.stdout}\n{res.stderr}"


def test_pod_disruption_budgets_present() -> None:
    docs = _render()
    pdbs = {
        d["metadata"]["name"]: d for d in docs if d.get("kind") == "PodDisruptionBudget"
    }
    # api + worker are enabled by default; web is opt-in.
    assert any(n.endswith("-api") for n in pdbs), pdbs.keys()
    assert any(n.endswith("-worker") for n in pdbs), pdbs.keys()
    for pdb in pdbs.values():
        assert pdb["spec"]["minAvailable"] >= 1
        assert pdb["spec"]["selector"]["matchLabels"]


def test_every_deployment_runs_non_root_with_dropped_caps() -> None:
    docs = _render()
    deployments = [d for d in docs if d.get("kind") == "Deployment"]
    assert len(deployments) >= 3, "expected api + worker + web deployments"
    for d in deployments:
        name = d["metadata"]["name"]
        pod = d["spec"]["template"]["spec"]
        psc = pod.get("securityContext", {})
        assert psc.get("runAsNonRoot") is True, f"{name} runs as root"
        assert psc.get("seccompProfile", {}).get("type") == "RuntimeDefault", name
        for c in pod["containers"]:
            csc = c.get("securityContext", {})
            assert csc.get("allowPrivilegeEscalation") is False, f"{name}/{c['name']}"
            caps = csc.get("capabilities", {}).get("drop", [])
            assert "ALL" in caps, f"{name}/{c['name']} does not drop ALL caps"


def test_every_deployment_has_resource_limits() -> None:
    docs = _render()
    for d in (d for d in docs if d.get("kind") == "Deployment"):
        for c in d["spec"]["template"]["spec"]["containers"]:
            res = c.get("resources", {})
            assert res.get("requests"), f"{d['metadata']['name']}/{c['name']} no requests"
            assert res.get("limits"), f"{d['metadata']['name']}/{c['name']} no limits"


def test_every_deployment_has_liveness_probe() -> None:
    docs = _render()
    for d in (d for d in docs if d.get("kind") == "Deployment"):
        for c in d["spec"]["template"]["spec"]["containers"]:
            assert c.get("livenessProbe"), (
                f"{d['metadata']['name']}/{c['name']} missing livenessProbe"
            )


def test_pdb_can_be_disabled() -> None:
    docs = _render({"pdb.api.enabled": "false", "pdb.worker.enabled": "false"})
    pdbs = [d for d in docs if d.get("kind") == "PodDisruptionBudget"]
    # web pdb defaults to disabled too, so we expect zero.
    assert pdbs == [], pdbs
