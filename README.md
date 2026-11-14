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
  <a href="#quick-start">Quick Start</a> ·
  <a href="docs/tools.md">Tools</a> ·
  <a href="#why-spectre">Why Spectre?</a> ·
  <a href="docs/safety.md">Safety</a> ·
  <a href="docs/integrations.md">Integrations</a> ·
  <a href="docs/reference.md">Reference</a>
</p>

---

Spectre is an MCP server that gives AI agents 111 tools for X/Twitter: search,
timelines, profiles, posting, media, DMs, lists, bookmarks, communities,
notifications, scheduled posts and account management.

Under the hood it talks straight to X's internal GraphQL and REST APIs with the
cookies you already have. No browser to boot, no Puppeteer to babysit, no DOM
scraping that dies when the UI changes.

<a id="why-spectre"></a>

## Why Spectre?

| | **Spectre** | Browser agents | API wrappers |
|--|:-:|:-:|:-:|
| **Transport** | Direct GraphQL/REST | Headless Chromium | GraphQL (single session) |
| **Per call** | < 1s | 3–10s (browser startup) | ~1s |
| **Memory** | ~10 MB | 200 MB+ | ~10 MB |
| **MCP server** | ✓ 111 tools | ad-hoc scripts | ✗ |
| **Account pool** | ✓ real rotation on 429 | ✗ | ✗ |
| **Error contract** | ✓ structured `kind` + `hint` | ✗ | ✗ |
| **Pagination** | ✓ cursors on list endpoints | ✗ | partial |
| **Media upload** | ✓ cookie auth, no API keys | slow | needs keys |
| **Language** | Python | JS | Python |

What changed in 2.0, and why it matters:

- **Every write verifies itself.** X answers HTTP 200 with an `errors` array
  often enough that "no exception" means nothing. 31 GraphQL query ids had
  silently drifted; the ones Spectre uses are now generated from X's live
  bundles and verified against the API.
- **Errors are structured.** `{"error", "kind", "hint"}` with `kind` in
  `auth · rate_limit · permission · validation · not_found · upstream`, so an
  agent can retry, switch accounts, or stop — instead of guessing.
- **Rotation is real.** A 429 or a dead cookie parks that account and retries
  the call on the next one.
- **Limits are honoured.** `limit=5000` returns 5000 followers, not the first
  page. Long walks return `truncated: true` instead of hanging.
- **New in 2.0:** `get_me`, `get_user_by_id`, `get_users_by_ids`, `get_tweets`,
  `get_tweet_quotes`, `download_media`, `get_rate_limits`, `get_list_info`,
  `get_trend_locations`.

<a id="quick-start"></a>

## Quick Start

### 1. Install

```bash
pipx install spectre-mcp     # or: uv tool install spectre-mcp
```

### 2. Add your X account

Log into x.com, open DevTools (`F12`) → **Application** → **Cookies** →
`https://x.com`, and copy two values:

| Cookie | Looks like |
|--|--|
| `auth_token` | a long hex string |
| `ct0` | exactly 160 hex characters |

```bash
spectre add myaccount "auth_token=...; ct0=..."
```

Spectre checks the cookies against X before saving and stores the account's
**real** handle — so a renamed account still works. Bad cookies are rejected on
the spot instead of failing silently weeks later.

```bash
spectre list      # accounts and their state
spectre status    # pool health
spectre doctor    # auth + operation-table check
```

### 3. Point your MCP client at it

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

Works with Hermes (`~/.hermes/config.yaml`), Claude Desktop
(`claude_desktop_config.json`), Cursor (`.cursor/mcp.json`) — see
[Integrations](docs/integrations.md).

### 4. Call a tool

IDs are **strings** (or full `https://x.com/...` URLs), never JSON numbers:

```python
get_me()                                    # which account is live
search("mcp server", limit=20, mode="latest")
get_user("elonmusk")                        # -> id for follow/block/DM
post_tweet("hello from an agent")
```

