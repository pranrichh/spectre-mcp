<p align="center">
  <img src="../assets/headers/safety.svg" alt="Safety" />
</p>

# Safety

Spectre can act as you on X. Nothing here is theoretical: a wrong call is a
public post, a DM to a stranger, or a deleted thread.

## The one rule

**Confirm with the user in this conversation before any write.** Not "the user
asked for a Twitter bot once" — the specific action, right now.

## Writes, ranked by how badly they go wrong

| Tier | Tools | Why |
|--|--|--|
| **Permanent** | `delete_tweet`, `delete_draft`, `delete_scheduled_tweet`, `delete_list`, `delete_bookmark_folder`, `delete_profile_banner`, `clear_all_bookmarks`, `remove_account` | No undo exists |
| **Public** | `post_tweet`, `retweet`, `follow_user`, `unfollow_user`, `block_user`, `unblock_user`, `mute_user`, `unmute_user`, `remove_follower`, `pin_tweet`, `pin_reply`, `create_highlight` | Visible to others immediately |
| **Irreversible message** | `send_dm`, `dm_block_user`, `dm_unblock_user` | No recall; may be someone's first impression |
| **Identity** | `update_profile`, `update_profile_image`, `update_profile_banner` | Changes who you appear to be |
| **Deferred** | `schedule_tweet`, `delete_scheduled_tweet`, `edit_scheduled_tweet`, `create_draft`, `edit_draft` | Fires later, without you |
| **Reversible** | `like_tweet`/`unlike_tweet`, `bookmark_tweet`/`unbookmark_tweet`, `subscribe_list`/`unsubscribe_list`, `join_community`/`leave_community` | Undo tools exist |

`pin_tweet` deserves its own warning: X keeps exactly one pinned post, so
pinning replaces the previous one silently.

## Read-only (safe in bulk)

`get_*`, `search`, `search_users`, `list_accounts`, `pool_status`,
`get_rate_limits`, `get_trends`, `get_home_timeline`, `get_notifications`,
`get_muted_accounts`, `get_blocked_accounts`, `get_scheduled_tweets`,
`get_drafts`, `get_bookmarks`, `get_dm_*`, `search_dm*`.

Even these cost rate limit, which is the real budget in any bulk job.

## Rate limits

| Surface | Approx. limit |
|--|--|
| Reads (`TweetDetail`, `UserTweets`, ...) | ~300 requests / 15 min / account |
| Search | ~50 requests / 15 min / account (the tight one) |
| Writes (post, like, follow) | a few hundred / day, and X throttles new accounts harder |
| DMs | ~500 / day, plus per-recipient limits |

What Spectre does about it:

- before a paginated read, it checks the account's lock table and fails fast
  with `kind: rate_limit` and `retry_after_seconds` instead of sleeping;
- on HTTP 429 from GraphQL it benches that account and retries the call on the
  next active one (`set_auto_rotate(false)` disables that);
- `get_rate_limits()` shows the locks and the last `x-rate-limit-*` headers.

Two or three accounts absorb a normal day of work. Cookies expire roughly every
two weeks — `spectre doctor` tells you when they stop authenticating.

## What Spectre will not do

- It does not solve captchas, create accounts, or evade bans.
- It does not scrape logged-out pages.
- It will not touch a post it cannot verify it deleted, and it reports
  `kind: permission` rather than pretending a Premium-only action worked.

Automated access violates X's Terms of Service. The account, and the
consequences, are yours.
