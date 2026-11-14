# Changelog

All notable changes to `spectre-mcp`. Versioning is semver; the tool surface is
the public API.

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
