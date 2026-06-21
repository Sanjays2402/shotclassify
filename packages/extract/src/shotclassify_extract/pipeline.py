"""Pipeline that runs the right extractor for the classified category."""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult

from .chat import enrich_chat
from .code import enrich_code
from .emails import extract_emails
from .error import enrich_error
from .git_shas import extract_git_shas
from .identifiers import extract_identifiers
from .macs import extract_macs
from .network import extract_network
from .paths import extract_paths
from .phones import extract_phones
from .receipt import enrich_receipt
from .urls import extract_urls
from .uuids import extract_uuids


def enrich(category: Category, fields: ExtractedFields, ocr: OCRResult) -> ExtractedFields:
    out = fields.model_copy(deep=True)
    if category == Category.receipt:
        out.receipt = enrich_receipt(out.receipt, ocr)
    elif category == Category.code_snippet:
        out.code = enrich_code(out.code, ocr)
    elif category == Category.error_stacktrace:
        out.error = enrich_error(out.error, ocr)
    elif category == Category.chat_screenshot:
        out.chat = enrich_chat(out.chat, ocr)
    # meme/document/ui_mockup/chart/other rely on LLM fields; nothing to enrich

    # Cross-category: stash every http(s) URL found in the OCR text
    # under raw["urls"]. Runs for EVERY category because URLs show up
    # everywhere (error -> docs link, receipt -> Yelp page, chat ->
    # mostly links). Callers that need only one category's URLs can
    # ignore the key; storage already persists raw as a JSON column.
    text = ocr.text or ""
    urls = extract_urls(text)
    if urls:
        out.raw = dict(out.raw or {})
        out.raw["urls"] = urls

    # Cross-category: stash filesystem paths found in the OCR text
    # under raw["paths"]. Mirrors the URL extractor (also runs for
    # every category) -- error stacktraces, code snippets, terminal
    # screenshots, and documents all reference paths and dashboards
    # want a single key to look at. URL spans are masked out before
    # scanning so a URL's path component does not double-count.
    paths = extract_paths(text)
    if paths:
        out.raw = dict(out.raw or {})
        out.raw["paths"] = paths

    # Cross-category: stash IP / IPv6 / host:port endpoints found in
    # the OCR text under raw["network"]. Network endpoints appear in
    # every category -- error stacktraces print the upstream that
    # refused the connection, code snippets bind to ``0.0.0.0:8080``,
    # terminal screenshots paste shell URIs. URL spans are masked
    # before scanning so a URL's authority does not double-count.
    network = extract_network(text)
    if network:
        out.raw = dict(out.raw or {})
        out.raw["network"] = network

    # Cross-category: stash email addresses found in the OCR text
    # under raw["emails"]. Emails appear across every category --
    # error reports cite the on-call address, receipts include the
    # merchant's billing email, code snippets reference test
    # fixtures, chats are mostly emails between people. Email
    # spans never overlap URL spans (a URL has ``://`` between the
    # scheme and authority, while an email has ``@`` between local
    # and domain) so no masking is required.
    emails = extract_emails(text)
    if emails:
        out.raw = dict(out.raw or {})
        out.raw["emails"] = emails

    # Cross-category: stash academic / publishing identifiers (ISBN,
    # DOI, arXiv, ISSN) found in the OCR text under
    # raw["identifiers"] as a list of {"type", "value"} dicts. These
    # show up on document and chart captures most often but a code
    # snippet's docstring or a chat message can also cite a DOI, so
    # we run the matcher cross-category and let the consumer filter
    # by type. Each identifier passes its respective check-digit
    # validation (EAN-13 / mod-11 / arXiv shape) so 13-digit barcode
    # noise does not false-positive as an ISBN.
    identifiers = extract_identifiers(text)
    if identifiers:
        out.raw = dict(out.raw or {})
        out.raw["identifiers"] = identifiers

    # Cross-category: stash phone numbers found in the OCR text under
    # raw["phones"]. Phone numbers appear across categories --
    # receipts print the merchant's contact line, chat captures show
    # contact cards, signatures embed direct lines, error pages list
    # the on-call number, document captures cite source citations.
    # Output is in canonical digits-only form (with a leading ``+``
    # for E.164 matches) so dashboards de-dupe trivially across
    # printer formatting variation.
    phones = extract_phones(text)
    if phones:
        out.raw = dict(out.raw or {})
        out.raw["phones"] = phones

    # Cross-category: stash UUIDs found in the OCR text under
    # raw["uuids"]. UUIDs appear everywhere -- correlation IDs in
    # error logs, test fixtures in code snippets, resource IDs in
    # document URLs, invite links in chats. Output is canonical
    # lowercase + hyphenated RFC 4122 form so the same UUID printed
    # compact vs dashed collapses to one entry. The "nil" UUID
    # (all zeros) is rejected as a placeholder.
    uuids = extract_uuids(text)
    if uuids:
        out.raw = dict(out.raw or {})
        out.raw["uuids"] = uuids

    # Cross-category: stash git commit SHAs found in the OCR text
    # under raw["git_shas"]. SHAs appear in error stacktraces that
    # cite the release tag, code snippet docstrings, terminal
    # ``git log`` output, document build provenance, and chat PR
    # references. Full 40-hex SHAs are matched standalone; short
    # 7..12 hex SHAs require a git-vocabulary context (commit /
    # revision / rev / Fixes: / Refs: etc.) to avoid false-
    # positiving on UUIDs and color codes. Output is lowercase.
    git_shas = extract_git_shas(text)
    if git_shas:
        out.raw = dict(out.raw or {})
        out.raw["git_shas"] = git_shas

    # Cross-category: stash MAC addresses found in the OCR text under
    # raw["macs"]. MACs surface in terminal screenshots (``ifconfig``
    # / ``ip link`` output), network-config captures, ARP / DHCP
    # tables, router console output, and asset-inventory documents.
    # Output is canonical lowercase + colon-separated EUI-48 form so
    # the same MAC printed colon / dash / Cisco-dot-quad collapses to
    # one entry. The null MAC (all zeros) and broadcast MAC (all
    # ones) are rejected because they don't identify a specific
    # device. IPv6 spans are masked before scanning so a compressed
    # IPv6 doesn't false-positive as a MAC.
    macs = extract_macs(text)
    if macs:
        out.raw = dict(out.raw or {})
        out.raw["macs"] = macs

    return out
