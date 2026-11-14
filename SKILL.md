---
name: spectre
description: "Use when a task involves X/Twitter: search posts, read a profile or timeline, post/reply/quote, upload media, send DMs, manage lists, bookmarks, communities, or scheduled posts. Spectre is the MCP server for all X work."
metadata:
  hermes:
    tags: [twitter, x, mcp, social-media, automation, research]
    category: mcp
    related_skills: []
---

# Spectre — X/Twitter for agents

Spectre is not "a Twitter API". It is a live authenticated session on X, with
111 tools, and it will happily post, DM or delete on your behalf. The skill of
using it is knowing **which call answers the question**, **what it costs**, and
**when to stop and ask the user**.

Repo: <https://github.com/pranrichh/spectre-mcp> · tool reference:
`docs/tools.md` in that repo.

## Before anything else

1. `get_me()` — confirms which account is live and returns its real handle. Do
   this once per session; every write lands on this account.
2. If it errors with `kind: auth`, the cookies are dead. That is a user action
   (`spectre add ...`), not something to retry.

Never assume an account: the pool may hold several, and `set_active_account`
decides which one acts.

## Choosing a tool

Start from the question, not the tool list.

| The user wants | Reach for | Why not the obvious alternative |
|--|--|--|
| "what are people saying about X" | `search(q, mode="latest")` | `get_home_timeline` is the algorithm, not the topic |
| "what did this person say" | `get_user_tweets` / `get_user_tweets_and_replies` | search with `from:` is for date ranges and filters |
| "find the person behind this" | `get_user` (handle) or `get_user_by_id` (numeric id) | never guess a handle from a display name |
| "who is this audience" | `get_followers` with a real limit + `get_verified_followers` | walking 100k followers is a rate-limit bonfire |
| "what is the reaction" | `get_tweet_quotes` → `get_tweet_replies` | replies are dominated by bots and "first" |
| "summarise this thread" | `get_thread` (oldest first, conversation only) | `get_tweet` gives one post, not the story |
| "is this still true" | `get_tweets` on the ids already collected | re-running search burns the expensive quota |
| "post this" | `upload_media` → `post_tweet(media_ids=...)` | posting then editing is not a thing on X |
| "DM this person" | `get_user` → `send_dm(user_id, text)` | `send_dm` needs the numeric id, not the handle |
| "clean up my timeline" | `get_muted_accounts`, `get_blocked_accounts`, `get_bookmarks` | these are reads; the clean-up itself is a write |
| "what's trending" | `get_trends(woeid=1)` (worldwide) or `get_trend_locations` | search "trending" returns noise |

If a read comes back empty, check *why* before retrying: `get_user_likes`
(privacy), `get_favoriters` (restricted), bookmark folders and
`get_similar_posts` (Premium), `get_list_memberships` (X returns nothing for
many accounts). An empty list with a `note` is an answer; do not loop on it.

## Non-negotiables

**IDs are strings.** Every id argument takes a numeric string or an
`https://x.com/...` URL; pass ids back exactly as the tools return them.

**Resolve before you act.** Follow, block, mute, DM and user-likes take
`user_id`; get it from `get_user` once and keep it. Post operations take
`tweet_id` from search/timeline results.

**Confirm every write in this conversation.** Posting, DMs, follows, blocks,
deletes, profile edits, scheduled posts. `post_tweet` is public in under a
second and `pin_tweet` silently replaces the old pin. The full tiered list is
`docs/safety.md`; the short version is: if it changes state on X, ask first.

**Media goes up before the post exists.** `upload_media(path)` → `media_id` →
`post_tweet(text, media_ids="id")`. Multiple ids are comma-separated. An INIT
202 is normal, not a failure.

## Cost model

Rate limit is the real budget, and it is per account.

- Reads: ~300 requests / 15 min. One page ≈ one request.
- **Search: ~50 / 15 min — the scarce resource.** Prefer `get_user_tweets`,
  `get_thread` and `get_tweets` over re-running searches.
- Fans-outs (`get_followers`, `get_following`) walk many pages: ask for the
  limit you need (`limit=500` not `limit=5000`), and expect `truncated: true`
  when the time budget runs out.
- Writes: generous, but new accounts and replies to strangers get throttled
  harder than the numbers suggest.
