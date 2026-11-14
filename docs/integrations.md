<p align="center">
  <img src="../assets/headers/integrations.svg" alt="Integrations" />
</p>

Spectre is a standard MCP server over stdio. The command is always `uvx spectre-mcp` (or `spectre-mcp` if installed system-wide).

## Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "spectre": {
      "command": "uvx",
      "args": ["spectre-mcp"]
    }
  }
}
```

## Cursor / Windsurf / Cline

`.cursor/mcp.json` (or the equivalent config for your client):

```json
{
  "mcpServers": {
    "spectre": {
      "command": "uvx",
      "args": ["spectre-mcp"]
    }
  }
}
```

## OpenCode

`opencode.json` (project root or `~/.config/opencode/opencode.json`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "spectre": {
      "type": "local",
      "command": ["uvx", "spectre-mcp"],
      "enabled": true
    }
  }
}
```

## OMP

`.omp/mcp.json` in the project, or `~/.omp/agent/mcp.json` for every project:

```json
{
  "mcpServers": {
    "spectre": {
      "command": "uvx",
      "args": ["spectre-mcp"]
    }
  }
}
```

Then `/mcp reload` and `/mcp test spectre` inside OMP.

## DeepSeek Harness (DSH)

Add `@deepseek-ai/dsh-mcp-client` as a plugin and register Spectre as a stdio server:

```yaml
- id: mcp-spectre
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: spectre
    transport: stdio
    command: uvx
    args: ['spectre-mcp']
```

The server's tools show up as `mcp__spectre__<tool>`.

## Hermes Agent

`~/.hermes/config.yaml`:

```yaml
mcp_servers:
  spectre:
    command: "uvx"
    args: ["spectre-mcp"]
    timeout: 120
```

Hermes can also load the [SKILL.md](../SKILL.md) guide, which tells the agent
which tool fits which job and what needs confirming first. Copy it to
`~/.hermes/skills/mcp/spectre/SKILL.md` (plus
[references/full-follower-extraction.md](../references/full-follower-extraction.md)
in `references/`), then reload with `/reload-mcp` and `/reload-skills`.

## From Python

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server = StdioServerParameters(command="uvx", args=["spectre-mcp"])
async with stdio_client(server) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        me = await session.call_tool("get_me", {})
```

Or skip MCP and import the writer directly (the same code the server runs):

```python
import asyncio
from twscrape.accounts_pool import AccountsPool
from spectre.writer import Writer
from spectre.xclient import XClient

async def main():
    pool = AccountsPool()                      # ~/.spectre/accounts.db
    writer = Writer(XClient(pool))
    print(await writer.me())
    print(await writer.search_bookmarks("mcp"))

asyncio.run(main())
```

## Updating

`uvx` always resolves the latest PyPI release. For managed installs:

```bash
pipx upgrade spectre-mcp      # pipx
uv tool upgrade spectre-mcp   # uv
```

After upgrading, run `spectre doctor` to check cookies and connectivity.
