"""Deterministic runtime identity derivation and container detection.

``platform`` and ``Path`` are module/class singletons: tests patch
``session_state.platform.<attr>`` and ``session_state.Path.<attr>`` on the
shared objects, so the calls here observe those patches regardless of module.
"""

from __future__ import annotations

import platform
from pathlib import Path


def get_runtime_id() -> str:
    """Return a deterministic identity for the current browser runtime."""
    os_name = _normalize_os(platform.system())
    arch = _normalize_arch(platform.machine())
    runtime_kind = "container" if _is_container_runtime() else "host"
    return f"{os_name}-{arch}-{runtime_kind}"


def _normalize_os(system: str) -> str:
    mapping = {
        "Darwin": "macos",
        "Linux": "linux",
        "Windows": "windows",
    }
    return mapping.get(system, system.lower() or "unknown")


def _normalize_arch(machine: str) -> str:
    value = machine.lower()
    if value in {"x86_64", "amd64"}:
        return "amd64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    return value or "unknown"


def _is_container_runtime() -> bool:
    if any(
        path.exists()
        for path in (
            Path("/.dockerenv"),
            Path("/run/.containerenv"),
            Path("/run/containerenv"),
        )
    ):
        return True

    markers = ("docker", "containerd", "kubepods", "podman", "libpod")
    for probe in (
        Path("/proc/1/cgroup"),
        Path("/proc/self/cgroup"),
    ):
        if _path_contains_markers(probe, markers):
            return True

    for probe in (
        Path("/proc/1/mountinfo"),
        Path("/proc/self/mountinfo"),
    ):
        if _path_contains_markers(probe, markers) or _root_mount_uses_overlay(probe):
            return True

    return False


def _path_contains_markers(path: Path, markers: tuple[str, ...]) -> bool:
    if not path.exists():
        return False

    try:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False

    return any(marker in text for marker in markers)


def _root_mount_uses_overlay(path: Path) -> bool:
    if not path.exists():
        return False

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False

    for line in lines:
        if " - " not in line:
            continue
        left, right = line.split(" - ", maxsplit=1)
        left_fields = left.split()
        right_fields = right.split()
        if len(left_fields) < 5 or not right_fields:
            continue
        if left_fields[4] == "/" and right_fields[0] == "overlay":
            return True

    return False
