"""Cross-category social-handle extractor.

Social-media handles surface across every category of screenshot --
chat captures share creators' Twitter handles, code snippets paste
GitHub repo links, document captures cite LinkedIn profiles, error
logs reference the upstream's GitHub repo, receipts print the
merchant's Instagram handle. Rather than teach each per-category
extractor to find them, we run :func:`extract_social` once on the OCR
text and stash the typed list under
``ExtractedFields.raw["social"]`` so dashboards, routing rules, and
downstream agents have a single place to look.

Output shape: a list of ``{"platform": str, "handle": str}`` dicts.
Each entry's ``platform`` is one of ``twitter`` / ``github`` /
``linkedin`` / ``instagram`` / ``tiktok`` / ``youtube`` / ``reddit`` /
``mastodon`` and ``handle`` is the canonical short identifier the
platform uses (the part you'd type in the URL bar after the
platform's hostname).

Recognised forms per platform:

* **Twitter / X**
    * ``twitter.com/jack`` / ``x.com/jack``
    * ``@jack`` when a Twitter / X anchor is present on the same line.
* **GitHub**
    * ``github.com/torvalds`` (user)
    * ``github.com/torvalds/linux`` (user/repo, stored as
      ``user/repo``).
* **LinkedIn**
    * ``linkedin.com/in/satya-nadella`` (personal profile)
    * ``linkedin.com/company/microsoft`` (company page)
* **Instagram**
    * ``instagram.com/natgeo``
    * ``@natgeo`` when an Instagram / Insta anchor is on the same line.
* **TikTok**
    * ``tiktok.com/@khaby.lame``
* **YouTube**
    * ``youtube.com/@mkbhd`` (channel handle, post-2022 form)
    * ``youtube.com/c/mkbhd`` (legacy channel slug)
    * ``youtube.com/user/marquesbrownlee`` (legacy user slug)
* **Reddit**
    * ``reddit.com/u/spez`` (user)
    * ``reddit.com/r/programming`` (subreddit, stored as ``r/programming``)
* **Mastodon**
    * ``@user@instance.tld`` (the two-at-sign federated handle)

Distinct from the chat-mention extractor because OCR may carry a
code snippet that quotes a Twitter handle (``@torvalds`` in a code
comment) or a document that cites a LinkedIn URL -- both of those
should surface here even when the category isn't chat.

Capped at 50 entries; de-duplicated on the (platform, handle) pair;
first-seen order preserved across all matchers.
"""
from __future__ import annotations

import re

_MAX_SOCIAL = 50

# Twitter / X URL forms. Twitter renamed to X in 2023, both hostnames
# still work in the wild. The captured handle is bounded to 1..15
# chars (Twitter's actual max) and uses the
# letter / digit / underscore alphabet Twitter allows.
_TWITTER_URL_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/"
    r"(?!status\b|search\b|home\b|i\b|hashtag\b|share\b|intent\b|explore\b|"
    r"settings\b|notifications\b|messages\b|compose\b|login\b|signup\b|"
    r"following\b|followers\b|about\b)"
    r"(?P<handle>[A-Za-z0-9_]{1,15})"
    r"(?:/(?:status/\d+|with_replies|media|likes|following|followers)?)?"
    r"\b",
    re.IGNORECASE,
)

# @handle with explicit Twitter / X anchor on the same line. The
# anchor catches headers like "Twitter: @jack" or "Follow me on X
# at @jack".
_TWITTER_AT_HANDLE_RE = re.compile(
    r"(?:^|\W)"
    r"(?:twitter|x|tweet|follow\s+me|find\s+me)"
    r"[^\n@]{0,40}?"
    r"@(?P<handle>[A-Za-z0-9_]{1,15})\b",
    re.IGNORECASE,
)

