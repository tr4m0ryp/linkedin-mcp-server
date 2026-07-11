"""Tests for the optional, config-driven MCP auth layer."""

import pytest

from linkedin_mcp_server.auth import build_auth
from linkedin_mcp_server.config.schema import ConfigurationError, ServerConfig


def test_build_auth_none_when_unset():
    assert build_auth(ServerConfig()) is None


def test_build_auth_static_bearer_only():
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    auth = build_auth(ServerConfig(mcp_api_key="secret-token"))

    assert isinstance(auth, StaticTokenVerifier)
    assert "secret-token" in auth.tokens


def test_build_auth_authkit_only():
    from fastmcp.server.auth.providers.workos import AuthKitProvider

    auth = build_auth(
        ServerConfig(
            workos_authkit_domain="https://tenant.authkit.app",
            mcp_base_url="https://linkedin-mcp.example.com",
        )
    )

    assert isinstance(auth, AuthKitProvider)


def test_build_auth_authkit_requires_base_url():
    with pytest.raises(ConfigurationError):
        build_auth(ServerConfig(workos_authkit_domain="https://tenant.authkit.app"))


def test_build_auth_multiauth_accepts_either_credential():
    from fastmcp.server.auth import MultiAuth

    auth = build_auth(
        ServerConfig(
            mcp_api_key="secret-token",
            workos_authkit_domain="https://tenant.authkit.app",
            mcp_base_url="https://linkedin-mcp.example.com",
        )
    )

    assert isinstance(auth, MultiAuth)
    # AuthKit owns the RFC 9728 metadata routes; the bearer is an extra verifier.
    routes = {getattr(r, "path", None) for r in auth.get_routes("/mcp")}
    assert "/.well-known/oauth-protected-resource/mcp" in routes
