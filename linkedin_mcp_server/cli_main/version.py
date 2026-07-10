"""Version resolution for the LinkedIn MCP Server CLI."""


def get_version() -> str:
    """Get version from installed metadata with a source fallback."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        for package_name in (
            "mcp-server-linkedin",
            "linkedin-scraper-mcp",
            "linkedin-mcp-server",
        ):
            try:
                return version(package_name)
            except PackageNotFoundError:
                continue
    except Exception:
        pass

    try:
        import os
        import tomllib

        # This module lives at linkedin_mcp_server/cli_main/version.py, one
        # directory deeper than the original cli_main.py, so an extra dirname()
        # is needed to reach the repository root that holds pyproject.toml.
        pyproject_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "pyproject.toml",
        )
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
            return data["project"]["version"]
    except Exception:
        return "unknown"
