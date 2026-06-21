"""Cross-category social-handle extractor.

Social-media handles surface across every category of screenshot --
chat captures share creators' Twitter handles, code snippets paste
GitHub repo links, document captures cite LinkedIn profiles, error
logs reference upstream repos, receipts print the merchant's
Instagram handle. We surface them under ``raw["social"]`` as a list
of ``{"platform", "handle"}`` dicts.

Recognised forms:

* Twitter / X: ``twitter.com/jack`` / ``x.com/jack`` / ``@jack`` with
  a Twitter anchor on the same line.
* GitHub: ``github.com/torvalds`` (user) / ``github.com/torvalds/linux``
  (user/repo as ``user/repo``).
* LinkedIn: ``linkedin.com/in/<slug>`` / ``linkedin.com/company/<slug>``.
* Instagram: ``instagram.com/natgeo`` / ``@natgeo`` with Insta anchor.
* TikTok: ``tiktok.com/@khaby.lame``.
* YouTube: ``youtube.com/@mkbhd`` / ``youtube.com/c/<slug>`` /
  ``youtube.com/user/<slug>``.
* Reddit: ``reddit.com/r/<sub>`` / ``reddit.com/u/<user>``.
* Mastodon: ``@user@instance.tld``.

De-duplicated on (platform, handle.lower()) pair; first-seen-in-text
order preserved; capped at 50.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_social

# ---- edge cases --------------------------------------------------


def test_empty_string_returns_empty_list():
    assert extract_social("") == []


def test_whitespace_only_returns_empty_list():
    assert extract_social("   \n\n  ") == []


def test_plain_prose_no_handles_returns_empty_list():
    assert extract_social("Just plain English with no links.") == []


# ---- Twitter / X URL forms ---------------------------------------


def test_twitter_url_basic():
    out = extract_social("Follow https://twitter.com/jack for updates")
    assert {"platform": "twitter", "handle": "jack"} in out


def test_twitter_x_com_url():
    out = extract_social("https://x.com/jack")
    assert {"platform": "twitter", "handle": "jack"} in out


def test_twitter_url_without_scheme():
    out = extract_social("twitter.com/jack")
    assert {"platform": "twitter", "handle": "jack"} in out


def test_twitter_url_with_www():
    out = extract_social("https://www.twitter.com/jack")
    assert {"platform": "twitter", "handle": "jack"} in out


def test_twitter_url_with_status_path():
    out = extract_social("https://twitter.com/jack/status/12345")
    assert {"platform": "twitter", "handle": "jack"} in out


def test_twitter_reserved_path_rejected():
    """``twitter.com/login`` is not a handle."""
    out = extract_social("https://twitter.com/login")
    twitter_handles = [e for e in out if e["platform"] == "twitter"]
    assert twitter_handles == []


def test_twitter_handle_with_underscores():
    out = extract_social("https://twitter.com/the_real_jack")
    assert {"platform": "twitter", "handle": "the_real_jack"} in out


# ---- Twitter @handle with anchor ---------------------------------


def test_twitter_at_handle_with_twitter_anchor():
    out = extract_social("Twitter: @jack")
    assert {"platform": "twitter", "handle": "jack"} in out


def test_twitter_at_handle_with_follow_anchor():
    out = extract_social("Follow me on X at @jack")
    assert {"platform": "twitter", "handle": "jack"} in out


def test_twitter_at_handle_without_anchor_not_captured():
    """Bare ``@jack`` with no Twitter context is ignored."""
    out = extract_social("@jack said hi")
    twitter = [e for e in out if e["platform"] == "twitter"]
    assert twitter == []


# ---- GitHub URL forms --------------------------------------------


def test_github_user_url():
    out = extract_social("github.com/torvalds")
    assert {"platform": "github", "handle": "torvalds"} in out


def test_github_user_repo_url():
    out = extract_social("https://github.com/torvalds/linux")
    assert {"platform": "github", "handle": "torvalds/linux"} in out


def test_github_url_with_path_tail():
    """A trailing ``/blob/main/README.md`` doesn't poison the user/repo."""
    out = extract_social("https://github.com/torvalds/linux/blob/main/README.md")
    assert {"platform": "github", "handle": "torvalds/linux"} in out


