<p align="center">
  <img src="../assets/headers/reference.svg" alt="Reference" />
</p>

# Reference

## X query operators

`search()` passes your query straight to X, so the whole operator language works:

| Operator | Example | What it does |
|--|--|--|
| `from:` / `to:` | `from:elonmusk` | Posts by / replies to a handle |
| `since:` / `until:` | `since:2026-01-01` | Date range (`YYYY-MM-DD`) |
| `#tag` / `$cashtag` | `#python` | Hashtag or cashtag |
| `filter:media` | `ai filter:media` | Only posts with media |
| `filter:links` | `ai filter:links` | Only posts with links |
| `filter:replies` | `ai filter:replies` | Include replies |
| `filter:follows` | `ai filter:follows` | Only accounts you follow |
| `lang:` | `ai lang:en` | Language |
| `min_retweets:` / `min_faves:` | `ai min_faves:100` | Engagement floor |
| `-"term"` | `ai -"gpt"` | Exclude |
| `OR` | `python OR rust` | Either |
| `quoted_tweet_id:` | `quoted_tweet_id:2111...` | Quotes of one post (`get_tweet_quotes` uses this) |

## CLI

```bash
spectre add <name> "<auth_token=...; ct0=...>"   verify + add an account
spectre remove <name>                            drop an account
spectre list                                     accounts and state
spectre status                                   pool health (exit 1 if none active)
spectre rename <old> <new>                       fix a handle after a rename, keep cookies
spectre doctor                                   auth + connectivity check
spectre serve                                    start the MCP server (default)
spectre --version
```

`add` verifies the cookies with X before saving them and keeps the account's real
handle, so a renamed account keeps working. `doctor` is the first thing to run
when something looks wrong:

```text
spectre doctor  v2.0.1
db      /home/you/.spectre/accounts.db
pool    1 account(s): @handle
✓ auth    @handle (1234567890)
✓ profile ok
✓ timeline ok
✓ search  ok
ops     90 operations loaded - override any with SPECTRE_OP_<NAME>
✓ done
```

## Environment variables

| Variable | Default | Purpose |
|--|--|--|
| `SPECTRE_DB` | `~/.spectre/accounts.db` | Account pool database |
| `SPECTRE_PROXY` | none | Global proxy (`http://user:pass@host:port`) |
| `SPECTRE_OP_<NAME>` | built-in | Override one GraphQL query id, e.g. `SPECTRE_OP_CREATETWEET` |
| `SPECTRE_LOG_LEVEL` | `ERROR` | `DEBUG` for request logs, `OFF` for silence |
| `TWS_HTTP_BACKEND` | `httpx` | `curl_cffi` for TLS fingerprinting on reads |
| `TWS_TELEMETRY` | `0` | Disabled by default |

## Output shapes

Reads return the same shapes whether the data came from GraphQL or twscrape.

**Tweet**

```json
{
  "id": "2121388517540716839",
  "url": "https://x.com/elonmusk/status/2121388517540716839",
  "text": "full text, including long-form posts",
  "author_id": "44196397", "author_username": "elonmusk", "author_name": "Elon Musk",
  "created_at": "2026-11-13T23:43:30+00:00", "lang": "en",
  "reply_count": 4069, "retweet_count": 6618, "like_count": 60118,
  "quote_count": 646, "view_count": 4592980, "bookmark_count": 2620,
  "is_retweet": false, "is_quote": false, "is_reply": false,
  "in_reply_to_id": null, "conversation_id": "2121388517540716839",
  "media_urls": ["https://video.twimg.com/..."], "media_types": ["video"],
  "hashtags": [], "urls": [], "mentioned_users": [],
  "quoted_tweet_id": null, "quoted_tweet": null, "retweeted_tweet_id": null
}
```

**User**

```json
{
  "id": "44196397", "username": "elonmusk", "display_name": "Elon Musk",
  "bio": "...", "location": "...", "website": "...",
  "followers": 240919353, "following": 1425, "tweets": 112085,
  "likes": 258295, "media_count": 4772,
  "verified": false, "blue_verified": true,
  "profile_image_url": "...", "banner_url": "...",
  "created_at": "2009-06-02T20:12:29+00:00", "protected": false
}
```

IDs are strings on the way out too — echo them back as-is.

## Errors

```json
{
  "error": "Rate limited on SearchTimeline",
  "kind": "rate_limit",
  "retry_after_seconds": 420,
  "hint": "Wait 420s, or add another account (spectre add ...)."
}
```

| `kind` | Meaning | What to do |
|--|--|--|
| `auth` | Cookies dead, account locked or suspended | re-add the account |
| `rate_limit` | Wait for the window, or switch accounts | retry after `retry_after_seconds` |
| `permission` | X refuses for this account (Premium, privacy, blocked) | don't retry; tell the user |
| `validation` | Bad input: id, datetime, length | fix the argument |
| `not_found` | Post/user/list gone | check the id |
| `upstream` | X returned something unusable | retry once, then report |

## Pagination

List-shaped tools return `next_cursor`; pass it back as `cursor`:

```python
page = get_bookmarks(limit=100)
page2 = get_bookmarks(limit=100, cursor=page["next_cursor"])
```

`get_followers` / `get_following` walk up to 5000 and set `truncated: true` when the time budget stops them early.

## Limits worth knowing

- **Likes are private by default.** `get_user_likes` is empty for most accounts.
- **Who-liked lists are restricted** on large posts, so `get_favoriters` often returns nothing.
- **Similar posts and bookmark folders need Premium** → `kind: permission`.
- **List memberships** (`get_list_memberships`) is unreliable upstream and often empty.
- **DM history** is whatever X serves the cookie session; older messages can be missing.
- **~3,200-post cap** on user timelines — use `search("from:… since:…")` for older posts.
- **Notifications** only reflect activity on the authenticated account.
- **One call, one page:** search returns ~20 results per request, so a high `limit` costs several requests.
