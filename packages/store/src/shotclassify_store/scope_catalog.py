"""Canonical catalog of API scopes.

Enterprise procurement reviews routinely ask: "Show me, in one place, every
permission your platform exposes, what it grants, what it does NOT grant,
and which built-in roles include it." Without that, auditors cannot
size the blast radius of a leaked credential and tend to reject the vendor.

This module is the single source of truth for that catalog. It is
intentionally code-first (not config) so the build fails the moment a new
scope is referenced in middleware without an accompanying entry here.

The catalog is consumed by:

* :mod:`shotclassify_store.api_keys` (``VALID_SCOPES`` validation)
* ``GET /v1/scopes`` (public-after-auth discovery for API consumers)
* ``GET /v1/auth/introspect`` (RFC 7662 style "what can this credential do")
* the ``/settings/scopes`` admin UI
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ScopeDefinition:
    """A single permission exposed by the API.

    ``mutating`` is the field auditors care about most: read-only scopes
    cannot be used to change tenant state and therefore have a lower risk
    profile when issued to a long-lived credential.
    """

    id: str
    title: str
    description: str
    mutating: bool
    # Built-in roles that include this scope by default. Used by the UI to
    # render the role/scope matrix without re-deriving it.
    roles: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "mutating": self.mutating,
            "roles": list(self.roles),
        }


# Order is the order rendered in the UI. Read-before-write-before-admin.
SCOPE_CATALOG: tuple[ScopeDefinition, ...] = (
    ScopeDefinition(
        id="read:classifications",
        title="Read classifications",
        description=(
            "List and fetch screenshot classification results, history "
            "rows, saved views, and per-result blobs scoped to the "
            "calling credential's tenant."
        ),
        mutating=False,
        roles=("viewer", "operator", "admin"),
    ),
    ScopeDefinition(
        id="write:classifications",
        title="Submit classifications",
        description=(
            "Upload screenshots, run classification, edit history labels, "
            "and create or update saved views. Does not grant access to "
            "tenant settings, members, or audit data."
        ),
        mutating=True,
        roles=("operator", "admin"),
    ),
    ScopeDefinition(
        id="read:audit",
        title="Read audit log",
        description=(
            "Read the tenant's immutable audit log, support-access "
            "grants, and audit sink delivery history. Required for "
            "compliance exports and SIEM verification."
        ),
        mutating=False,
        roles=("admin",),
    ),
    ScopeDefinition(
        id="scim:provision",
        title="SCIM 2.0 provisioning",
        description=(
            "Create, update, and deprovision users and groups via the "
            "SCIM 2.0 endpoints. Issued only to identity-provider "
            "service accounts; never to interactive users."
        ),
        mutating=True,
        roles=(),
    ),
    ScopeDefinition(
        id="admin",
        title="Full admin",
        description=(
            "Superset shorthand: implies every other scope and grants "
            "the ability to manage members, security settings, API "
            "keys, webhooks, and billing. Treat as root-equivalent for "
            "the tenant."
        ),
        mutating=True,
        roles=("admin",),
    ),
)


_BY_ID: dict[str, ScopeDefinition] = {s.id: s for s in SCOPE_CATALOG}


def all_scope_ids() -> frozenset[str]:
    """The canonical set of scope ids. Use as the validation allowlist."""
    return frozenset(_BY_ID.keys())


def get_scope(scope_id: str) -> ScopeDefinition | None:
    return _BY_ID.get(scope_id)


def describe(scopes: Iterable[str]) -> list[dict]:
    """Hydrate raw scope ids into full catalog entries.

    Unknown scopes are surfaced with ``"unknown": True`` rather than
    silently dropped so an admin reviewing a legacy key sees that
    something is off.
    """
    out: list[dict] = []
    for s in scopes:
        entry = _BY_ID.get(s)
        if entry is None:
            out.append(
                {
                    "id": s,
                    "title": s,
                    "description": "Unknown scope. Likely from a legacy or removed feature; revoke this credential.",
                    "mutating": True,
                    "roles": [],
                    "unknown": True,
                }
            )
        else:
            d = entry.to_dict()
            d["unknown"] = False
            out.append(d)
    return out
