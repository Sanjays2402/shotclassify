"""Cross-category color-value extractor.

Design captures (Figma / Sketch screenshots), CSS / Tailwind /
SCSS code, design-system docs, Brand-style guides, and many UI
mockups reference colours in machine-readable form. We surface
every recognised colour into ``ExtractedFields.raw["colors"]``
as a list of ``{"model": str, "value": str}`` dicts where
``model`` is the colour space tag and ``value`` is the canonical
string form.

Recognised models:

* ``hex``    -- ``#FF5733`` / ``#fa3`` / ``#FF5733AA`` (alpha)
                / ``0xFF5733``. Canonicalised to lowercase
                ``#xxxxxx`` (or ``#xxxxxxxx`` when alpha is
                present). Short 3-digit form is expanded.
* ``rgb``    -- ``rgb(255, 87, 51)`` / ``rgb(255 87 51)`` (space-
                separated CSS-4 form) / ``rgba(255,87,51,0.5)``.
* ``hsl``    -- ``hsl(11, 100%, 60%)`` / ``hsl(11 100% 60%)`` /
                ``hsla(11, 100%, 60%, 0.5)``.
* ``hsv``    -- ``hsv(11, 80%, 100%)`` -- non-CSS but common in
                design tools.
* ``oklch``  -- ``oklch(0.8 0.1 30)`` -- modern CSS-4 perceptual
                colour space.
* ``oklab``  -- ``oklab(0.8 0.1 0.05)`` -- CSS-4 perceptual.
* ``lab``    -- ``lab(50% 40 30)``.
* ``lch``    -- ``lch(50% 40 30)``.
* ``named``  -- one of the curated CSS named colours
                (``rebeccapurple``, ``coral``, ``cornflowerblue``,
                etc -- ~50 distinctive colour names with low
                false-positive risk; common dictionary words
                like ``red``, ``blue``, ``green``, ``black``,
                ``white``, ``yellow`` are intentionally EXCLUDED
                from the catalogue because they appear in prose
                far too often).

Safety:

* Hex matcher requires either a ``#`` or ``0x`` prefix so a
  bare ``FF5733`` hex (which could be anything -- a hash, a
  token, an ID) does NOT misfire.
* All function-form matchers require the function name (``rgb``,
  ``hsl``, etc) followed by ``(`` so a sentence ``hsl values``
  doesn't fire.
* Named-colour matching enforces word boundaries on both ends
  and uses a CURATED catalogue (~50 distinctive names) so
  prose words like ``red`` / ``blue`` / ``green`` / ``black``
  don't false-positive.
* Cap 100 entries.
* Dedup on (model, canonical-value) so the same colour printed
  via different formats stays distinct (#FF5733 vs rgb(255,87,51)
  are TWO entries because dashboards care about which form the
  source used).

Useful for design-system tooling, brand-consistency dashboards,
accessibility audits (contrast checking), and theme-extraction
from screenshots.
"""
from __future__ import annotations

import re

_MAX_COLORS = 100

# Hex with mandatory # or 0x prefix. 3, 4, 6, or 8 hex chars.
# Word-boundary on both ends to keep us from biting into longer
# alphanumeric runs.
_HEX_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<prefix>#|0x)(?P<digits>[0-9a-fA-F]+)(?![A-Za-z0-9_])"
)

# rgb() / rgba() function form. Numbers can be integers (0..255) or
# floats. Separator can be comma OR space (CSS-4 syntax). The
# optional alpha component is at the end.
_RGB_RE = re.compile(
    r"\brgba?\s*\(\s*"
    r"(?P<r>\d{1,3}(?:\.\d+)?)\s*[,\s]\s*"
    r"(?P<g>\d{1,3}(?:\.\d+)?)\s*[,\s]\s*"
    r"(?P<b>\d{1,3}(?:\.\d+)?)"
    r"(?:\s*[,/]\s*(?P<a>\d*\.?\d+%?))?"
    r"\s*\)",
    re.IGNORECASE,
)

# hsl() / hsla() function form. Percent symbol required on
# saturation and lightness per CSS spec; comma or space separators
# accepted.
_HSL_RE = re.compile(
    r"\bhsla?\s*\(\s*"
    r"(?P<h>-?\d+(?:\.\d+)?(?:deg|rad|turn|grad)?)\s*[,\s]\s*"
    r"(?P<s>\d+(?:\.\d+)?%)\s*[,\s]\s*"
    r"(?P<l>\d+(?:\.\d+)?%)"
    r"(?:\s*[,/]\s*(?P<a>\d*\.?\d+%?))?"
    r"\s*\)",
    re.IGNORECASE,
)

