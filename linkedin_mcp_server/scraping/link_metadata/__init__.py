"""Helpers for extracting compact, typed references from LinkedIn DOM links."""

from __future__ import annotations

from urllib.parse import urlparse

from .classify import (
    _COMPANY_PATH_RE,
    _FEED_PATH_RE,
    _FIRST_URN_RE,
    _JOB_PATH_RE,
    _MAX_REDIRECT_UNWRAP_DEPTH,
    _MESSAGING_THREAD_PATH_RE,
    _NEWSLETTER_PATH_RE,
    _PERSON_PATH_RE,
    _PULSE_PATH_RE,
    _SCHOOL_PATH_RE,
    _first_company_urn_from_query,
    _is_linkedin_chrome,
    _is_linkedin_host,
    classify_link,
    normalize_url,
)
from .text import (
    _CONNECTIONS_FOLLOW_RE,
    _CONTEXT_LABELS,
    _DUPLICATE_HALVES_RE,
    _GENERIC_LABELS,
    _SECTION_CONTEXTS,
    _URL_LIKE_RE,
    _WHITESPACE_RE,
    _label_sort_key,
    choose_reference_text,
    clean_heading,
    clean_label,
    derive_context,
)
from .types import RawReference, Reference, ReferenceKind

_DEFAULT_REFERENCE_CAP = 12
_REFERENCE_CAPS = {
    "main_profile": 12,
    "about": 12,
    "experience": 12,
    "education": 12,
    "interests": 12,
    "honors": 12,
    "languages": 12,
    "posts": 12,
    "jobs": 8,
    "search_results": 15,
    "job_posting": 8,
    "contact_info": 8,
    "inbox": 30,
    "conversation": 12,
    # Headroom for get_feed's num_posts ceiling (Field(ge=1, le=50)).
    # Kept in sync with the literal cap=50 in extractor._build_feed_references
    # where SDUI-derived /posts/<slug> permalinks are appended.
    "feed": 50,
}


def build_references(
    raw_references: list[RawReference],
    section_name: str,
) -> list[Reference]:
    """Filter and normalize raw DOM anchors into compact references."""
    cap = _REFERENCE_CAPS.get(section_name, _DEFAULT_REFERENCE_CAP)
    normalized_references: list[Reference] = []

    for raw in raw_references:
        normalized = normalize_reference(raw, section_name)
        if normalized is None:
            continue
        normalized_references.append(normalized)

    return dedupe_references(normalized_references, cap=cap)


def normalize_reference(
    raw: RawReference,
    section_name: str,
) -> Reference | None:
    """Normalize one raw DOM anchor into a compact reference."""
    if raw.get("in_nav") or raw.get("in_footer"):
        return None

    href = normalize_url(raw.get("href", ""))
    if href is None:
        return None

    kind_url = classify_link(href)
    if kind_url is None:
        return None
    kind, normalized_url = kind_url

    if kind == "company_urn":
        text = None
    else:
        text = choose_reference_text(raw, kind)
    if text is None and kind not in {
        "feed_post",
        "external",
        "conversation",
        "company_urn",
    }:
        return None

    context = derive_context(section_name, raw, kind)

    reference: Reference = {
        "kind": kind,
        "url": normalized_url,
    }
    if kind == "company_urn":
        # ``classify_link`` already extracted the urn while building the
        # canonical url. Re-parsing here keeps that classifier internal —
        # callers of ``normalize_reference`` shouldn't have to know the
        # url shape — and is cheap (the canonical url has a fixed
        # single-id form, so ``parse_qs`` is O(1) here).
        urn_id = _first_company_urn_from_query(urlparse(normalized_url).query)
        if urn_id:
            reference["value"] = urn_id
    if text:
        reference["text"] = text
    if context:
        reference["context"] = context
    return reference


def _choose_better_reference(existing: Reference, new: Reference) -> Reference:
    """Keep the cleaner, richer of two duplicate-url references."""
    existing_score = _reference_score(existing)
    new_score = _reference_score(new)
    return new if new_score > existing_score else existing


def dedupe_references(
    references: list[Reference],
    cap: int | None = None,
) -> list[Reference]:
    """Dedupe references by URL while keeping the cleaner duplicate in order."""
    deduped: dict[str, Reference] = {}
    ordered_urls: list[str] = []

    for reference in references:
        url = reference["url"]
        existing = deduped.get(url)
        if existing is None:
            deduped[url] = reference
            ordered_urls.append(url)
            continue
        deduped[url] = _choose_better_reference(existing, reference)

    ordered = [deduped[url] for url in ordered_urls]
    return ordered[:cap] if cap is not None else ordered


def _reference_score(reference: Reference) -> tuple[int, int, int | float]:
    text = reference.get("text")
    context = reference.get("context")
    return (
        1 if text else 0,
        1 if context else 0,
        _text_score(text),
    )


def _text_score(text: str | None) -> int | float:
    """Prefer richer labels while scoring missing text as strictly worst."""
    return len(text) if text else float("-inf")


__all__ = [
    "RawReference",
    "Reference",
    "ReferenceKind",
    "_COMPANY_PATH_RE",
    "_CONNECTIONS_FOLLOW_RE",
    "_CONTEXT_LABELS",
    "_DUPLICATE_HALVES_RE",
    "_FEED_PATH_RE",
    "_FIRST_URN_RE",
    "_GENERIC_LABELS",
    "_JOB_PATH_RE",
    "_MAX_REDIRECT_UNWRAP_DEPTH",
    "_MESSAGING_THREAD_PATH_RE",
    "_NEWSLETTER_PATH_RE",
    "_PERSON_PATH_RE",
    "_PULSE_PATH_RE",
    "_SCHOOL_PATH_RE",
    "_SECTION_CONTEXTS",
    "_URL_LIKE_RE",
    "_WHITESPACE_RE",
    "_choose_better_reference",
    "_first_company_urn_from_query",
    "_is_linkedin_chrome",
    "_is_linkedin_host",
    "_label_sort_key",
    "_reference_score",
    "_text_score",
    "build_references",
    "choose_reference_text",
    "classify_link",
    "clean_heading",
    "clean_label",
    "dedupe_references",
    "derive_context",
    "normalize_reference",
    "normalize_url",
]
