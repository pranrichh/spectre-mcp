<p align="center">
  <img src="../assets/headers/integrations.svg" alt="Integrations" />
</p>

# Integrations

Spectre is a standard MCP server over stdio. The command is always
`uvx spectre-mcp` (or `spectre-mcp` if installed system-wide).

## Hermes Agent (recommended)

Spectre was built for [Hermes Agent](https://github.com/NousResearch/hermes-agent),
and ships a skill that teaches the agent when to reach for which tool.

1. Add the server to `~/.hermes/config.yaml`:

   ```yaml
   mcp_servers:
     spectre:
       command: "uvx"
       args: ["spectre-mcp"]
       timeout: 120
   ```

2. Install the skill (Hermes discovers `~/.hermes/skills/<category>/<name>/SKILL.md`):

   ```bash
   mkdir -p ~/.hermes/skills/mcp/spectre/references
   curl -fsSL https://raw.githubusercontent.com/pranrichh/spectre-mcp/main/SKILL.md \
     -o ~/.hermes/skills/mcp/spectre/SKILL.md
   curl -fsSL https://raw.githubusercontent.com/pranrichh/spectre-mcp/main/references/full-follower-extraction.md \
     -o ~/.hermes/skills/mcp/spectre/references/full-follower-extraction.md
   ```

3. Reload:

   ```
   /reload-mcp
   /reload-skills
   ```

The skill covers which tool fits which job, what each call costs, what must be
confirmed first, and which failures mean "stop" rather than "retry".

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

Claude reads the tool docstrings directly, so no extra skill file is needed.

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

Or skip MCP and import the writer directly (same code the server runs):

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

After upgrading, run `spectre doctor` — it re-checks auth and the GraphQL
operation table, which is the thing most likely to age.