# hsv() function form (non-CSS, common in design tools).
_HSV_RE = re.compile(
    r"\bhsv\s*\(\s*"
    r"(?P<h>-?\d+(?:\.\d+)?(?:deg|rad|turn|grad)?)\s*[,\s]\s*"
    r"(?P<s>\d+(?:\.\d+)?%?)\s*[,\s]\s*"
    r"(?P<v>\d+(?:\.\d+)?%?)"
    r"\s*\)",
    re.IGNORECASE,
)

# oklch() / oklab() / lab() / lch() function forms (CSS-4
# perceptual colour spaces). Loose number matching because these
# accept percentages, dimensions, or bare floats.
_PERCEPTUAL_RE = re.compile(
    r"\b(?P<model>oklch|oklab|lab|lch)\s*\(\s*"
    r"(?P<args>[^\)]+?)\s*\)",
    re.IGNORECASE,
)

# CSS named colours -- intentionally CURATED to avoid prose
# false-positives. Common dictionary words (red/blue/green/black/
# white/yellow/grey/gray) are EXCLUDED because they appear far
# too often in prose. We keep colours that are visually
# distinctive AND lexically distinctive (rebeccapurple, coral,
# orchid, fuchsia, etc.).
_NAMED_COLORS: frozenset[str] = frozenset({
    "aliceblue",
    "aqua",
    "aquamarine",
    "azure",
    "beige",
    "bisque",
    "blanchedalmond",
    "blueviolet",
    "burlywood",
    "cadetblue",
    "chartreuse",
    "chocolate",
    "coral",
    "cornflowerblue",
    "cornsilk",
    "crimson",
    "cyan",
    "darkcyan",
    "darkgoldenrod",
    "darkkhaki",
    "darkmagenta",
    "darkolivegreen",
    "darkorange",
    "darkorchid",
    "darksalmon",
    "darkseagreen",
    "darkslategray",
    "darkturquoise",
    "darkviolet",
    "deeppink",
    "deepskyblue",
    "dodgerblue",
    "firebrick",
    "floralwhite",
    "forestgreen",
    "fuchsia",
    "gainsboro",
    "ghostwhite",
    "goldenrod",
    "honeydew",
    "hotpink",
    "indianred",
    "indigo",
    "khaki",
    "lavender",
    "lavenderblush",
    "lawngreen",
    "lemonchiffon",
    "lightcoral",
    "lightcyan",
    "lightgoldenrodyellow",
    "lightpink",
    "lightsalmon",
    "lightseagreen",
    "lightskyblue",
    "lightslategray",
    "lightsteelblue",
    "limegreen",
    "linen",
    "magenta",
    "mediumaquamarine",
    "mediumorchid",
    "mediumpurple",
    "mediumseagreen",
    "mediumslateblue",
    "mediumspringgreen",
    "mediumturquoise",
    "mediumvioletred",
    "midnightblue",
    "mintcream",
    "mistyrose",
    "moccasin",
    "navajowhite",
    "oldlace",
    "olivedrab",
    "orangered",
    "orchid",
    "palegoldenrod",
    "palegreen",
    "paleturquoise",
    "palevioletred",
    "papayawhip",
    "peachpuff",
    "periwinkle",
    "peru",
    "powderblue",
    "rebeccapurple",
    "rosybrown",
    "royalblue",
    "saddlebrown",
    "salmon",
    "sandybrown",
    "seagreen",
    "seashell",
    "sienna",
    "skyblue",
    "slateblue",
    "slategray",
    "snow",
    "springgreen",
    "steelblue",
    "tan",
    "teal",
    "thistle",
    "tomato",
    "turquoise",
    "violet",
    "wheat",
    "whitesmoke",
    "yellowgreen",
})

