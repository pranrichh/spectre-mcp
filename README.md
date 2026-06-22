<div align="center">

# Spectre MCP

### The fastest X/Twitter automation for AI agents

**104 tools for X/Twitter automation — no browser, no API keys, no monthly fees.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-8B5CF6?style=flat-square)](https://modelcontextprotocol.io)
[![PyPI](https://img.shields.io/pypi/v/spectre-mcp?style=flat-square&color=cb3837&label=pypi)](https://pypi.org/project/spectre-mcp/)

[Quick Start](#-quick-start) · [All Tools](#-all-104-tools) · [Why Spectre?](#-why-spectre) · [Safety Guide](#️-safety-guide) · [Integrations](#-integrations)

</div>

---

## Why Spectre?

Spectre is an MCP server that gives AI agents 104 tools for X/Twitter automation — from search and posting to DMs, lists, and communities. Under the hood, it talks directly to X's internal GraphQL and REST APIs. No browser to spin up, no Puppeteer to maintain, no DOM scraping that breaks on UI changes.

| | **Spectre** | **XActions** | **twikit** |
|--|:-:|:-:|:-:|
| **Architecture** | Direct GraphQL/REST | Puppeteer (headless browser) | Python API wrapper |
| **Speed** | <1s per request | 3–10s (browser startup) | ~1s per request |
| **Memory** | ~10 MB | ~200 MB+ (Chromium) | ~10 MB |
| **MCP Server** | ✅ 104 tools | ⚠️ ~50 API tools | ❌ None |
| **Account Pool** | ✅ Multi-account auto-rotation | ❌ Single auth_token | ❌ Single session |
| **Browser Required** | ❌ Never | ✅ Always | ❌ Never |
| **DOM Breakage Risk** | ❌ None | ⚠️ Breaks on UI changes | ❌ None |
| **Media Upload** | ✅ Cookie-based (no API keys) | ⚠️ Requires API keys | ❌ |
| **Lists** | ✅ Full CRUD + members + subscribe | ❌ | ❌ |
| **Drafts & Scheduled** | ✅ Full CRUD | ⚠️ Basic | ❌ |
| **Bookmark Folders** | ✅ Full CRUD + timeline | ❌ | ❌ |
| **DM Search** | ✅ All / groups / people | ❌ | ❌ |
| **Community Notes** | ✅ Read + rate | ❌ | ❌ |
| **Highlights** | ✅ Create, delete, get | ❌ | ❌ |
| **Notifications** | ✅ Full timeline | ❌ | ❌ |
| **Language** | Python | JavaScript | Python |

**Bottom line:** Spectre covers 104 tools across every X feature — search, tweets, DMs, lists, communities, bookmarks, drafts, scheduling, profiles, and more — all without spinning up a browser.

---

## 🚀 Quick Start

### 1. Install

```bash
# Recommended — isolated, auto-updates
pipx install spectre-mcp

# Or with uv
uv tool install spectre-mcp
```

### 2. Add Your X Account

Extract cookies from your browser:

1. Open **x.com** and make sure you're logged in
2. Open **DevTools** (`F12` or `Ctrl+Shift+I`)
3. Go to **Storage** → **Cookies** → select **`https://x.com`**
4. Find and copy these two values:
   - **`auth_token`** — long hex string (e.g. `a1b2c3d4...`)
   - **`ct0`** — 160-character hex string

```bash
spectre add myaccount "auth_token=a1b2c3d4...; ct0=e5f6a7b8..."
```

> **Tip:** `ct0` is exactly 160 hex characters. Double-check you copied the full value — partial cookies will fail silently.

### 3. Configure Your MCP Client

#### Hermes Agent

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  spectre:
    command: "uvx"
    args: ["spectre-mcp"]
    timeout: 120
```

Then run `/reload-mcp` in your Hermes session.

#### Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

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

#### Cursor / Windsurf

Add to your MCP config (`.cursor/mcp.json` or equivalent):

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

#### Any MCP Client

Spectre works with any client that supports the [Model Context Protocol](https://modelcontextprotocol.io). Use `uvx spectre-mcp` as the command.

> **No `uv`?** Install it: `curl -LsSf https://astral.sh/uv/install.sh | sh`
> Or use `python3 -m spectre.server` to run from a local clone.

### Updating

`uvx` always pulls the latest version from PyPI automatically. For manual upgrades:

```bash
pipx upgrade spectre-mcp    # pipx
uv tool upgrade spectre-mcp  # uv
```

---

## 📦 All 104 Tools

### Account Pool (5)

Manage multiple X accounts with automatic rotation on rate limits.

| Tool | Description |
|------|-------------|
| `list_accounts()` | List all accounts with status |
| `pool_status()` | Pool health stats |
| `set_active_account(username)` | Set primary account |
| `set_auto_rotate(enabled)` | Enable/disable auto-rotation |
| `remove_account(username)` | ⚠️ Remove account from pool |

### Search (2)

| Tool | Description |
|------|-------------|
| `search(query, limit, mode)` | Search tweets. Supports `from:username`, `since:2026-01-01`, `#hashtag`, `filter:media` |
| `search_users(query, limit)` | Search users by name/keyword |

### Users (12)

| Tool | Description |
|------|-------------|
| `get_user(username)` | User profile by @handle |
| `get_user_tweets(username, limit)` | User's recent tweets |
| `get_user_tweets_and_replies(username, limit)` | User's tweets and replies |
| `get_user_media(username, limit)` | User's photos/videos/GIFs |
| `get_followers(username, limit)` | User's followers |
| `get_following(username, limit)` | Who a user follows |
| `get_user_likes(user_id, limit)` | A user's liked tweets |
| `get_user_highlights(user_id, limit)` | User's highlighted tweets |
| `get_verified_followers(user_id, limit)` | Blue-verified followers |
| `get_followers_you_know(user_id, limit)` | Mutual followers |
| `get_list_memberships(user_id, limit)` | Lists a user is a member of |
| `get_list_ownerships(user_id, limit)` | Lists owned by a user |

### Tweets (8)

| Tool | Description |
|------|-------------|
| `get_tweet(tweet_id)` | Single tweet by ID |
| `get_tweet_replies(tweet_id, limit)` | Replies to a tweet |
| `get_thread(tweet_id, limit)` | Full conversation thread |
| `get_retweeters(tweet_id, limit)` | Users who retweeted |
| `get_favoriters(tweet_id, limit)` | Users who liked a tweet |
| `get_tweet_edit_history(tweet_id)` | Edit history of a tweet |
| `get_similar_posts(tweet_id, limit)` | Similar/related posts |
| `get_community_notes(tweet_id)` | Community notes on a tweet |

### Timeline & Notifications (3)

| Tool | Description |
|------|-------------|
| `get_trends(category, limit)` | Trending topics (trending, news, sport, entertainment) |
| `get_home_timeline(limit)` | Home feed |
| `get_notifications(limit)` | Notifications timeline |

### Post & Media (3)

| Tool | Description |
|------|-------------|
| `post_tweet(text, reply_to?, quote_tweet?, media_ids?)` | Post a tweet with optional media |
| `upload_media(file_path)` | Upload image or video (jpg, png, gif, mp4, mov) — no API keys |
| `delete_tweet(tweet_id)` | ⚠️ Delete a tweet |

### Engagement (6)

| Tool | Description |
|------|-------------|
| `like_tweet(tweet_id)` | Like a tweet |
| `unlike_tweet(tweet_id)` | Unlike a tweet |
| `retweet(tweet_id)` | Retweet |
| `unretweet(tweet_id)` | Undo retweet |
| `bookmark_tweet(tweet_id)` | Bookmark a tweet |
| `unbookmark_tweet(tweet_id)` | Remove bookmark |

### Social (6)

| Tool | Description |
|------|-------------|
| `follow_user(user_id)` | ⚠️ Follow a user |
| `unfollow_user(user_id)` | ⚠️ Unfollow a user |
| `mute_user(user_id)` | Mute a user |
| `unmute_user(user_id)` | Unmute a user |
| `block_user(user_id)` | ⚠️ Block a user |
| `unblock_user(user_id)` | ⚠️ Unblock a user |

### Social Extended (3)

| Tool | Description |
|------|-------------|
| `remove_follower(user_id)` | ⚠️ Remove a follower |
| `pin_reply(tweet_id)` | Pin a reply to a conversation |
| `unpin_reply(tweet_id)` | Unpin a reply |

### DMs (9)

| Tool | Description |
|------|-------------|
| `send_dm(user_id, text)` | ⚠️ Send a direct message |
| `get_dm_inbox(limit)` | Recent DM conversations |
| `get_dm_conversation(conversation_id, limit)` | Messages in a conversation |
| `search_dm(query, limit)` | Search all DMs by text |
| `search_dm_groups(query, limit)` | Search DMs in group conversations |
| `search_dm_people(query, limit)` | Search for people in DMs |
| `get_dm_muted(limit)` | Muted DM conversations |
| `dm_block_user(user_id)` | Block a user in DMs |
| `dm_unblock_user(user_id)` | Unblock a user in DMs |

### Lists (10)

Full lifecycle: create → manage members → subscribe → delete.

| Tool | Description |
|------|-------------|
| `create_list(name, description?)` | Create a new list |
| `update_list(list_id, name, description?)` | Update list name/description |
| `delete_list(list_id)` | ⚠️ Delete a list |
| `add_list_member(list_id, user_id)` | Add user to list |
| `remove_list_member(list_id, user_id)` | Remove user from list |
| `get_list_timeline(list_id, limit)` | Tweets from a list |
| `get_list_members(list_id, limit)` | Members of a list |
| `get_list_subscribers(list_id, limit)` | List subscribers |
| `subscribe_list(list_id)` | Subscribe to a list |
| `unsubscribe_list(list_id)` | Unsubscribe from a list |

### Bookmark Folders (8)

| Tool | Description |
|------|-------------|
| `get_bookmark_folders()` | List all bookmark folders |
| `create_bookmark_folder(name)` | Create a folder |
| `edit_bookmark_folder(folder_id, name)` | Rename a folder |
| `delete_bookmark_folder(folder_id)` | ⚠️ Delete a folder |
| `add_tweet_to_folder(folder_id, tweet_id)` | Add tweet to folder |
| `remove_tweet_from_folder(folder_id, tweet_id)` | Remove tweet from folder |
| `get_bookmark_folder_timeline(folder_id, limit)` | Tweets in a folder |
| `search_bookmarks(query, limit)` | Search bookmarks by text |

### Bookmarks (2)

| Tool | Description |
|------|-------------|
| `get_bookmarks(limit)` | Your bookmarked tweets |
| `clear_all_bookmarks()` | ⚠️ Delete ALL bookmarks |

### Scheduled Tweets (4)

| Tool | Description |
|------|-------------|
| `schedule_tweet(text, execute_at, reply_to?)` | Schedule for future posting (ISO 8601 datetime) |
| `get_scheduled_tweets()` | List all scheduled tweets |
| `edit_scheduled_tweet(id, text, execute_at)` | Edit a scheduled tweet |
| `delete_scheduled_tweet(tweet_id)` | ⚠️ Delete a scheduled tweet |

### Draft Tweets (4)

| Tool | Description |
|------|-------------|
| `create_draft(text)` | Save a tweet draft |
| `get_drafts()` | List all drafts |
| `edit_draft(draft_id, text)` | Edit a draft |
| `delete_draft(tweet_id)` | ⚠️ Delete a draft |

### Communities (4)

| Tool | Description |
|------|-------------|
| `get_community_info(community_id)` | Community details |
| `get_community_tweets(community_id, limit)` | Community feed |
| `join_community(community_id)` | Join a community |
| `leave_community(community_id)` | ⚠️ Leave a community |

### Topics (3)

| Tool | Description |
|------|-------------|
| `get_topic_info(topic_id)` | Get topic details |
| `follow_topic(topic_id)` | Follow a topic |
| `unfollow_topic(topic_id)` | Unfollow a topic |

### Community Notes (2)

| Tool | Description |
|------|-------------|
| `get_community_notes(tweet_id)` | Get community notes on a tweet |
| `rate_community_note(note_id, rating)` | Rate a note as helpful / not_helpful |

> **Note:** Community Notes *creation* requires an eligible account (6+ months old, verified phone, enrolled in the program). Reading and rating notes works for all accounts.

### Account Settings & Profile (5)

| Tool | Description |
|------|-------------|
| `get_account_settings()` | View account settings |
| `update_profile(name?, bio?, location?, website?)` | ⚠️ Update profile info |
| `update_profile_image(file_path)` | ⚠️ Change avatar image |
| `update_profile_banner(file_path)` | ⚠️ Change banner image |
| `delete_profile_banner()` | ⚠️ Remove banner |

### Pin & Highlights (5)

| Tool | Description |
|------|-------------|
| `pin_tweet(tweet_id)` | ⚠️ Pin tweet to profile (replaces existing) |
| `unpin_tweet(tweet_id)` | Unpin tweet |
| `create_highlight(tweet_ids)` | ⚠️ Add tweets to profile highlights |
| `delete_highlight(highlight_id)` | ⚠️ Remove a highlight |
| `get_user_highlights(user_id, limit)` | Get user's highlighted tweets |

### Safety & Privacy (4)

| Tool | Description |
|------|-------------|
| `get_muted_accounts(limit)` | List all muted accounts |
| `get_blocked_accounts(limit)` | List all blocked accounts |
| `get_verified_followers(user_id, limit)` | Blue-verified followers |
| `get_user_likes(user_id, limit)` | A user's liked tweets |

---

## 🎛 Integrations

### Hermes Agent (Recommended)

Spectre was built for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Install the MCP server and skill for best results:

1. Add the MCP server to `~/.hermes/config.yaml`:
   ```yaml
   mcp_servers:
     spectre:
       command: "uvx"
       args: ["spectre-mcp"]
       timeout: 120
   ```
2. Install the skill (Hermes discovers skills at `~/.hermes/skills/<category>/<name>/SKILL.md`):
   ```bash
   mkdir -p ~/.hermes/skills/mcp/spectre
   cp SKILL.md ~/.hermes/skills/mcp/spectre/SKILL.md
   ```
3. Reload in your Hermes session:
   ```
   /reload-mcp
   /reload-skills
   ```

The skill gives Hermes full context on all 104 tools — parameter types, safe vs. destructive tools, usage patterns, and error handling.

### Claude Desktop

Add to `claude_desktop_config.json`:
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

Claude automatically discovers all 104 tools. No skill file needed — the tool descriptions are self-documenting.

### Cursor / Windsurf / Cline

Add to `.cursor/mcp.json` (or equivalent):
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

### Custom Integration (Python)

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server = StdioServerParameters(command="uvx", args=["spectre-mcp"])
async with stdio_client(server) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        # Use any of the 104 tools
```

---

## ⚠️ Safety Guide

Spectre marks every destructive tool with **⚠️**. Agents should respect these warnings.

### Always Confirm Before Calling

| Tool | Why |
|------|-----|
| `post_tweet` | Public, live immediately |
| `delete_tweet` | Permanent |
| `pin_tweet` | Replaces existing pin silently |
| `update_profile*` | Changes your public profile |
| `follow_user` / `unfollow_user` | Visible to the other user |
| `block_user` | Blocked user loses access to your content |
| `send_dm` | Sent immediately, no recall |
| `create_highlight` | Adds to your public profile |

### Safe to Use Freely (Read-Only)

All `get_*`, `search_*`, `list_*` tools. `pool_status`, `get_muted_accounts`, `get_blocked_accounts`, `get_scheduled_tweets`, `get_drafts`, `get_bookmarks`, `get_trends`, `get_home_timeline`, `get_notifications`.

### Rate Limits

- ~300 requests/hour/account
- Spectre auto-rotates to the next account on rate limits
- Use `set_auto_rotate(false)` to lock to a single account
- Rate limit errors include `retry_after_seconds`

---

## 🔍 X Query Operators

| Operator | Example | Description |
|----------|---------|-------------|
| `from:username` | `from:elonmusk` | Tweets by a user |
| `since:YYYY-MM-DD` | `since:2026-01-01` | After date |
| `until:YYYY-MM-DD` | `until:2026-06-01` | Before date |
| `#hashtag` | `#python` | Hashtag search |
| `filter:media` | `AI filter:media` | Only media tweets |
| `filter:links` | `AI filter:links` | Only tweets with links |
| `lang:en` | `AI lang:en` | Language filter |
| `min_retweets:N` | `AI min_retweets:100` | Minimum retweets |
| `min_faves:N` | `AI min_faves:50` | Minimum likes |
| `-"term"` | `AI -"GPT"` | Exclude term |
| `OR` | `python OR rust` | Either term |

---

## CLI

```bash
spectre add <username> <cookies>     Add account via browser cookies
spectre remove <username>            Remove an account
spectre list                         List all accounts
spectre status                       Pool health check
spectre serve                        Start MCP server (default)
spectre help                         Show help
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPECTRE_DB` | `~/.spectre/accounts.db` | Account pool database path |
| `SPECTRE_PROXY` | none | Global proxy (`socks5://user:pass@host:port`) |
| `TWS_HTTP_BACKEND` | `httpx` | Set to `curl_cffi` for TLS fingerprinting |
| `TWS_TELEMETRY` | `0` | Disable telemetry |
| `SPECTRE_OP_*` | built-in | Override GraphQL operation IDs (when they rotate) |

---

## Limitations

- **Authenticated accounts required** — X blocks unauthenticated access
- **Rate limited** — ~300 requests/hour/account (auto-rotation handles this)
- **~3200 tweet cap** on user timelines (X's own limit)
- **ToS risk** — automated access violates X's terms
- **Cookies expire** — re-add every ~2 weeks when searches return empty

---

## License

MIT
