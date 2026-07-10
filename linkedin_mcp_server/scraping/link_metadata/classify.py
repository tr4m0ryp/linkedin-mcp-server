"""URL normalization and classification for LinkedIn DOM anchors."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

from .types import ReferenceKind

_COMPANY_PATH_RE = re.compile(r"^/company/([^/?#]+)")
_PERSON_PATH_RE = re.compile(r"^/in/([^/?#]+)")
_SCHOOL_PATH_RE = re.compile(r"^/school/([^/?#]+)")
_JOB_PATH_RE = re.compile(r"^/jobs/view/(\d+)")
_NEWSLETTER_PATH_RE = re.compile(r"^/newsletters/([^/?#]+)")
_PULSE_PATH_RE = re.compile(r"^/pulse/([^/?#]+)")
_FEED_PATH_RE = re.compile(r"^/feed/update/([^/?#]+)")
_MESSAGING_THREAD_PATH_RE = re.compile(r"^/messaging/thread/([^/?#]+)")
_MAX_REDIRECT_UNWRAP_DEPTH = 5

# Accept both quoted-string and bare-integer JSON list elements, e.g.
# ``["1115","2573558"]`` (the form LinkedIn currently emits — verified live)
# and ``[1115,2573558]`` (also valid JSON). Optional surrounding quote keeps
# the matcher resilient if LinkedIn ever drops the string-typing.
_FIRST_URN_RE = re.compile(r'\[\s*"?(\d+)"?')


def _first_company_urn_from_query(query: str) -> str | None:
    """Pull the first numeric id from a ``currentCompany`` people-search facet.

    LinkedIn's people-search canned-search anchors carry the company URN
    in the ``currentCompany`` query param as a JSON list, e.g.
    ``currentCompany=["1115","2573558"]`` (percent-encoded in the href).
    The first id is the parent company; subsequent ids are subsidiaries.
    """
    values = parse_qs(query).get("currentCompany")
    if not values:
        return None
    match = _FIRST_URN_RE.match(values[0])
    return match.group(1) if match else None


def normalize_url(href: str, _depth: int = 0) -> str | None:
    """Normalize a raw href and unwrap LinkedIn redirect URLs."""
    if _depth > _MAX_REDIRECT_UNWRAP_DEPTH:
        return None

    href = href.strip()
    if not href or href.startswith("#"):
        return None

    parsed = urlparse(href)
    scheme = parsed.scheme.lower()
    if scheme in {"blob", "javascript", "mailto", "tel"}:
        return None
    if scheme and scheme not in {"http", "https"}:
        return None

    host = parsed.netloc.lower()
    if _is_linkedin_host(host) and parsed.path == "/redir/redirect/":
        target = unquote((parse_qs(parsed.query).get("url") or [""])[0]).strip()
        if not target:
            return None
        return normalize_url(target, _depth + 1)

    if not parsed.scheme:
        return None

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def classify_link(href: str) -> tuple[ReferenceKind, str] | None:
    """Classify and canonicalize one normalized URL."""
    parsed = urlparse(href)
    host = parsed.netloc.lower()
    path = parsed.path or "/"

    if not _is_linkedin_host(host):
        return "external", urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path or "/", "", "", "")
        )

    # The "See all employees on LinkedIn" canned-search anchor carries the
    # company URN id, which is the only value LinkedIn's currentCompany
    # people-search facet actually filters on. Match before the chrome
    # check below, which would otherwise drop every /search/results path.
    if path.rstrip("/") == "/search/results/people":
        urn_id = _first_company_urn_from_query(parsed.query)
        if urn_id:
            return (
                "company_urn",
                f"/search/results/people/?currentCompany=%5B%22{urn_id}%22%5D",
            )

    if _is_linkedin_chrome(path):
        return None

    if match := _PERSON_PATH_RE.match(path):
        person_suffix = path[match.end() :].lstrip("/")
        first_suffix_segment = person_suffix.split("/", 1)[0] if person_suffix else ""
        if first_suffix_segment in {"overlay", "details", "recent-activity"}:
            return None
        return "person", f"/in/{match.group(1)}/"

    if match := _COMPANY_PATH_RE.match(path):
        return "company", f"/company/{match.group(1)}/"

    if match := _SCHOOL_PATH_RE.match(path):
        return "school", f"/school/{match.group(1)}/"

    if match := _JOB_PATH_RE.match(path):
        return "job", f"/jobs/view/{match.group(1)}/"

    if match := _NEWSLETTER_PATH_RE.match(path):
        return "newsletter", f"/newsletters/{match.group(1)}/"

    if match := _PULSE_PATH_RE.match(path):
        return "article", f"/pulse/{match.group(1)}/"

    if match := _FEED_PATH_RE.match(path):
        return "feed_post", f"/feed/update/{match.group(1)}/"

    if match := _MESSAGING_THREAD_PATH_RE.match(path):
        return "conversation", f"/messaging/thread/{match.group(1)}/"

    return None


def _is_linkedin_chrome(path: str) -> bool:
    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = f"/{path}"

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return False

    first = segments[0]
    second = segments[1] if len(segments) > 1 else ""

    if first in {
        "help",
        "legal",
        "about",
        "accessibility",
        "mypreferences",
        "preferences",
    }:
        return True
    if first == "search" and second == "results":
        return True
    if first == "overlay" and second in {
        "background-photo",
        "browsemap-recommendations",
    }:
        return True
    return first == "preload" and second == "custom-invite"


def _is_linkedin_host(host: str) -> bool:
    return host == "linkedin.com" or host.endswith(".linkedin.com")
