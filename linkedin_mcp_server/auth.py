"""claude.ai-compatible auth for the streamable-http transport.

Reuses the proven WorkOS AuthKit + static-bearer pattern from the sibling
``finding_house_mcp`` / ``enrichment-mcp`` / ``gmail-mcp-server`` connectors,
adapted to this repo's dataclass config. One function, :func:`build_auth`,
returns the single FastMCP auth layer (or ``None`` for authless), selected
purely from config so the rest of the server never branches on it:

- Neither ``MCP_API_KEY`` nor ``WORKOS_AUTHKIT_DOMAIN`` set -> ``None``
  (authless; today's behaviour, for local / tunnelled use).
- ``MCP_API_KEY`` only -> static bearer (``StaticTokenVerifier``). Claude Code
  and curl send ``Authorization: Bearer $MCP_API_KEY``.
- ``WORKOS_AUTHKIT_DOMAIN`` only -> stateless WorkOS AuthKit resource server
  (``AuthKitProvider``, RFC 9728): the server only verifies AuthKit-issued JWTs
  against the tenant JWKS and serves protected-resource metadata pointing
  clients at AuthKit. claude.ai web registers itself (DCR, which must be enabled
  in the WorkOS dashboard) and refreshes tokens directly with AuthKit, so
  restarts never invalidate a connection. Requires ``MCP_BASE_URL`` (the public
  https URL of this server, without the ``/mcp`` suffix).
- Both -> ``MultiAuth`` that accepts EITHER credential: the AuthKit provider
  owns the OAuth metadata routes and JWT verification, the static bearer is
  tried as an additional verifier. Mirrors gmail-mcp-server's "either
  credential is accepted" shape.

Provider classes are imported lazily inside each branch so the bearer-only path
never imports the OAuth stack.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastmcp.server.auth import AuthProvider

from linkedin_mcp_server.config.schema import ConfigurationError, ServerConfig

if TYPE_CHECKING:
    from fastmcp.server.auth.auth import TokenVerifier

logger = logging.getLogger(__name__)

# Identity attached to the static bearer token (cosmetic; OAuth fills real ids).
_BEARER_CLIENT_ID = "linkedin-mcp-session"


def build_auth(config: ServerConfig) -> AuthProvider | None:
    """Return the server's single auth layer, or ``None`` for authless dev.

    Config-driven and optional: with neither ``MCP_API_KEY`` nor
    ``WORKOS_AUTHKIT_DOMAIN`` set the server stays authless exactly as before;
    setting either one turns on enforcement.
    """
    api_key = config.mcp_api_key
    authkit_domain = config.workos_authkit_domain

    if not api_key and not authkit_domain:
        logger.warning(
            "No MCP auth configured (no MCP_API_KEY, no WORKOS_AUTHKIT_DOMAIN) "
            "-- the /mcp endpoint is UNAUTHENTICATED: anyone who can reach it "
            "can use your LinkedIn session. Set MCP_API_KEY and/or "
            "WORKOS_AUTHKIT_DOMAIN before exposing this server."
        )
        return None

    bearer = _static_bearer(api_key) if api_key else None
    authkit = _authkit(config) if authkit_domain else None

    if authkit is not None and bearer is not None:
        from fastmcp.server.auth import MultiAuth

        logger.info(
            "Auth: WorkOS AuthKit OAuth + static bearer (either credential accepted)"
        )
        # AuthKit owns the RFC 9728 routes + OAuth metadata; the static bearer
        # is tried as an extra verifier so Claude Code and claude.ai both work.
        return MultiAuth(server=authkit, verifiers=[bearer])
    if authkit is not None:
        return authkit
    logger.info("Auth: static bearer only (MCP_API_KEY)")
    return bearer


def _static_bearer(api_key: str) -> TokenVerifier:
    """Static bearer verifier accepting ``Authorization: Bearer $MCP_API_KEY``."""
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    return StaticTokenVerifier(
        tokens={api_key: {"client_id": _BEARER_CLIENT_ID, "scopes": []}},
    )


def _authkit(config: ServerConfig) -> AuthProvider:
    """Stateless WorkOS AuthKit resource server (``AuthKitProvider``)."""
    from fastmcp.server.auth.providers.jwt import JWTVerifier
    from fastmcp.server.auth.providers.workos import AuthKitProvider

    if not config.mcp_base_url:
        raise ConfigurationError(
            "WORKOS_AUTHKIT_DOMAIN is set but MCP_BASE_URL is missing. Set "
            "MCP_BASE_URL to the public https URL of this server (without the "
            "/mcp suffix) so the OAuth metadata advertises the right resource."
        )

    domain = config.workos_authkit_domain.rstrip("/")
    logger.info(
        "Auth: WorkOS AuthKit stateless resource server (domain=%s, resource=%s)",
        domain,
        config.mcp_base_url,
    )
    # Explicit verifier = issuer + signature only, no audience binding, matching
    # the proven enrichment-mcp / gmail-mcp-server setup (an aud check would also
    # require the resource URL be registered as a Resource Indicator in WorkOS).
    return AuthKitProvider(
        authkit_domain=domain,
        base_url=config.mcp_base_url,
        token_verifier=JWTVerifier(
            jwks_uri=f"{domain}/oauth2/jwks",
            issuer=domain,
            algorithm="RS256",
        ),
    )


__all__ = ["build_auth"]
