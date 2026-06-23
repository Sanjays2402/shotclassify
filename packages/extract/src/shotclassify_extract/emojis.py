"""Cross-category emoji extractor.

Tally every distinct emoji codepoint with its count in the OCR
text. Surfaces under ``ExtractedFields.raw["emojis"]`` as a list
of ``{"emoji", "codepoint", "count"}`` dicts. Useful for meme-
format dashboards, sentiment monitoring (lots of 😡 vs lots of
🎉), and detecting reaction-heavy chats.

Output shape:
    [
      {"emoji": "🎉", "codepoint": "U+1F389", "count": 5},
      {"emoji": "❤️", "codepoint": "U+2764 U+FE0F", "count": 3},
      {"emoji": "👍", "codepoint": "U+1F44D", "count": 2},
    ]

Sorted by descending count, then by first-seen-order on ties so
dashboards render most-used-first deterministically. Capped at
50 distinct entries.

Detected codepoint ranges (covers the vast majority of Unicode
emoji in real OCR captures):

* Miscellaneous Symbols and Pictographs (U+1F300..U+1F5FF)
* Emoticons (U+1F600..U+1F64F)
* Transport and Map Symbols (U+1F680..U+1F6FF)
* Geometric Shapes Extended (U+1F780..U+1F7FF) -- some shapes
* Supplemental Symbols and Pictographs (U+1F900..U+1F9FF)
* Symbols and Pictographs Extended-A (U+1FA70..U+1FAFF)
* Miscellaneous Symbols (U+2600..U+26FF) -- some shapes
* Dingbats (U+2700..U+27BF) -- some shapes
* Enclosed Alphanumerics (U+1F100..U+1F1FF) -- regional
  indicator pairs for flags
* Variation selectors U+FE0E / U+FE0F (combined with the
  preceding base char)
* Zero-Width Joiner U+200D (combined into ZWJ sequences:
  family / professions / multi-component emoji)

Compound emoji (👨‍👩‍👧‍👦, 🏳️‍🌈, 👨🏻‍💻) are kept as one
unit when they're built with ZWJ sequences. Skin-tone modifiers
(U+1F3FB..U+1F3FF) are combined with the preceding face/hand
emoji to preserve the modifier semantics.

What's intentionally NOT captured:

* Plain text symbols like ©, ®, ™, → because those are too
  often used in non-emoji contexts (copyright headers, math
  expressions, prose).
* Box-drawing chars (U+2500..U+257F).
* Currency symbols ($, €, £, ¥) -- handled by the amounts
  extractor.

Distinct from raw[\"chat\"].reactions which is per-message
reaction footers; this extractor is text-density tally across
the WHOLE OCR capture.
"""
from __future__ import annotations

# Unicode ranges that count as emoji for our purposes. Tuned
# conservatively to avoid false-positives on math / typography
# symbols. The base range catalogue:
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    # Miscellaneous Symbols (sun, hearts, peace sign, etc.).
    # We pick a subset that's commonly used as emoji vs the
    # bare typographic chars.
    (0x2600, 0x26FF),
    # Dingbats (snowflake, scissors, sparkles, etc.).
    (0x2700, 0x27BF),
    # Supplemental arrows that are commonly used as decorative
    # arrows in chats (e.g. ↪️ U+21AA forward-reply).
    (0x21AA, 0x21AB),  # left/right hooked arrows
    # Enclosed Alphanumeric Supplement -- includes regional
    # indicators U+1F1E6..U+1F1FF used for flags.
    (0x1F1E0, 0x1F1FF),
    # Miscellaneous Symbols and Pictographs (the big emoji block).
    (0x1F300, 0x1F5FF),
    # Emoticons.
    (0x1F600, 0x1F64F),
    # Transport and Map Symbols.
    (0x1F680, 0x1F6FF),
    # Geometric Shapes Extended -- coloured circles / squares
    # (🟢🟡🔴🟠🟣🟤🟦🟧🟨🟩🟪🟫🟥) commonly used as status
    # indicators and reaction badges.
    (0x1F7E0, 0x1F7FF),
    # Supplemental Symbols and Pictographs.
    (0x1F900, 0x1F9FF),
    # Symbols and Pictographs Extended-A.
    (0x1FA70, 0x1FAFF),
)

