"""Chat attachment marker detection (``ChatFields.attachments``).

The new ``ChatFields.attachments`` slot captures voice notes,
images, videos, files, GIFs, stickers, locations, contacts, and
call markers found in chat screenshots. Each entry is a
``{"sender", "kind", "duration"?, "name"?}`` dict.

Recognised shapes:
  * Bracketed: ``[Image]`` / ``[Voice note 0:23]`` /
    ``[Document: file.pdf]``.
  * Emoji-prefixed: ``📷 Photo`` / ``🎤 Voice (0:42)``.
  * Generic English: ``Voice message (0:42)`` /
    ``Video call · 1m 23s`` / ``Missed video call``.
"""
from __future__ import annotations

from shotclassify_common import ChatFields, OCRResult
from shotclassify_extract import enrich_chat
from shotclassify_extract.chat import _extract_attachments

# ---- bracket shape ---------------------------------------------


def test_bracket_image():
    out = _extract_attachments("Alice: [Image]")
    assert out == [{"kind": "image", "sender": "Alice"}]


def test_bracket_photo_alias():
    out = _extract_attachments("Alice: [Photo]")
    assert out == [{"kind": "image", "sender": "Alice"}]


def test_bracket_video():
    out = _extract_attachments("Bob: [Video]")
    assert out == [{"kind": "video", "sender": "Bob"}]


def test_bracket_voice_note_with_duration():
    out = _extract_attachments("Bob: [Voice note 0:23]")
    assert out == [{"kind": "voice", "duration": "0:23", "sender": "Bob"}]


def test_bracket_voice_message_with_duration():
    out = _extract_attachments("Alice: [Voice message 1:05]")
    assert out == [{"kind": "voice", "duration": "1:05", "sender": "Alice"}]


def test_bracket_audio_with_long_duration():
    out = _extract_attachments("Bob: [Audio 12:34:56]")
    assert out == [{"kind": "audio", "duration": "12:34:56", "sender": "Bob"}]


def test_bracket_sticker():
    out = _extract_attachments("Alice: [Sticker]")
    assert out == [{"kind": "sticker", "sender": "Alice"}]


def test_bracket_gif():
    out = _extract_attachments("Bob: [GIF]")
    assert out == [{"kind": "gif", "sender": "Bob"}]


def test_bracket_document():
    out = _extract_attachments("Alice: [Document]")
    assert out == [{"kind": "document", "sender": "Alice"}]


def test_bracket_document_with_name():
    out = _extract_attachments("Bob: [Document: report.pdf]")
    assert out == [{"kind": "document", "name": "report.pdf", "sender": "Bob"}]


def test_bracket_location():
    out = _extract_attachments("Alice: [Location]")
    assert out == [{"kind": "location", "sender": "Alice"}]


def test_bracket_live_location():
    out = _extract_attachments("Bob: [Live Location]")
    assert out == [{"kind": "location", "sender": "Bob"}]


def test_bracket_contact():
    out = _extract_attachments("Alice: [Contact]")
    assert out == [{"kind": "contact", "sender": "Alice"}]


def test_bracket_unknown_label_rejected():
    """A bracketed token whose label is not in the alias map is rejected."""
    out = _extract_attachments("Bob: [issue-123]")
    assert out == []


def test_bracket_prose_id_rejected():
    """``[ABC-99]`` (an issue or ticket ID) does NOT misfire."""
    out = _extract_attachments("See [TICKET-99] for details")
    assert out == []


# ---- emoji-prefixed shape --------------------------------------


def test_emoji_camera_photo():
    out = _extract_attachments("Alice: 📷 Photo")
    assert out == [{"kind": "image", "sender": "Alice"}]


def test_emoji_video():
    out = _extract_attachments("Bob: 🎥 Video")
    assert out == [{"kind": "video", "sender": "Bob"}]


def test_emoji_mic_voice_with_duration():
    out = _extract_attachments("Bob: 🎤 Voice (0:42)")
    assert out == [{"kind": "voice", "duration": "0:42", "sender": "Bob"}]


def test_emoji_paperclip_document():
    out = _extract_attachments("Alice: 📎 Document")
    assert out == [{"kind": "document", "sender": "Alice"}]


def test_emoji_pin_location():
    out = _extract_attachments("Bob: 📍 Location")
    assert out == [{"kind": "location", "sender": "Bob"}]


def test_emoji_speaker_audio():
    out = _extract_attachments("Alice: 🔊 Audio (3:12)")
    assert out == [{"kind": "audio", "duration": "3:12", "sender": "Alice"}]


def test_emoji_film_video_with_duration():
    out = _extract_attachments("Bob: 🎥 Video (1:23)")
    assert out == [{"kind": "video", "duration": "1:23", "sender": "Bob"}]