- `get_rate_limits()` before a bulk job; a `kind: rate_limit` error carries
  `retry_after_seconds` — wait it out or switch accounts, do not hammer.

Batch reads: `get_tweets("id1,id2,id3")` and `get_users_by_ids("a,b")` cost one
call instead of N.

## When it fails

Errors come back as `{"error", "kind", "hint"}`. Branch on `kind`:

- `rate_limit` → wait `retry_after_seconds`, or `set_active_account` to another
  account. Retrying immediately makes it worse.
- `auth` → cookies are dead. Tell the user to run `spectre add`; do not retry.
- `permission` → X refuses for this account (Premium gate, privacy, you are
  blocked). Not fixable by retrying; report it.
- `validation` → the argument is wrong: bad id, bad datetime, tweet too long
  (280 standard / 25,000 Premium), duplicate text, bio containing `< > &`.
- `not_found` → the post/user is gone. If *every* read fails this way, either
  the cookies are stale or the query ids rotated: run `spectre doctor`, which
  re-checks the account and pulls the current query ids from X's bundles.
- `upstream` → X returned something unusable. One retry, then report.

Never convert an error into a success story in your summary. "Posted" means
`post_tweet` returned a `tweet_id`; "deleted" means the tool verified the post
is gone.

## Recipes

**Research one account.** `get_user(handle)` → `get_user_tweets(limit=50)` →
`get_user_tweets_and_replies(limit=50)` → `get_user_media` if visuals matter →
`get_followers_you_know` for warm intros → `get_user_likes` (often hidden,
that is normal).

**Map an audience.** `get_followers(handle, limit=1000)` → sort by `followers`
→ `get_verified_followers` for the credible slice. Long pulls get
`truncated: true`; say so rather than claiming full coverage.

**Follow a developing story.** `search(q, mode="latest")` for the sweep →
`get_thread` on the two or three posts that matter → `get_tweet_quotes` for
commentary. Re-run with `since:` rather than re-reading everything.

**Post something with media.** `upload_media(path)` → `post_tweet(text,
media_ids=id)` → report the returned `url`. To reply or quote, pass `reply_to` /
`quote_tweet` (never both — the tool rejects it).

**Schedule instead of posting now.** `schedule_tweet(text, execute_at)` with
ISO-8601 (`2026-12-01T12:00:00Z`); list with `get_scheduled_tweets`, cancel
with `delete_scheduled_tweet`. Times are UTC unless the string carries an
offset.

**Triage notifications.** `get_notifications(limit=50)` → group by `type` →
reply only where a human reply is warranted. `mentions` and `replies` are the
actionable ones; likes and follows are not.

**Full follower export.** `get_followers(handle, limit=5000)` walks X's cursor and
returns `count`, `truncated` and `total_available`, so you can report coverage
honestly ("1,000 of 48,211") instead of implying a full scan. For a complete pull
of a very large account, call it in slices and keep the returned users in a file
between calls.

## Things that bite

- **Cookies expire ~2 weeks.** First symptom is empty searches, not an error.
  `spectre doctor` proves it, and refreshes the GraphQL query ids while it runs.
- **`ct0` must be 160 hex chars.** Partial cookies look fine and fail silently.
- **Stored handles go stale.** If the account was renamed, `get_me` shows the
  real handle and `get_account_settings` flags `pool_username_stale`; fix with
  `spectre rename <old> <new>`.
- **Delete verification is real.** `delete_tweet` reads the post back; a
  "still readable" error means it was not yours to delete.
- **DM history is partial by design.** X serves the cookie session a window of
  messages; if a reply the user can see in the browser is missing, say so —
  never invent its content.
- **Bookmark folders and similar posts are Premium.** `kind: permission` or a
  `note`, not a bug.
- **`get_trends` needs a woeid**, not a country name. Look it up with
  `get_trend_locations`.
- **The tool count changes with releases.** Do not hardcode a count in answers;
  the registry is the truth.

## Safety line

Spectre is an authenticated session, not a scraper toy. Do not use it to
harass, mass-follow, spam DMs, or evade a block. When the user asks for
something that reads as astroturfing, say what the tools would actually do
(rate limits, account bans, visibility) before doing it.
