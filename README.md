# linkedin-mcp-server

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-3fb950.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://www.python.org)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2.svg)](https://modelcontextprotocol.io)

**An MCP server that gives your LLM your own LinkedIn session.**
LinkedIn has no usable public API for reading profiles, companies, or jobs.
This drives your own logged-in browser instead, so the model sees LinkedIn
exactly as you do — no scraping API keys, no third-party data broker.

Under the hood it's one Python process. It reuses a real, persistent Chromium
profile (Patchright) that you log into once; from there the LLM gets **17 tools**
to read profiles and companies, search people and jobs, browse your feed, and
read or send messages. Extraction reads rendered `innerText` and URL patterns
rather than brittle CSS classes, and connection/message state is detected from
locale-independent signals, so it survives LinkedIn's constant layout churn.

**In short:**

1. Log in once — a QR-free browser sign-in stores a persistent session, or
   import an existing one from a browser you're already logged into.
2. Point your MCP client at the server.
3. Ask things like *"what does williamhgates list under experience?"* or
   *"find backend jobs in Amsterdam posted this week"*.

Everything runs locally against your own account: the session lives in a local
browser profile, the model only sees what a tool call returns. The usual caution
applies — automating your own logged-in LinkedIn session carries account risk and
an LLM that can send messages for you is a prompt-injection target, so use it with
awareness.

> **Disclaimer:** Independent community project. Not affiliated with, authorized
> by, or endorsed by LinkedIn Corporation or Microsoft. "LinkedIn" is a
> registered trademark of LinkedIn Corporation, used here only descriptively to
> name the third-party service this software interoperates with.

## Quick start

```bash
uv sync
uv run patchright install chromium
uv run -m linkedin_mcp_server --login   # sign in once
uv run -m linkedin_mcp_server           # run the server
```

Point any MCP client (Claude Code, Cursor, claude.ai) at the running server. See
[`AGENTS.md`](./AGENTS.md) for development commands and the full tool contract.

## License

Apache-2.0 — see [LICENSE](./LICENSE). This is a maintained fork of
[stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server)
by Daniel Sticker; the original copyright and NOTICE travel with it.