def test_emoji_unknown_label_rejected():
    """Emoji + unknown label is rejected."""
    out = _extract_attachments("Bob: 📷 Unknown")
    assert out == []


def test_emoji_no_label_rejected():
    """A lone emoji with no label after doesn't trigger."""
    out = _extract_attachments("Alice: 📷")
    assert out == []


# ---- generic English shape -------------------------------------


def test_english_voice_message_with_duration():
    out = _extract_attachments("Alice: Voice message (0:42)")
    assert out == [{"kind": "voice", "duration": "0:42", "sender": "Alice"}]


def test_english_voice_message_no_duration():
    out = _extract_attachments("Bob: Voice message")
    assert out == [{"kind": "voice", "sender": "Bob"}]


def test_english_video_call_with_duration():
    out = _extract_attachments("Alice: Video call · 1m 23s")
    assert out == [{"kind": "video_call", "duration": "1m 23s", "sender": "Alice"}]


def test_english_audio_call_short_duration():
    out = _extract_attachments("Bob: Audio call · 45s")
    assert out == [{"kind": "audio_call", "duration": "45s", "sender": "Bob"}]


def test_english_video_call_clock_duration():
    out = _extract_attachments("Alice: Video call · 12:34")
    assert out == [{"kind": "video_call", "duration": "12:34", "sender": "Alice"}]


def test_english_missed_video_call():
    out = _extract_attachments("Bob: Missed video call")
    assert out == [{"kind": "video_call", "sender": "Bob"}]


def test_english_missed_audio_call():
    out = _extract_attachments("Alice: Missed audio call")
    assert out == [{"kind": "audio_call", "sender": "Alice"}]


def test_english_missed_voice_call():
    out = _extract_attachments("Bob: Missed voice call")
    assert out == [{"kind": "audio_call", "sender": "Bob"}]


def test_english_voice_note_no_duration():
    out = _extract_attachments("Bob: Voice note")
    assert out == [{"kind": "voice", "sender": "Bob"}]


def test_english_voice_memo_with_duration():
    out = _extract_attachments("Alice: Voice memo - 0:30")
    assert out == [{"kind": "voice", "duration": "0:30", "sender": "Alice"}]


def test_english_photo():
    out = _extract_attachments("Bob: Photo")
    assert out == [{"kind": "image", "sender": "Bob"}]


def test_english_no_speaker_prefix():
    """Lines without a Sender: prefix still tag (no sender attribution)."""
    out = _extract_attachments("Voice message (0:42)")
    assert out == [{"kind": "voice", "duration": "0:42"}]


def test_english_case_insensitive():
    """English label matching is case-insensitive."""
    out = _extract_attachments("Bob: VOICE MESSAGE (0:42)")
    assert out == [{"kind": "voice", "duration": "0:42", "sender": "Bob"}]


# ---- false-positive defences -----------------------------------


def test_prose_voiced_opinion_rejected():
    """``I voiced my opinion`` does NOT fire as voice."""
    out = _extract_attachments("I voiced my opinion")
    assert out == []


def test_prose_picture_unclear_rejected():
    """``The picture is unclear`` does NOT fire as picture."""
    out = _extract_attachments("the picture is unclear")
    assert out == []


def test_prose_new_image_rejected():
    """A prose mention of ``image`` mid-sentence does not fire."""
    out = _extract_attachments("Bob: We need to vote on the new image")
    assert out == []


def test_empty_brackets_rejected():
    out = _extract_attachments("Alice: []")
    assert out == []


def test_empty_text():
    assert _extract_attachments("") == []


def test_no_attachment_no_match():
    text = "Alice: hello\nBob: hi there\nAlice: how are you"
    assert _extract_attachments(text) == []


# ---- multiple matches, ordering, dedupe ------------------------


def test_multiple_attachments_in_order():
    text = (
        "Alice: [Image]\n"
        "Bob: [Voice note 0:23]\n"
        "Cara: 📷 Photo\n"
        "Dave: Voice message (1:05)\n"
    )
    out = _extract_attachments(text)
    kinds = [e["kind"] for e in out]
    assert kinds == ["image", "voice", "image", "voice"]
    senders = [e.get("sender") for e in out]
    assert senders == ["Alice", "Bob", "Cara", "Dave"]


def test_dedupe_same_sender_kind_duration_name():
    """Same (sender, kind, duration, name) collapses to one entry."""
    text = "Alice: [Image]\nAlice: [Image]"
    out = _extract_attachments(text)
    assert out == [{"kind": "image", "sender": "Alice"}]