X IDs are 64-bit and overflow the IEEE-754 safe range (2^53). A client that
parses JSON numbers as doubles turns `2111332908657148356` into
`2111332908657148416` and the tool reports a perfectly good post as "not
found". Strings never round-trip through a float.

---

## What's in the box

| Area | Tools |
|--|--|
| Accounts | `get_me`, `list_accounts`, `pool_status`, `set_active_account`, `set_auto_rotate`, `get_rate_limits`, `remove_account` |
| Search | `search` (full operator syntax), `search_users` |
| Profiles | `get_user`, `get_user_by_id`, `get_users_by_ids`, `get_user_tweets`, `get_user_tweets_and_replies`, `get_user_media`, `get_followers`, `get_following`, `get_verified_followers`, `get_followers_you_know`, `get_user_likes`, `get_user_highlights` |
| Posts | `get_tweet`, `get_tweets`, `get_tweet_replies`, `get_thread`, `get_tweet_quotes`, `get_retweeters`, `get_favoriters`, `get_tweet_edit_history`, `get_similar_posts`, `get_community_notes` |
| Compose | `post_tweet`, `delete_tweet`, `upload_media`, `download_media`, `schedule_tweet` (+CRUD), `create_draft` (+CRUD) |
| Engagement | `like_tweet`, `unlike_tweet`, `retweet`, `unretweet`, `bookmark_tweet`, `unbookmark_tweet`, `pin_tweet`, `unpin_tweet`, `pin_reply`, `unpin_reply` |
| Social | `follow_user`, `unfollow_user`, `mute_user`, `unmute_user`, `block_user`, `unblock_user`, `remove_follower`, `get_muted_accounts`, `get_blocked_accounts` |
| DMs | `send_dm`, `get_dm_inbox`, `get_dm_conversation`, `search_dm`, `search_dm_groups`, `search_dm_people`, `get_dm_muted`, `dm_block_user`, `dm_unblock_user` |
| Lists | `get_list_info`, `create_list`, `update_list`, `delete_list`, `add_list_member`, `remove_list_member`, `get_list_members`, `get_list_timeline`, `get_list_subscribers`, `get_list_memberships`, `get_list_ownerships`, `subscribe_list`, `unsubscribe_list` |
| Communities & topics | `get_community_info`, `get_community_tweets`, `join_community`, `leave_community`, `get_topic_info`, `follow_topic`, `unfollow_topic`, `get_trends`, `get_trend_locations` |
| Bookmarks | `get_bookmarks`, `search_bookmarks`, `clear_all_bookmarks`, folder CRUD + folder timeline |
| Notifications | `get_notifications`, `get_home_timeline` |
| Profile | `get_account_settings`, `update_profile`, `update_profile_image`, `update_profile_banner`, `delete_profile_banner`, `rate_community_note` |

Full reference with arguments and gotchas: **[docs/tools.md](docs/tools.md)**.

---

## Safety

Posting, DMs, follows, blocks, deletes and profile edits are public and mostly
irreversible. Spectre labels them in [docs/safety.md](docs/safety.md); the
agent-side rule is simple: **confirm with the user before any write.**

Rate limits are per account (~50 searches / 15 min, ~300 requests / 15 min on
reads). The pool rotates automatically; `get_rate_limits()` tells you when the
next window opens.

Automated access violates X's Terms of Service. You are responsible for the
account you point this at.

## Development

```bash
git clone https://github.com/pranrichh/spectre-mcp
cd spectre-mcp
uv sync
.venv/bin/python tools/gen_docs.py --check    # fails if docs/tools.md drifted
.venv/bin/python -m pytest tests -q             # parser tests
.venv/bin/python tools/update_ops.py GraphQL.json   # refresh query ids
```

Query ids drift every few weeks. `tools/update_ops.py` regenerates
`src/spectre/ops.py` from
[fa0311/TwitterInternalAPIDocument](https://github.com/fa0311/TwitterInternalAPIDocument);
`SPECTRE_OP_<NAME>` overrides a single operation at runtime.

## License

MIT