# Variation selectors that modify the preceding emoji's
# presentation (text vs emoji style).
_VARIATION_SELECTORS: frozenset[int] = frozenset({0xFE0E, 0xFE0F})

# Skin-tone modifiers attach to a preceding hand / face emoji.
_SKIN_TONES: tuple[int, int] = (0x1F3FB, 0x1F3FF)  # inclusive

# Zero-Width Joiner combines emoji into compound sequences
# (family, professions, etc.).
_ZWJ: int = 0x200D


def _is_base_emoji(cp: int) -> bool:
    """Return True if codepoint sits in a recognised emoji range."""
    for lo, hi in _EMOJI_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def _is_skin_tone(cp: int) -> bool:
    return _SKIN_TONES[0] <= cp <= _SKIN_TONES[1]


def _format_codepoints(cps: list[int]) -> str:
    """Format a list of codepoints as ``U+XXXX U+YYYY``."""
    return " ".join(f"U+{cp:04X}" for cp in cps)


_MAX_EMOJI_ENTRIES = 50


def extract_emojis(text: str) -> list[dict[str, object]]:
    """Return tallied emojis found in ``text``.

    Walks the text codepoint-by-codepoint. When a base-emoji
    codepoint is found, we look ahead for ZWJ sequences and
    skin-tone / variation-selector modifiers and group them as
    one logical emoji unit.

    Output is sorted by descending count (most common first),
    then by first-seen-order on ties. Each entry has:

    * ``emoji``     -- the rendered string form (one logical
                       emoji character or compound)
    * ``codepoint`` -- the codepoints in ``U+XXXX[ U+YYYY ...]``
                       form (multiple for ZWJ / skin-tone /
                       variation-selector compounds)
    * ``count``     -- how many times this distinct emoji
                       appeared in the text

    Capped at 50 distinct emoji.
    """
    if not text or not isinstance(text, str):
        return []

    # Walk char-by-char gathering emoji units.
    units: list[tuple[str, str]] = []  # (rendered, codepoint-string)
    i = 0
    n = len(text)
    while i < n:
        cp = ord(text[i])
        if not _is_base_emoji(cp):
            i += 1
            continue
        # Found a base emoji. Collect the unit (base + any
        # following modifiers / ZWJ continuations).
        cps: list[int] = [cp]
        chars: list[str] = [text[i]]
        j = i + 1
        while j < n:
            ncp = ord(text[j])
            # Variation selector glues to preceding emoji.
            if ncp in _VARIATION_SELECTORS:
                cps.append(ncp)
                chars.append(text[j])
                j += 1
                continue
            # Skin-tone modifier glues to preceding emoji.
            if _is_skin_tone(ncp):
                cps.append(ncp)
                chars.append(text[j])
                j += 1
                continue
            # ZWJ + next base emoji is a compound sequence.
            if ncp == _ZWJ and j + 1 < n:
                next_cp = ord(text[j + 1])
                if _is_base_emoji(next_cp):
                    cps.append(ncp)
                    chars.append(text[j])
                    cps.append(next_cp)
                    chars.append(text[j + 1])
                    j += 2
                    continue
            break
        units.append(("".join(chars), _format_codepoints(cps)))
        i = j

    if not units:
        return []

    # Tally distinct units while preserving first-seen order on
    # tie-breaks (Python 3.7+ dict ordering is insertion-order).
    counts: dict[str, int] = {}
    rendered_for_codepoint: dict[str, str] = {}
    first_seen: dict[str, int] = {}
    seen_order = 0
    for rendered, codepoint in units:
        if codepoint not in counts:
            counts[codepoint] = 0
            rendered_for_codepoint[codepoint] = rendered
            first_seen[codepoint] = seen_order
            seen_order += 1
        counts[codepoint] += 1

    # Sort by descending count, then by first-seen-order ascending.
    ordered_keys = sorted(
        counts.keys(),
        key=lambda k: (-counts[k], first_seen[k]),
    )

    out: list[dict[str, object]] = []
    for k in ordered_keys[:_MAX_EMOJI_ENTRIES]:
        out.append({
            "emoji": rendered_for_codepoint[k],
            "codepoint": k,
            "count": counts[k],
        })
    return out


__all__ = ["extract_emojis"]