def test_github_reserved_paths_rejected():
    """``github.com/login`` and ``github.com/marketplace`` are not users."""
    for path in ("login", "marketplace", "explore", "topics", "pricing"):
        out = extract_social(f"https://github.com/{path}")
        github = [e for e in out if e["platform"] == "github"]
        assert github == [], f"path={path}"


def test_github_user_with_hyphens_and_digits():
    out = extract_social("github.com/foo-bar-123")
    assert {"platform": "github", "handle": "foo-bar-123"} in out


# ---- LinkedIn URL forms ------------------------------------------


def test_linkedin_personal_profile():
    out = extract_social("linkedin.com/in/satya-nadella")
    assert {"platform": "linkedin", "handle": "satya-nadella"} in out


def test_linkedin_company_page():
    out = extract_social("linkedin.com/company/microsoft")
    assert {"platform": "linkedin", "handle": "company/microsoft"} in out


def test_linkedin_school_page():
    out = extract_social("linkedin.com/school/stanford-university")
    assert {"platform": "linkedin", "handle": "school/stanford-university"} in out


def test_linkedin_country_subdomain():
    """``uk.linkedin.com/in/...`` is recognised."""
    out = extract_social("https://uk.linkedin.com/in/alice-author")
    assert {"platform": "linkedin", "handle": "alice-author"} in out


# ---- Instagram URL forms -----------------------------------------


def test_instagram_url():
    out = extract_social("instagram.com/natgeo")
    assert {"platform": "instagram", "handle": "natgeo"} in out


def test_instagram_url_with_period_in_handle():
    out = extract_social("instagram.com/the.rock")
    assert {"platform": "instagram", "handle": "the.rock"} in out


def test_instagram_reserved_paths_rejected():
    """``instagram.com/p/<post>`` is a post, not a handle."""
    out = extract_social("instagram.com/p/ABC123")
    insta = [e for e in out if e["platform"] == "instagram"]
    assert insta == []


def test_instagram_reel_rejected():
    out = extract_social("instagram.com/reel/XYZ789")
    insta = [e for e in out if e["platform"] == "instagram"]
    assert insta == []


def test_instagram_at_handle_with_insta_anchor():
    out = extract_social("Insta @natgeo")
    assert {"platform": "instagram", "handle": "natgeo"} in out


# ---- TikTok URL forms --------------------------------------------


def test_tiktok_url():
    out = extract_social("tiktok.com/@khaby.lame")
    assert {"platform": "tiktok", "handle": "khaby.lame"} in out


def test_tiktok_url_with_www():
    out = extract_social("https://www.tiktok.com/@khaby.lame")
    assert {"platform": "tiktok", "handle": "khaby.lame"} in out


# ---- YouTube URL forms -------------------------------------------


def test_youtube_handle_url():
    out = extract_social("youtube.com/@mkbhd")
    assert {"platform": "youtube", "handle": "mkbhd"} in out


def test_youtube_channel_slug():
    out = extract_social("youtube.com/c/mkbhd")
    assert {"platform": "youtube", "handle": "mkbhd"} in out


def test_youtube_legacy_user():
    out = extract_social("youtube.com/user/marquesbrownlee")
    assert {"platform": "youtube", "handle": "marquesbrownlee"} in out


# ---- Reddit URL forms --------------------------------------------


def test_reddit_subreddit():
    out = extract_social("reddit.com/r/programming")
    assert {"platform": "reddit", "handle": "r/programming"} in out


def test_reddit_user_short():
    out = extract_social("reddit.com/u/spez")
    assert {"platform": "reddit", "handle": "u/spez"} in out


def test_reddit_user_long():
    """``/user/<name>`` canonicalises to ``u/<name>``."""
    out = extract_social("reddit.com/user/spez")
    assert {"platform": "reddit", "handle": "u/spez"} in out


def test_reddit_old_subdomain():
    out = extract_social("old.reddit.com/r/python")
    assert {"platform": "reddit", "handle": "r/python"} in out


# ---- Mastodon ----------------------------------------------------


def test_mastodon_handle():
    out = extract_social("Reach me at @gargron@mastodon.social for updates")
    assert {"platform": "mastodon", "handle": "@gargron@mastodon.social"} in out


def test_mastodon_handle_uppercase_instance():
    out = extract_social("Contact @user@Example.Social")
    assert any(e["platform"] == "mastodon" for e in out)


