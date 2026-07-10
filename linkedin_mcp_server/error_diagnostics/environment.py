"""Runtime and environment snapshot renderers for issue diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _build_gist_command(
    issue_dir: Path,
    issue_path: Path,
    log_path: Path | None,
) -> str:
    trace_path = issue_dir / "trace.jsonl"
    files = [str(issue_path)]
    if log_path is not None and log_path.exists():
        files.append(str(log_path))
    if trace_path.exists():
        files.append(str(trace_path))
    quoted = " ".join(f'"{path}"' for path in files)
    return f'gh gist create {quoted} -d "LinkedIn MCP debug artifacts"'


def _installation_method_lines(runtime: dict[str, Any]) -> list[str]:
    current_runtime_id = str(runtime.get("current_runtime_id") or "")
    docker_checked = "x" if "container" in current_runtime_id else " "
    managed_checked = " " if "container" in current_runtime_id else "x"
    return [
        f"- [{docker_checked}] Docker (specify docker image version/tag): `stickerdaniel/linkedin-mcp-server:<version-or-latest>` with `~/.linkedin-mcp` mounted into `/home/pwuser/.linkedin-mcp`",
        f"- [{managed_checked}] Managed runtime (Claude Desktop MCP Bundle, `uvx`, or local `uv run` setup)",
    ]


def _installation_method_summary(runtime: dict[str, Any]) -> str:
    current_runtime_id = str(runtime.get("current_runtime_id") or "")
    if "container" in current_runtime_id:
        return (
            "Docker using `stickerdaniel/linkedin-mcp-server:<version-or-latest>` with "
            "`~/.linkedin-mcp` mounted into `/home/pwuser/.linkedin-mcp`"
        )
    return "Managed runtime (Claude Desktop MCP Bundle, `uvx`, or local `uv run` setup)"