# Curated-named-colour regex. Word-boundary on both sides; the
# alternation is built from the catalogue (longest-first so
# ``mediumaquamarine`` beats ``aquamarine``).
_NAMED_RE = re.compile(
    r"\b(?P<name>" + "|".join(sorted(_NAMED_COLORS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _canonicalise_hex(digits: str) -> str:
    """Expand short hex (#abc / #abcd) to long form and lowercase."""
    digits = digits.lower()
    if len(digits) == 3:
        # #abc -> #aabbcc
        return "#" + "".join(c * 2 for c in digits)
    if len(digits) == 4:
        # #abcd -> #aabbccdd
        return "#" + "".join(c * 2 for c in digits)
    if len(digits) in (6, 8):
        return "#" + digits
    return ""


def _format_rgb(r: str, g: str, b: str, a: str | None) -> str:
    """Format an rgb tuple back to canonical CSS form."""
    if a:
        return f"rgba({r}, {g}, {b}, {a.rstrip('%')})"
    return f"rgb({r}, {g}, {b})"


def _format_hsl(h: str, s: str, lightness: str, a: str | None) -> str:
    """Format an hsl tuple back to canonical CSS form."""
    if a:
        return f"hsla({h}, {s}, {lightness}, {a.rstrip('%')})"
    return f"hsl({h}, {s}, {lightness})"


def extract_colors(text: str) -> list[dict[str, str]]:
    """Return list of detected colour values in source-text order.

    Each entry is a ``{"model": str, "value": str}`` dict where
    ``model`` is one of: ``hex`` / ``rgb`` / ``hsl`` / ``hsv`` /
    ``oklch`` / ``oklab`` / ``lab`` / ``lch`` / ``named``.

    ``value`` is the canonical string form:

    * Hex: ``#xxxxxx`` (or ``#xxxxxxxx`` with alpha) lowercased.
      Short 3- and 4-digit forms expanded to long form.
    * Function forms: re-rendered with ``,`` separators and the
      explicit ``rgba`` / ``hsla`` function name when alpha is
      present.
    * Perceptual (oklch/oklab/lab/lch): preserved verbatim from
      source so ``oklch(0.8 0.1 30)`` and ``lab(50% 40 30)`` keep
      their author-intended units.
    * Named: lowercased from catalogue.

    De-duped on (model, value) pair so the same colour written
    twice in identical form collapses, but the same colour
    written in DIFFERENT forms (#FF5733 vs rgb(255,87,51))
    stays as TWO entries because dashboards care about which
    form the source used.

    Capped at 100 entries.
    """
    if not text or not isinstance(text, str):
        return []

    # Each tuple: (offset, model, value).
    hits: list[tuple[int, str, str]] = []
    claimed: list[tuple[int, int]] = []  # (start, end) spans

    def _is_claimed(start: int, end: int) -> bool:
        for cs, ce in claimed:
            if not (end <= cs or start >= ce):
                return True
        return False

    # Walk function-form matchers FIRST so a hex inside an rgb()
    # call doesn't double-tag (we don't actually accept hex inside
    # rgb but it's defensive to claim early).

    # rgb() / rgba()
    for m in _RGB_RE.finditer(text):
        r, g, b = m.group("r"), m.group("g"), m.group("b")
        a = m.group("a")
        # Sanity: each channel must be 0..255 for ints, 0..100% if
        # percent (we don't accept percent here -- CSS allows it
        # but we keep it tight). Floats are accepted because some
        # design tools emit fractional values.
        try:
            for ch in (r, g, b):
                v = float(ch)
                if v < 0 or v > 255:
                    raise ValueError
        except ValueError:
            continue
        value = _format_rgb(r, g, b, a)
        hits.append((m.start(), "rgb", value))
        claimed.append((m.start(), m.end()))

    # hsl() / hsla()
    for m in _HSL_RE.finditer(text):
        h, s, lt = m.group("h"), m.group("s"), m.group("l")
        a = m.group("a")
        value = _format_hsl(h, s, lt, a)
        hits.append((m.start(), "hsl", value))
        claimed.append((m.start(), m.end()))

    # hsv() (non-CSS but common in design tools)
    for m in _HSV_RE.finditer(text):
        h, s, v = m.group("h"), m.group("s"), m.group("v")
        value = f"hsv({h}, {s}, {v})"
        hits.append((m.start(), "hsv", value))
        claimed.append((m.start(), m.end()))

    # Perceptual: oklch / oklab / lab / lch
    for m in _PERCEPTUAL_RE.finditer(text):
        model = m.group("model").lower()
        args = m.group("args").strip()
        # Normalise internal whitespace for stable storage.
        args = re.sub(r"\s+", " ", args)
        value = f"{model}({args})"
        hits.append((m.start(), model, value))
        claimed.append((m.start(), m.end()))

    # Hex matcher AFTER function-form so a hex inside ``rgba(0x00,
    # 0x80, 0xff)`` (unusual but possible) doesn't both tag as
    # rgb AND as three hex entries. The claim-set guards this.
    for m in _HEX_RE.finditer(text):
        if _is_claimed(m.start(), m.end()):
            continue
        digits = m.group("digits")
        if len(digits) not in (3, 4, 6, 8):
            continue
        value = _canonicalise_hex(digits)
        if not value:
            continue
        hits.append((m.start(), "hex", value))
        claimed.append((m.start(), m.end()))

    # Named-colour matcher LAST because it's the most likely
    # source of prose false-positives (the catalogue is tight but
    # we still want function-form hits to win when overlapping).
    for m in _NAMED_RE.finditer(text):
        if _is_claimed(m.start(), m.end()):
            continue
        value = m.group("name").lower()
        hits.append((m.start(), "named", value))
        claimed.append((m.start(), m.end()))

    # Sort by source-text offset for top-to-bottom appearance order.
    hits.sort(key=lambda triple: triple[0])

    # Dedup on (model, value) pair while preserving first-seen order.
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for _, model, value in hits:
        key = (model, value)
        if key in seen:
            continue
        seen.add(key)
        out.append({"model": model, "value": value})
        if len(out) >= _MAX_COLORS:
            break
    return out


__all__ = ["extract_colors"]
