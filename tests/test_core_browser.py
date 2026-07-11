"""Tests for BrowserManager cookie import/export helpers."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from linkedin_mcp_server.core.browser import BrowserManager
from linkedin_mcp_server.core.browser._helpers import (
    build_context_options,
    build_proxy_options,
)


def _make_cookie(
    name: str,
    value: str = "value",
    *,
    domain: str = ".linkedin.com",
) -> dict[str, str]:
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
    }


def _make_browser_manager(tmp_path) -> tuple[BrowserManager, MagicMock]:
    browser = BrowserManager(user_data_dir=tmp_path / "profile")
    context = MagicMock()
    context.clear_cookies = AsyncMock()
    context.add_cookies = AsyncMock()
    context.storage_state = AsyncMock()
    browser._context = context
    return browser, context


@pytest.mark.asyncio
async def test_import_cookies_imports_bridge_subset_only(tmp_path):
    browser, context = _make_browser_manager(tmp_path)
    cookie_path = tmp_path / "cookies.json"
    cookies = [
        _make_cookie("li_at"),
        _make_cookie("JSESSIONID"),
        _make_cookie("bcookie"),
        _make_cookie("bscookie"),
        _make_cookie("lidc"),
        _make_cookie("session", domain=".example.com"),
        _make_cookie("timezone"),
    ]
    cookie_path.write_text(json.dumps(cookies))

    imported = await browser.import_cookies(cookie_path)

    assert imported is True
    context.clear_cookies.assert_not_awaited()
    context.add_cookies.assert_awaited_once_with(
        [cookies[0], cookies[1], cookies[2], cookies[3], cookies[4]]
    )


@pytest.mark.asyncio
async def test_import_cookies_uses_bridge_core_debug_preset(tmp_path, monkeypatch):
    browser, context = _make_browser_manager(tmp_path)
    cookie_path = tmp_path / "cookies.json"
    cookies = [
        _make_cookie("li_at"),
        _make_cookie("JSESSIONID"),
        _make_cookie("bcookie"),
        _make_cookie("bscookie"),
        _make_cookie("lidc"),
        _make_cookie("liap"),
        _make_cookie("timezone"),
    ]
    cookie_path.write_text(json.dumps(cookies))
    monkeypatch.setenv("LINKEDIN_DEBUG_BRIDGE_COOKIE_SET", "bridge_core")

    imported = await browser.import_cookies(cookie_path)

    assert imported is True
    context.add_cookies.assert_awaited_once_with(cookies)


@pytest.mark.asyncio
async def test_import_cookies_requires_li_at(tmp_path):
    browser, context = _make_browser_manager(tmp_path)
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(
        json.dumps(
            [
                _make_cookie("JSESSIONID"),
                _make_cookie("bcookie"),
            ]
        )
    )

    imported = await browser.import_cookies(cookie_path)

    assert imported is False
    context.clear_cookies.assert_not_awaited()
    context.add_cookies.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_cookies_preserves_existing_cookies(tmp_path):
    browser, context = _make_browser_manager(tmp_path)
    cookie_path = tmp_path / "cookies.json"
    cookie_path.write_text(
        json.dumps(
            [
                _make_cookie("li_at"),
                _make_cookie("li_rm"),
                _make_cookie("JSESSIONID"),
            ]
        )
    )

    imported = await browser.import_cookies(cookie_path)

    assert imported is True
    context.clear_cookies.assert_not_awaited()
    context.add_cookies.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_storage_state_calls_context_storage_state(tmp_path):
    browser, context = _make_browser_manager(tmp_path)
    storage_state_path = tmp_path / "storage-state.json"

    exported = await browser.export_storage_state(storage_state_path, indexed_db=True)

    assert exported is True
    context.storage_state.assert_awaited_once_with(
        path=storage_state_path,
        indexed_db=True,
    )


@pytest.mark.asyncio
async def test_export_storage_state_requires_context(tmp_path):
    browser = BrowserManager(user_data_dir=tmp_path / "profile")

    exported = await browser.export_storage_state(tmp_path / "storage-state.json")

    assert exported is False


def test_build_proxy_options_inert_without_server(monkeypatch):
    monkeypatch.delenv("LINKEDIN_PROXY_SERVER", raising=False)
    assert build_proxy_options() is None


def test_build_proxy_options_server_only(monkeypatch):
    monkeypatch.setenv("LINKEDIN_PROXY_SERVER", "http://proxy.example:8080")
    monkeypatch.delenv("LINKEDIN_PROXY_USERNAME", raising=False)
    monkeypatch.delenv("LINKEDIN_PROXY_PASSWORD", raising=False)

    assert build_proxy_options() == {"server": "http://proxy.example:8080"}


def test_build_proxy_options_with_credentials(monkeypatch):
    monkeypatch.setenv("LINKEDIN_PROXY_SERVER", "http://proxy.example:8080")
    monkeypatch.setenv("LINKEDIN_PROXY_USERNAME", "user")
    monkeypatch.setenv("LINKEDIN_PROXY_PASSWORD", "secret")

    assert build_proxy_options() == {
        "server": "http://proxy.example:8080",
        "username": "user",
        "password": "secret",
    }


def test_build_context_options_injects_proxy_from_env(monkeypatch):
    monkeypatch.setenv("LINKEDIN_PROXY_SERVER", "socks5://proxy.example:1080")
    monkeypatch.delenv("LINKEDIN_PROXY_USERNAME", raising=False)
    monkeypatch.delenv("LINKEDIN_PROXY_PASSWORD", raising=False)

    options = build_context_options(
        headless=True,
        slow_mo=0,
        viewport={"width": 1280, "height": 720},
        user_agent=None,
        launch_options={},
    )

    assert options["proxy"] == {"server": "socks5://proxy.example:1080"}


def test_build_context_options_no_proxy_when_unset(monkeypatch):
    monkeypatch.delenv("LINKEDIN_PROXY_SERVER", raising=False)

    options = build_context_options(
        headless=True,
        slow_mo=0,
        viewport={"width": 1280, "height": 720},
        user_agent=None,
        launch_options={},
    )

    assert "proxy" not in options


def test_build_context_options_explicit_proxy_wins(monkeypatch):
    monkeypatch.setenv("LINKEDIN_PROXY_SERVER", "http://env-proxy.example:8080")
    explicit = {"server": "http://explicit.example:3128"}

    options = build_context_options(
        headless=True,
        slow_mo=0,
        viewport={"width": 1280, "height": 720},
        user_agent=None,
        launch_options={"proxy": explicit},
    )

    assert options["proxy"] == explicit


@pytest.mark.asyncio
async def test_close_is_idempotent_and_resets_state(tmp_path):
    browser = BrowserManager(user_data_dir=tmp_path / "profile")
    browser._page = MagicMock()
    context = MagicMock()
    context.close = AsyncMock(side_effect=RuntimeError("boom"))
    playwright = MagicMock()
    playwright.stop = AsyncMock()
    browser._context = context
    browser._playwright = playwright

    await browser.close()
    await browser.close()

    context.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    assert browser._context is None
    assert browser._page is None
    assert browser._playwright is None
