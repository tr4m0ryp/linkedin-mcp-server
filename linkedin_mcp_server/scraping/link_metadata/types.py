"""Typed payloads for compact references extracted from LinkedIn DOM links."""

from __future__ import annotations

from typing import Literal, NotRequired, Required, TypedDict

ReferenceKind = Literal[
    "person",
    "company",
    "company_urn",
    "job",
    "feed_post",
    "article",
    "newsletter",
    "school",
    "conversation",
    "external",
]


class Reference(TypedDict):
    """Compact reference payload returned to MCP clients."""

    kind: Required[ReferenceKind]
    url: Required[str]
    text: NotRequired[str]
    context: NotRequired[str]
    value: NotRequired[str]


class RawReference(TypedDict, total=False):
    """Raw anchor data collected from the browser DOM."""

    href: str
    text: str
    aria_label: str
    title: str
    heading: str
    in_article: bool
    in_nav: bool
    in_footer: bool
