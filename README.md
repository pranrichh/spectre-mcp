<p align="center">
  <img src="https://raw.githubusercontent.com/pranrichh/spectre-mcp/main/assets/spectre-logo.png" width="180" alt="Spectre" />
</p>

<h1 align="center">Spectre MCP</h1>

<p align="center">
  <em>The fastest X/Twitter automation for AI agents.</em>
</p>

<p align="center">
  111 tools · no browser · no API keys · no monthly fees
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> · <a href="docs/tools.md">Tools</a> · <a href="#why-spectre">Why Spectre?</a> · <a href="docs/safety.md">Safety</a> · <a href="docs/integrations.md">Integrations</a> · <a href="docs/reference.md">Reference</a>
</p>

---

<a id="why-spectre"></a>

<p align="center">
  <img src="https://raw.githubusercontent.com/pranrichh/spectre-mcp/main/assets/headers/why.svg" alt="Why Spectre?" />
</p>

Spectre is an MCP server that gives AI agents 111 tools for X/Twitter — from search and posting to DMs, lists, and communities. Under the hood, it talks directly to X's internal GraphQL and REST APIs. No browser to spin up, no Puppeteer to maintain, no DOM scraping that breaks on UI changes.

| | **Spectre** | **XActions** | **twikit** |
|--|:-:|:-:|:-:|
| **Architecture** | Direct GraphQL/REST | Puppeteer (headless browser) | Python API wrapper |
| **Speed** | <1s per request | 3–10s (browser startup) | ~1s per request |
| **Memory** | ~10 MB | ~200 MB+ (Chromium) | ~10 MB |
| **MCP Server** | ✓ 111 tools | ~50 API tools | ✗ None |
| **Account Pool** | ✓ Multi-account rotation | ✗ Single auth_token | ✗ Single session |
| **Browser Required** | ✗ Never | ✓ Always | ✗ Never |
| **DOM Breakage Risk** | ✗ None | ~ breaks on UI changes | ✗ None |
| **Pagination** | ✓ Cursors on list endpoints | ✗ | partial |
| **Media Upload** | ✓ Cookie-based (no API keys) | ~ requires API keys | ✗ |
| **Lists** | ✓ Full CRUD + members + subscribe | ✗ | ✗ |
| **Drafts & Scheduled** | ✓ Full CRUD | ~ Basic | ✗ |
| **Bookmark Folders** | ✓ Full CRUD + timeline | ✗ | ✗ |
| **DM Search** | ✓ All / groups / people | ✗ | ✗ |
| **Quote Tweets** | ✓ Full timeline | ✗ | ✗ |
| **Community Notes** | ✓ Read + rate | ✗ | ✗ |
| **Highlights** | ✓ Create, delete, get | ✗ | ✗ |
| **Notifications** | ✓ Full timeline | ✗ | ✗ |
| **Language** | Python | JavaScript | Python |

Every tool returns the same clean JSON shapes, and failures carry a `kind` (`auth`, `rate_limit`, `permission`, `validation`, `not_found`, `upstream`) so your agent knows whether to retry, switch accounts, or stop.

---

<a id="quick-start"></a>

<p align="center">
  <img src="https://raw.githubusercontent.com/pranrichh/spectre-mcp/main/assets/headers/quickstart.svg" alt="Quick Start" />
</p>

### 1. Install

```bash
pipx install spectre-mcp    # or: uv tool install spectre-mcp
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

Spectre checks the cookies with X before saving them, so a bad copy fails immediately instead of at the first empty search.

> **Tip:** `ct0` is exactly 160 hex characters. Double-check you copied the full value.

Handy commands:

```bash
spectre list      # accounts and their state
spectre status    # pool health
spectre doctor    # auth + connectivity check
```

### 3. Configure Your MCP Client

Add to your MCP client config (`~/.hermes/config.yaml`, `claude_desktop_config.json`, `.cursor/mcp.json`, or equivalent):

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

For client-specific setup (Hermes skill, Claude, Cursor, Python), see [Integrations](docs/integrations.md).

> **No `uv`?** Install it: `curl -LsSf https://astral.sh/uv/install.sh | sh`
> Or use `python3 -m spectre.server` to run from a local clone.

---

<p align="center">
  <img src="https://raw.githubusercontent.com/pranrichh/spectre-mcp/main/assets/headers/tools.svg" alt="Tools" />
</p>

## What You Get

| Area | Tools | What they cover |
|--|--|--|
| **Search** | `search`, `search_users` | full operator syntax: `from:`, `since:`, `filter:media`, `min_faves:`, `lang:` |
| **Profiles** | `get_user`, `get_user_by_id`, `get_users_by_ids`, `get_user_tweets`, `get_followers`, `get_following` | timelines, media, up to 5,000 followers/following, verified followers, mutuals, likes, highlights |
| **Posts** | `get_tweet`, `get_tweets`, `get_thread`, `get_tweet_quotes`, `get_tweet_replies` | batch fetch, quote timelines, retweeters, favoriters, edit history, similar posts, community notes |
| **Compose** | `post_tweet`, `upload_media`, `download_media`, `schedule_tweet`, `create_draft` | text, replies, quotes, media, scheduling, drafts |
| **Engagement** | `like_tweet`, `retweet`, `bookmark_tweet`, `pin_tweet`, `pin_reply` | each one has its undo |
| **Social** | `follow_user`, `unfollow_user`, `mute_user`, `block_user`, `remove_follower` | plus muted and blocked lists |
| **DMs** | `send_dm`, `get_dm_inbox`, `get_dm_conversation`, `search_dm` | search across all / groups / people, muted threads, DM block |
| **Lists** | `create_list`, `update_list`, `add_list_member`, `get_list_timeline`, `subscribe_list` | members, subscribers, memberships, ownerships |
| **Communities** | `get_community_info`, `get_community_tweets`, `join_community`, `leave_community` | info, posts, join, leave |
| **Topics & trends** | `get_topic_info`, `follow_topic`, `get_trends`, `get_trend_locations` | topics, trends by location, woeid lookup |
| **Bookmarks** | `get_bookmarks`, `search_bookmarks`, `get_bookmark_folders`, `get_bookmark_folder_timeline` | list, search, folders, folder timeline |
| **Account** | `get_me`, `get_account_settings`, `update_profile`, `get_rate_limits` | settings, profile edits, avatar, banner, pool management |

Full list with arguments and gotchas: **[docs/tools.md](docs/tools.md)**.

---

<p align="center">
  <img src="https://raw.githubusercontent.com/pranrichh/spectre-mcp/main/assets/headers/reference.svg" alt="Reference" />
</p>

- [All 111 Tools](docs/tools.md) — every tool, grouped by feature
- [Integrations](docs/integrations.md) — Hermes, Claude, Cursor, Python
- [Safety](docs/safety.md) — what to confirm before writing, and rate limits
- [Reference](docs/reference.md) — X query operators, CLI, env vars, output shapes, limitations
- [Changelog](CHANGELOG.md) — what changed between versions

---

## License

MIT