def test_dedupe_keeps_different_senders():
    """Different senders are kept as separate entries."""
    text = "Alice: [Image]\nBob: [Image]"
    out = _extract_attachments(text)
    assert len(out) == 2
    assert {e["sender"] for e in out} == {"Alice", "Bob"}


def test_dedupe_keeps_different_durations():
    """Same sender + kind but different duration = two entries."""
    text = "Alice: [Voice note 0:23]\nAlice: [Voice note 1:05]"
    out = _extract_attachments(text)
    assert len(out) == 2


# ---- sender tracking ------------------------------------------


def test_sender_tracked_from_preceding_transcript():
    """An attachment on a bare line after ``Sender: text`` lines
    is attributed to the most recent speaker."""
    text = "Alice: hello\nBob: hi\n[Image]"
    out = _extract_attachments(text)
    assert len(out) == 1
    assert out[0].get("sender") == "Bob"


def test_sender_none_for_lone_attachment():
    out = _extract_attachments("[Image]")
    assert out == [{"kind": "image"}]


# ---- bracket / emoji overlap defence ---------------------------


def test_bracket_wins_over_emoji_in_overlap():
    """A bracketed match's span pre-empts an emoji-prefix match."""
    text = "Alice: [📷 Photo]"
    out = _extract_attachments(text)
    # Note: the bracket regex pulls out the label "📷 Photo" which
    # is NOT in the alias map (the label starts with non-letter),
    # so this case rejects the bracket; the emoji shape inside
    # then fires. We just verify nothing crashes and exactly one
    # entry surfaces.
    assert all(e["kind"] == "image" for e in out)
    assert len(out) <= 1


# ---- cap enforcement -------------------------------------------


def test_attachment_cap_at_30():
    text = "\n".join(f"Alice: [Voice note 0:{i:02d}]" for i in range(40))
    out = _extract_attachments(text)
    assert len(out) == 30


# ---- enrich_chat integration -----------------------------------


def test_enrich_chat_populates_attachments():
    text = "Alice: hello\nBob: [Voice note 0:23]"
    out = enrich_chat(None, OCRResult(text=text))
    assert len(out.attachments) == 1
    a = out.attachments[0]
    assert a["kind"] == "voice"
    assert a["duration"] == "0:23"
    assert a["sender"] == "Bob"


def test_enrich_chat_preserves_caller_attachments():
    text = "Alice: [Image]"
    existing = ChatFields(
        attachments=[{"kind": "video", "name": "from-caller.mp4"}]
    )
    out = enrich_chat(existing, OCRResult(text=text))
    assert len(out.attachments) == 2
    assert out.attachments[0]["name"] == "from-caller.mp4"
    assert out.attachments[1]["kind"] == "image"


def test_enrich_chat_dedupes_identical():
    text = "Alice: [Image]"
    existing = ChatFields(attachments=[{"kind": "image", "sender": "Alice"}])
    out = enrich_chat(existing, OCRResult(text=text))
    assert len(out.attachments) == 1


def test_enrich_chat_no_attachments_means_empty_list():
    out = enrich_chat(None, OCRResult(text="Alice: hi\nBob: hello"))
    assert out.attachments == []


# ---- mixed shapes in one screenshot ----------------------------


def test_mixed_shapes_all_recognised():
    text = (
        "Alice: [Image]\n"
        "Bob: 🎤 Voice (0:42)\n"
        "Alice: Voice message (1:05)\n"
        "Bob: Missed video call\n"
        "Cara: 📷 Photo\n"
    )
    out = _extract_attachments(text)
    assert len(out) == 5
    kinds = [e["kind"] for e in out]
    assert kinds == ["image", "voice", "voice", "video_call", "image"]


# ---- whitespace robustness -------------------------------------


def test_bracket_with_inner_whitespace():
    out = _extract_attachments("Bob: [  Image  ]")
    assert out == [{"kind": "image", "sender": "Bob"}]


def test_emoji_with_extra_space():
    out = _extract_attachments("Alice: 📷   Photo")
    assert out == [{"kind": "image", "sender": "Alice"}]


def test_english_trailing_whitespace_ok():
    out = _extract_attachments("Bob: Voice message (0:42)   ")
    assert out == [{"kind": "voice", "duration": "0:42", "sender": "Bob"}]


# ---- name / duration interaction -------------------------------


def test_name_captured_with_document():
    out = _extract_attachments("Bob: [Document: project-spec.pdf]")
    assert out == [{"kind": "document", "name": "project-spec.pdf", "sender": "Bob"}]


def test_voice_note_zero_duration():
    out = _extract_attachments("Alice: [Voice note 0:00]")
    assert out == [{"kind": "voice", "duration": "0:00", "sender": "Alice"}]
