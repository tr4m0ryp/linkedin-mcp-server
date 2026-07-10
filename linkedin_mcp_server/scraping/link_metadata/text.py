"""Label selection and context derivation for compact references."""

from __future__ import annotations

import re

from .types import RawReference, ReferenceKind

_GENERIC_LABELS = {
    "show all",
    "follow",
    "following",
    "connect",
    "send",
    "like",
    "comment",
    "repost",
    "post",
    "play",
    "pause",
    "fullscreen",
    "close",
    "manage notifications",
    "view my newsletter",
    "my newsletter",
}

_CONTEXT_LABELS = {
    "about",
    "experience",
    "education",
    "interests",
    "honors",
    "languages",
    "featured",
    "contact info",
}

_SECTION_CONTEXTS = {
    "experience": "experience",
    "education": "education",
    "interests": "interests",
    "honors": "honors",
    "languages": "languages",
    "contact_info": "contact info",
    "job_posting": "job posting",
    "inbox": "inbox",
    "conversation": "conversation",
}

_URL_LIKE_RE = re.compile(r"^(?:https?://|/)\S+$", re.IGNORECASE)
_DUPLICATE_HALVES_RE = re.compile(r"^(?P<value>.+?)\s+(?P=value)$")
_WHITESPACE_RE = re.compile(r"\s+")
_CONNECTIONS_FOLLOW_RE = re.compile(r"\bconnections follow this page\b", re.IGNORECASE)


def choose_reference_text(
    raw: RawReference,
    kind: ReferenceKind,
) -> str | None:
    """Choose the best compact human-readable label for a reference."""
    candidates: list[tuple[int, str]] = []
    for priority, candidate in enumerate(
        (
            raw.get("text", ""),
            raw.get("aria_label", ""),
            raw.get("title", ""),
        )
    ):
        cleaned = clean_label(candidate, kind)
        if cleaned:
            candidates.append((priority, cleaned))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (_label_sort_key(item[1]), item[0]))
    return candidates[0][1]


def clean_label(value: str, kind: ReferenceKind) -> str | None:
    """Normalize and compact a candidate label."""
    value = _WHITESPACE_RE.sub(" ", value).strip()
    if not value:
        return None

    value = re.sub(
        r"^(?:View:\s*|View\b\s+|Open article:\s*)",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"[’']s\s+graphic link$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+graphic link$", "", value, flags=re.IGNORECASE)
    value = value.strip(" :-")

    if " by " in value and kind in {"article", "external"}:
        value = value.split(" by ", 1)[0].strip()

    for separator in (" • ", " · ", " | "):
        if separator in value:
            value = value.split(separator, 1)[0].strip()

    duplicate_match = _DUPLICATE_HALVES_RE.match(value)
    if duplicate_match:
        value = duplicate_match.group("value").strip()

    if _URL_LIKE_RE.match(value):
        return None
    if _CONNECTIONS_FOLLOW_RE.search(value):
        return None
    if value.lower() in _GENERIC_LABELS:
        return None
    if len(value) < 2:
        return None
    if len(value) > 80:
        return None
    if not re.search(r"[A-Za-z0-9]", value):
        return None

    return value


def derive_context(
    section_name: str,
    raw: RawReference,
    kind: ReferenceKind,
) -> str | None:
    """Build a compact context hint for one retained reference."""
    if section_name in _SECTION_CONTEXTS:
        return _SECTION_CONTEXTS[section_name]

    heading = clean_heading(raw.get("heading", ""))

    if section_name == "search_results":
        return "job result" if kind == "job" else "search result"

    if section_name == "posts":
        if kind == "person":
            return "post author"
        if kind == "feed_post":
            return "company post"
        return "post attachment"

    if section_name in {"main_profile", "about"}:
        if heading in _CONTEXT_LABELS:
            return heading
        if raw.get("in_article"):
            return "featured"
        return "top card"

    return heading if heading in _CONTEXT_LABELS else None


def clean_heading(value: str) -> str | None:
    """Normalize a raw heading into a short supported context label."""
    value = _WHITESPACE_RE.sub(" ", value).strip().lower()
    if not value:
        return None
    return value if value in _CONTEXT_LABELS else None


def _label_sort_key(label: str) -> tuple[int, int]:
    """Prefer concise labels, but deprioritize short 2-character strings."""
    return (1 if len(label) < 3 else 0, len(label))