# GitHub URLs. We capture user OR user/repo. The reserved-path
# rejection prevents `/login` / `/marketplace` / `/explore` from
# tagging as users.
_GITHUB_URL_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?github\.com/"
    r"(?!login\b|join\b|marketplace\b|explore\b|topics\b|trending\b|"
    r"settings\b|notifications\b|about\b|pricing\b|security\b|enterprise\b|"
    r"features\b|customer-stories\b|sponsors\b|orgs\b|organizations\b|"
    r"site\b)"
    r"(?P<user>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})?)"
    r"(?:/(?P<repo>[A-Za-z0-9._-]{1,100}))?"
    r"(?=[/?#\s.,;:!)\]]|$)",
    re.IGNORECASE,
)

# LinkedIn URLs. Personal `/in/<slug>` and company `/company/<slug>`.
# Slugs allow letters, digits, hyphens.
_LINKEDIN_URL_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?(?:[a-z]{2,3}\.)?linkedin\.com/"
    r"(?P<kind>in|company|school)/"
    r"(?P<slug>[A-Za-z0-9-]{1,100})"
    r"(?:/)?(?=[/?#\s.,;:!)\]]|$)",
    re.IGNORECASE,
)

# Instagram URLs.
_INSTAGRAM_URL_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?instagram\.com/"
    r"(?!p/|reel/|stories/|tv/|explore/|accounts/|direct/)"
    r"(?P<handle>[A-Za-z0-9_.]{1,30})"
    r"(?:/)?(?=[/?#\s.,;:!)\]]|$)",
    re.IGNORECASE,
)

# Instagram @handle with explicit Instagram / IG / Insta anchor on
# the same line.
_INSTAGRAM_AT_HANDLE_RE = re.compile(
    r"(?:^|\W)"
    r"(?:instagram|insta|ig|gram)"
    r"[^\n@]{0,40}?"
    r"@(?P<handle>[A-Za-z0-9_.]{1,30})\b",
    re.IGNORECASE,
)

# TikTok URLs.
_TIKTOK_URL_RE = re.compile(
    r"\b(?:https?://)?(?:www\.|vm\.)?tiktok\.com/"
    r"@(?P<handle>[A-Za-z0-9_.]{1,24})"
    r"(?:/)?(?=[/?#\s.,;:!)\]]|$)",
    re.IGNORECASE,
)

# YouTube URLs. Three modern forms:
#   * youtube.com/@handle      (post-2022 channel handle)
#   * youtube.com/c/slug       (legacy channel slug)
#   * youtube.com/user/slug    (legacy user slug)
_YOUTUBE_URL_RE = re.compile(
    r"\b(?:https?://)?(?:www\.|m\.)?youtube\.com/"
    r"(?:"
    r"@(?P<handle>[A-Za-z0-9_.-]{1,30})"
    r"|c/(?P<cslug>[A-Za-z0-9_.-]{1,100})"
    r"|user/(?P<uslug>[A-Za-z0-9_.-]{1,100})"
    r")"
    r"(?:/)?(?=[/?#\s.,;:!)\]]|$)",
    re.IGNORECASE,
)

# Reddit URLs.
_REDDIT_URL_RE = re.compile(
    r"\b(?:https?://)?(?:www\.|old\.|np\.)?reddit\.com/"
    r"(?P<kind>r|u|user)/"
    r"(?P<slug>[A-Za-z0-9_-]{1,21})"
    r"(?:/)?(?=[/?#\s.,;:!)\]]|$)",
    re.IGNORECASE,
)

# Mastodon: ``@user@instance.tld`` two-at federated handle. The
# instance must look like a hostname (letters / digits / dots / hyphens)
# with a TLD-shaped tail.
_MASTODON_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])"
    r"@(?P<user>[A-Za-z0-9_]{1,30})"
    r"@(?P<instance>[A-Za-z0-9][A-Za-z0-9.-]+\.[A-Za-z]{2,24})"
    r"\b",
)


