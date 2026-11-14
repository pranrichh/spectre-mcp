# Changelog

All notable changes to `spectre-mcp`. Versioning is semver; the tool surface is
the public API.

## 2.0.6 — 2026-11-14

- **Multi-account `doctor` was wrong.** It compared every pool account to a
  single identity, so with two accounts it told you to rename the healthy second
  one. Each account is now verified with its own cookies.
- **The shipped query-id table is current.** It was built from the live-probe
  results rather than X's bundle, so a fresh install immediately "updated" 43
  ids. `ops.py` is generated from the bundle now: a clean install starts at zero
  changes, and `tools/update_ops.py --check` fails if it ever drifts.
- **GraphQL is POST-only.** Some read operations (`SearchTimeline`,
  `UserTweetsAndReplies`) answer a bare 404 to GET while working over POST; the
  client no longer has two code paths to get wrong. The 404 ladder is: fresh
  transaction id, then the built-in id, then an actionable error.
- `doctor` no longer calls the DM-send operation "missing upstream" — it is not
  published in X's bundles and has a built-in id.
- `spectre add` prints `Saved under the handle (@x).`
- **Pool labels are local.** `spectre rename` updates the label in place (stats
  and cookies kept) and never touches X. `doctor` prints `@label (id) -> @handle
  on X` when they differ instead of suggesting a rename — a label does not have
  to match the account's handle.

## 2.0.5 — 2026-11-14

- **Highlights are back.** `create_highlight` and `delete_highlight` were dropped
  during the rewrite; both are restored against X's current mutations, with a
  clear `kind: permission` when the account is not eligible.
- **Notifications parse X's current shape.** The payload moved onto
  `itemContent` with the kind in `template.__typename` and the text in
  `rich_message`; the old `notificationType` field is gone. Both shapes are
  handled, with actors resolved from the rich-text entities.
- **DM timelines skip cursor rows.** Cursor entries no longer turn into blank
  messages that eat the page limit.
- `get_dm_conversation` validates `conversation_id` before putting it in a URL.

## 2.0.4 — 2026-11-14

`spectre doctor` keeps the query-id table current, plus a documentation pass.

- **`spectre doctor` refreshes X's GraphQL query ids.** It pulls the current
  bundle map, writes `~/.spectre/ops.json`, and every later process uses it — no
  release needed when X rotates ids. `--no-update` skips the fetch.
- If a refreshed id is rejected with "Query not found", the client retries with
  the built-in id instead of failing.
- README reads "100+ tools"; the tools table has one consistent shape.
- `docs/tools.md` opens with the Tools banner; `docs/integrations.md` covers
  OpenCode, OMP and DeepSeek Harness; Hermes is one client among others.
- `docs/safety.md` and the tool docstrings state what things do without the
  justification paragraphs.

## 2.0.3 — 2026-11-14

README: the tools table now uses one consistent shape — `Area | Tools | What
they cover`, with the call names in backticks on every row. No code changes.

## 2.0.2 — 2026-11-14

README: drop the "Call a tool" step from the quick start. IDs-as-strings is
covered in [docs/reference.md](docs/reference.md). No code changes.

## 2.0.1 — 2026-11-14

Documentation and listing refresh — no code changes.

- README back to the original layout, with the new logo, current tool count and a
  tools overview.
- `docs/safety.md` and `docs/reference.md` rewritten to be shorter and more
  practical: what to confirm, what each surface costs, what the limits are.
- PyPI listing now mirrors the GitHub README (absolute asset URLs), and the
  package description is the project tagline.

## 2.0.0 — 2026-11-14

A correctness release. Every write now verifies itself, every failure carries a
machine-readable `kind`, and the GraphQL operation table is generated from X's
live bundles instead of being hand-copied.

### Fixed — silent failures

- **Writes reported success no matter what X said.** `like`, `retweet`,
  `bookmark`, `pin`, `follow`, `mute`, `block`, list/community/topic mutations
  ignored the response. `like_tweet("1")` cheerfully returned `liked`. Every
  mutation now checks for the object it asked X to change and raises otherwise.
- **`delete_tweet` trusts X's empty payload.** X answers
  `{"delete_tweet":{"tweet_results":{}}}` even for posts you do not own. The
  tool now reads the post back and only claims deletion when it is gone.
- **31 stale GraphQL query ids.** Favoriters, SimilarPosts, Notifications,
  ListMemberships, ListOwnerships, MutedAccounts, BlockedAccountsAll,
  HomeTimeline, CreateList, UpdateList, ListAddMember/RemoveMember,
  ListSubscribe/Unsubscribe, JoinCommunity, and more were calling ids X no
  longer serves — returning empty results or `DecodeException`. `ops.py` is now
  generated from X's live bundles and verified against the API.
