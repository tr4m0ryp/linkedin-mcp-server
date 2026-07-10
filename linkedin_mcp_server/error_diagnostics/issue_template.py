"""GitHub issue title/body builders and issue-related constants."""

from __future__ import annotations

import json
from typing import Any

from .environment import (
    _installation_method_lines,
    _installation_method_summary,
)

ISSUE_URL = "https://github.com/stickerdaniel/linkedin-mcp-server/issues/new/choose"
ISSUE_TITLE_PREFIX = "[BUG]"
ISSUE_SEARCH_API = "https://api.github.com/search/issues"


def _render_issue_template(payload: dict[str, Any]) -> str:
    runtime = payload["runtime"]
    existing_issues = payload.get("existing_issues") or []
    has_existing_issues = bool(existing_issues)
    issue_search_skipped = bool(payload.get("issue_search_skipped"))
    installation_lines = _installation_method_lines(runtime)
    tool_name = _tool_name_for_context(payload) or "unknown"
    setup_lines = [
        f"- Installation method: {_installation_method_summary(runtime)}",
        "- MCP client: Local curl-based MCP HTTP client against the server's streamable-http transport",
        f"- Operating system / runtime: {runtime['current_runtime_id']}",
    ]
    if runtime.get("trace_dir"):
        setup_lines.append(f"- Trace artifacts directory: {runtime['trace_dir']}")
    if runtime.get("log_path"):
        setup_lines.append(f"- Server log path: {runtime['log_path']}")

    what_happened_lines = [
        f"- Suggested title: {payload['suggested_issue_title']}",
        f"- Context: {payload['context']}",
        f"- Tool: {tool_name}",
        f"- Section: {payload.get('section_name') or 'n/a'}",
        f"- Target URL: {payload.get('target_url') or 'n/a'}",
        f"- Error: {payload['error_type']}: {payload['error_message']}",
        "- Expected behavior: The MCP tool call should complete and return structured scraping output.",
    ]

    reproduction_lines = [
        "1. Run a fresh local `uv run -m linkedin_mcp_server --login`.",
        "2. Start the server again using the same installation method and debug env vars used for this run.",
        f"3. Call `{tool_name}` again with the same target URL and section selection.",
        (
            "4. If one of the listed open issues matches, post the gist as a comment there as additional information."
            if has_existing_issues
            else "4. If no existing issue matches, open a new GitHub bug report with the information above."
        ),
    ]
    return (
        "\n".join(
            [
                "# LinkedIn MCP scrape failure",
                "",
                "## File This Issue",
                "- Read this generated file before posting.",
                "- Copy the `Setup`, `What Happened`, `Steps to Reproduce`, and `Logs` sections below into the matching GitHub bug report fields.",
                "- Attach this generated markdown file, the server log, and the trace artifacts directory.",
                (
                    "- Review the existing open issues below first. If one matches, post the gist as a comment there instead of opening a new issue."
                    if has_existing_issues
                    else f"- GitHub issue link: {ISSUE_URL}"
                ),
                "",
                "## Existing Open Issues",
                *(
                    [
                        f"- #{issue['number']}: {issue['title']} ({issue['url']})"
                        for issue in existing_issues
                    ]
                    if has_existing_issues
                    else (
                        [
                            "- Matching open-issue search was skipped in async server context to avoid blocking the server event loop."
                        ]
                        if issue_search_skipped
                        else ["- No matching open issues found during diagnostics."]
                    )
                ),
                "",
                "## Setup",
                *setup_lines,
                "",
                "## What Happened",
                *what_happened_lines,
                "",
                "## Steps to Reproduce",
                *reproduction_lines,
                "",
                "## Logs",
                "```text",
                "See attached server log and trace artifacts.",
                "```",
                "",
                "## Additional Diagnostics",
                "",
                "### Installation Method Details",
                *installation_lines,
                "",
                "### Runtime Diagnostics",
                f"- Hostname: {runtime['hostname']}",
                f"- Current runtime: {runtime['current_runtime_id']}",
                f"- Source profile: {runtime['source_profile_dir']}",
                f"- Portable cookies: {runtime['portable_cookie_path']}",
                f"- Derived runtime profile: {runtime['runtime_profile_dir']}",
                f"- Derived storage-state: {runtime['runtime_storage_state_path']}",
                f"- Trace artifacts: {runtime['trace_dir'] or 'not enabled'}",
                f"- Server log: {runtime['log_path'] or 'not enabled'}",
                f"- Suggested gist command: {runtime['suggested_gist_command'] or 'not available'}",
                "",
                "### Session State",
                "```json",
                json.dumps(
                    {
                        "source_state": runtime["source_state"],
                        "runtime_state": runtime["runtime_state"],
                    },
                    indent=2,
                    sort_keys=True,
                ),
                "```",
                "",
                "### Attachment Checklist",
                "- Read this generated markdown file and use it as the issue body/context.",
                "- Attach this generated markdown file itself.",
                "- Attach the server log if available.",
                "- Attach the trace screenshots/trace.jsonl if available.",
                "- Optional: run the suggested gist command below to upload the text artifacts as a single shareable bundle.",
                "",
                "### Suggested Gist Command",
                "```bash",
                runtime["suggested_gist_command"] or "# gist command unavailable",
                "```",
            ]
        )
        + "\n"
    )


def _suggest_issue_title(
    *,
    context: str,
    section_name: str | None,
    target_url: str | None,
    current_runtime_id: str,
) -> str:
    section = section_name or "unknown-section"
    route = target_url or context
    if "/recent-activity/" in route:
        summary = f"recent-activity redirect loop in {section} on {current_runtime_id}"
    else:
        summary = f"{section} scrape failure in {context} on {current_runtime_id}"
    return f"{ISSUE_TITLE_PREFIX} {summary}"


def _tool_name_for_context(payload: dict[str, Any]) -> str | None:
    context = str(payload.get("context") or "")
    if context in {
        "get_person_profile",
        "get_company_profile",
        "get_company_posts",
        "get_job_details",
        "search_jobs",
        "search_people",
        "close_session",
    }:
        return context

    if context in {"extract_page", "extract_overlay", "scrape_person"}:
        return "get_person_profile"
    if context == "scrape_company":
        return "get_company_profile"
    if context == "extract_search_page":
        target_url = str(payload.get("target_url") or "")
        if "/search/results/people" in target_url:
            return "search_people"
        if "/jobs/search" in target_url:
            return "search_jobs"

    return None