def extract_social(text: str) -> list[dict[str, str]]:
    """Return social-media handles found in ``text``.

    Each entry is ``{"platform": str, "handle": str}``. Iterates
    matchers in priority order so that the most-specific platform-
    URL form is preferred over a generic ``@handle`` line. The
    @handle matchers for Twitter and Instagram require a same-line
    platform anchor so a chat ``@jack`` mention doesn't get
    mis-attributed.

    Capped at 50 entries; de-duplicated on the (platform, handle.lower())
    pair; first-seen-in-text order preserved.
    """
    if not text or not isinstance(text, str):
        return []

    seen: set[tuple[str, str]] = set()
    candidates: list[tuple[int, str, str]] = []

    # 1) Twitter / X URLs.
    for m in _TWITTER_URL_RE.finditer(text):
        key = ("twitter", m.group("handle").lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "twitter", m.group("handle")))

    # 2) GitHub URLs (user or user/repo).
    for m in _GITHUB_URL_RE.finditer(text):
        user = m.group("user")
        repo = m.group("repo")
        if repo:
            handle = f"{user}/{repo}"
        else:
            handle = user
        key = ("github", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "github", handle))

    # 3) LinkedIn URLs (in / company / school).
    for m in _LINKEDIN_URL_RE.finditer(text):
        kind = m.group("kind").lower()
        slug = m.group("slug")
        # We store kind+slug for company / school so the handle is
        # disambiguated from a personal profile, and bare slug for in.
        if kind == "in":
            handle = slug
        else:
            handle = f"{kind}/{slug}"
        key = ("linkedin", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "linkedin", handle))

    # 4) Instagram URLs.
    for m in _INSTAGRAM_URL_RE.finditer(text):
        handle = m.group("handle")
        key = ("instagram", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "instagram", handle))

    # 5) TikTok URLs.
    for m in _TIKTOK_URL_RE.finditer(text):
        handle = m.group("handle")
        key = ("tiktok", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "tiktok", handle))

    # 6) YouTube URLs.
    for m in _YOUTUBE_URL_RE.finditer(text):
        handle = m.group("handle") or m.group("cslug") or m.group("uslug")
        if not handle:
            continue
        key = ("youtube", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "youtube", handle))

    # 7) Reddit URLs (r/sub or u/user).
    for m in _REDDIT_URL_RE.finditer(text):
        kind = m.group("kind").lower()
        slug = m.group("slug")
        if kind == "r":
            handle = f"r/{slug}"
        else:
            # ``u`` and ``user`` are equivalent on Reddit; canonicalise.
            handle = f"u/{slug}"
        key = ("reddit", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "reddit", handle))

    # 8) Mastodon federated handle ``@user@instance.tld``.
    for m in _MASTODON_RE.finditer(text):
        handle = f"@{m.group('user')}@{m.group('instance')}"
        key = ("mastodon", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "mastodon", handle))

    # 9) @handle with explicit Twitter anchor.
    for m in _TWITTER_AT_HANDLE_RE.finditer(text):
        handle = m.group("handle")
        key = ("twitter", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "twitter", handle))

    # 10) @handle with explicit Instagram anchor. Runs AFTER Twitter
    #     because the regex priority is dictated by URL specificity,
    #     not anchor type; both anchor regexes are tight enough that
    #     no cross-anchor false-positive should occur.
    for m in _INSTAGRAM_AT_HANDLE_RE.finditer(text):
        handle = m.group("handle")
        key = ("instagram", handle.lower())
        if key not in seen:
            seen.add(key)
            candidates.append((m.start(), "instagram", handle))

    candidates.sort(key=lambda x: x[0])
    out: list[dict[str, str]] = []
    out_seen: set[tuple[str, str]] = set()
    for _off, platform, handle in candidates:
        key = (platform, handle.lower())
        if key in out_seen:
            continue
        out_seen.add(key)
        out.append({"platform": platform, "handle": handle})
        if len(out) >= _MAX_SOCIAL:
            break
    return out


__all__ = ["extract_social"]