- **Bookmarks were broken in both directions.** `CreateBookmark` 404'd while
  reporting success, and the read path used an id that returned nothing. Now
  `BookmarkAdd`/`BookmarkDelete`/`Bookmarks`, verified by round-trip.
- **`get_bookmark_folders` swallowed an authorization error** and returned
  `{"folders": []}`. Premium-gated folders now surface `kind: permission`.
- **`get_account_settings` failed on renamed accounts** (`User @old not found`)
  because it looked up the handle stored at `spectre add` time. It now reads
  `Viewer` and flags `pool_username_stale`.
- **`Scraper.close()` crashed** with `AccountsPool has no attribute close`.

### Fixed — limits and pagination

- **`limit` was ignored** on twscrape-backed reads: `get_followers(limit=5)`
  returned 70. Limits are exact up to 5000, and long walks return
  `truncated: true` instead of running forever.
- **Rate-limited reads blocked for minutes.** twscrape implements waiting by
  sleeping inside its generator. Spectre now checks the account lock table and
  fails fast with `retry_after_seconds`.
- **Real account rotation.** `set_auto_rotate` claimed to switch accounts on a
  rate limit; nothing did. A 429 or dead cookie now parks that account and
  retries the call on the next active one.

### Fixed — parsing

- **Authors were `null`** on `get_home_timeline`, `get_user_highlights` and
  `get_user_tweets_and_replies` — the flattened `core` user shape was not
  handled.
- **Long-form posts were truncated** at `legacy.full_text`; `note_tweet` bodies
  are now returned in full.
- **`TweetWithVisibilityResults` and retweet wrappers** produced empty text.
- **User bios/websites vanished** on the new profile shape
  (`profile_bio`, `relationship_counts`) — only `legacy` was read.
- **`get_thread` mixed in promoted posts** from unrelated conversations.
- **Timestamps** are ISO-8601 everywhere (`get_scheduled_tweets` returned epoch
  milliseconds).

### Fixed — crashes and input handling

- `edit_scheduled_tweet` raised an uncaught `ValueError` on a bad datetime;
  datetimes are validated in both schedule tools.
- `withSuperFollowsUserFields`, `conversationId`, `target_user_id`,
  `bookmark_collection_id`, `tweet_id` (delete-highlight) and DM search flags
  were missing from mutation variables, producing `GRAPHQL_VALIDATION_FAILED`.
- `subscribe_list`/`unsubscribe_list` read the wrong response key and reported
  failure on success.
- `pin_reply`/`unpin_reply` now derive `conversation_id` when it is not given.
- Media upload ignores X's `202` on INIT, splits at 4 MiB, and polls video
  processing with a bounded loop.

### Added — 8 tools (111 total)

- `get_me` — the live identity of the session (and stale-handle detection).
- `get_user_by_id`, `get_users_by_ids` — ids turn up everywhere; handles do not.
- `get_tweets` — batch fetch by id, one call.
- `get_tweet_quotes` — quote posts, which is where commentary lives.
- `download_media` — pull a post's media to disk.
- `get_rate_limits` — per-account locks and last rate-limit headers.
- `get_list_info` — name, counts, owner, privacy of a list.
- `get_trend_locations` — woeids for `get_trends`.

### Changed — behaviour

- **Output IDs are strings**, matching the input contract. Shapes are identical
  across GraphQL and twscrape paths (`id`, `author_username`, `like_count`, …).
- `get_followers` / `get_following` return
  `{users, count, truncated, total_available}` instead of a bare list.
- `get_trends(category=…)` is gone: X's REST endpoint takes a `woeid`, so the
  tool is now `get_trends(woeid=1, limit=…)`. The old `category` argument never
  did anything.
- `delete_draft(draft_id=…)` and `delete_scheduled_tweet(scheduled_id=…)` use
  the same parameter names as their edit counterparts.
- Errors are `{"error", "kind", "hint"}` with `kind` in
  `auth | rate_limit | permission | validation | not_found | upstream`.
- `spectre add` verifies the cookies with X, stores the account's **real**
  handle, and prints nothing from twscrape.
- New `spectre doctor` and `spectre rename`; `spectre --version`.

### Docs

- New white-on-black ghost-X logo, README rebuilt, `SKILL.md` rewritten as an
  agent decision guide instead of an API dump, `docs/tools.md` generated from
  the registry (`tools/gen_docs.py --check` fails CI when they drift).

## 1.0.4 — unreleased

- Type X id parameters as strings to stop 2^53 precision loss.

## 1.0.3

- Fix `get_verified_followers` returning null usernames.

## 1.0.2

- Fix server crash on `last_used='0'` (`Invalid isoformat string`).

## 1.0.1

- Six minor fixes.

## 1.0.0

- First release: 104 tools.