def test_mastodon_handle_with_subdomain():
    out = extract_social("@alice@fosstodon.org said hi")
    assert {"platform": "mastodon", "handle": "@alice@fosstodon.org"} in out


# ---- mixed and ordering ------------------------------------------


def test_multiple_platforms_one_text():
    text = (
        "Find me on:\n"
        "Twitter: twitter.com/jack\n"
        "GitHub: github.com/torvalds\n"
        "LinkedIn: linkedin.com/in/satya-nadella\n"
    )
    out = extract_social(text)
    platforms = sorted({e["platform"] for e in out})
    assert "twitter" in platforms
    assert "github" in platforms
    assert "linkedin" in platforms


def test_dedup_same_handle_same_platform():
    text = "twitter.com/jack and twitter.com/jack"
    out = extract_social(text)
    twitter = [e for e in out if e["platform"] == "twitter" and e["handle"] == "jack"]
    assert len(twitter) == 1


def test_dedup_case_insensitive_on_handle():
    """Handle compared case-insensitively for dedupe."""
    text = "twitter.com/Jack and twitter.com/jack"
    out = extract_social(text)
    twitter = [e for e in out if e["platform"] == "twitter"]
    assert len(twitter) == 1


def test_first_seen_order_preserved():
    text = "github.com/c then twitter.com/b then x.com/a"
    out = extract_social(text)
    # The matchers run in priority order (twitter first, then github),
    # but final ordering is by source-text offset.
    assert out[0]["handle"] == "c"
    assert out[1]["handle"] == "b"
    assert out[2]["handle"] == "a"


def test_cap_at_50_entries():
    text = " ".join([f"github.com/user{i}" for i in range(60)])
    out = extract_social(text)
    assert len(out) == 50


# ---- output shape ------------------------------------------------


def test_output_shape_per_entry():
    out = extract_social("github.com/torvalds")
    assert out == [{"platform": "github", "handle": "torvalds"}]


# ---- pipeline integration ----------------------------------------


def test_pipeline_stashes_social_under_raw():
    text = "github.com/torvalds/linux issue tracker"
    ocr = OCRResult(text=text, language="en", word_count=len(text.split()))
    fields = ExtractedFields()
    out = enrich(Category.document, fields, ocr)
    assert "social" in out.raw
    assert {"platform": "github", "handle": "torvalds/linux"} in out.raw["social"]


def test_pipeline_omits_raw_social_when_none_found():
    text = "Just plain text with no handles."
    ocr = OCRResult(text=text, language="en", word_count=len(text.split()))
    fields = ExtractedFields()
    out = enrich(Category.document, fields, ocr)
    assert "social" not in (out.raw or {})


def test_pipeline_works_across_categories():
    text = "Following github.com/torvalds"
    ocr = OCRResult(text=text, language="en", word_count=len(text.split()))
    for cat in (Category.chat_screenshot, Category.error_stacktrace, Category.code_snippet):
        fields = ExtractedFields()
        out = enrich(cat, fields, ocr)
        assert "social" in out.raw


# ---- corner cases -------------------------------------------------


def test_twitter_url_inside_sentence():
    """URL embedded in prose with trailing punctuation extracts cleanly."""
    out = extract_social("Reach out to twitter.com/jack, he's great.")
    assert {"platform": "twitter", "handle": "jack"} in out


def test_twitter_handle_15_chars():
    """Twitter's 15-char max is enforced."""
    out = extract_social("twitter.com/abcdefghijklmno")  # 15 chars
    assert {"platform": "twitter", "handle": "abcdefghijklmno"} in out


def test_github_repo_with_dots_and_hyphens():
    out = extract_social("github.com/foo/bar.baz-qux_quux")
    assert {"platform": "github", "handle": "foo/bar.baz-qux_quux"} in out


def test_youtube_handle_with_dash():
    out = extract_social("youtube.com/@mkbhd-tech")
    assert {"platform": "youtube", "handle": "mkbhd-tech"} in out


def test_email_address_not_misidentified_as_mastodon():
    """``alice@example.com`` is NOT a mastodon handle (only one ``@``)."""
    out = extract_social("Contact alice@example.com")
    mastodon = [e for e in out if e["platform"] == "mastodon"]
    assert mastodon == []
