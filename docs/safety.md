<p align="center">
  <img src="../assets/headers/safety.svg" alt="Safety" />
</p>

Spectre acts as you on X: a wrong call is a public post, a DM to a stranger, or a deleted thread.

## Confirm before writing

Before any write, get the user's explicit OK for that specific action — not "they asked for a Twitter bot once".

## Writes, by how hard they are to undo

| Tier | Tools | Why |
|--|--|--|
| **Permanent** | `delete_tweet`, `delete_draft`, `delete_scheduled_tweet`, `delete_list`, `delete_bookmark_folder`, `delete_profile_banner`, `clear_all_bookmarks`, `remove_account` | No undo |
| **Public** | `post_tweet`, `retweet`, `follow_user`, `unfollow_user`, `block_user`, `unblock_user`, `mute_user`, `unmute_user`, `remove_follower`, `pin_tweet`, `pin_reply`, `create_highlight` | Visible to others immediately |
| **Message** | `send_dm`, `dm_block_user`, `dm_unblock_user` | No recall |
| **Identity** | `update_profile`, `update_profile_image`, `update_profile_banner` | Changes how you appear |
| **Deferred** | `schedule_tweet`, `edit_scheduled_tweet`, `delete_scheduled_tweet`, `create_draft`, `edit_draft` | Runs later, without you |
| **Reversible** | `like`/`unlike`, `bookmark`/`unbookmark`, `subscribe_list`/`unsubscribe_list`, `join_community`/`leave_community` | Undo tools exist |

`pin_tweet` deserves its own warning: X keeps exactly one pinned post, so pinning replaces the previous one silently.

## Read-only

`get_*`, `search`, `search_users`, `list_accounts`, `pool_status`, `get_rate_limits`, `get_trends`, `get_home_timeline`, `get_notifications`, `get_muted_accounts`, `get_blocked_accounts`, `get_scheduled_tweets`, `get_drafts`, `get_bookmarks`, `get_dm_*`, `search_dm*`.

These still cost rate limit, which is the real budget in a bulk job.

## Rate limits

| Surface | Approx. limit |
|--|--|
| Reads (`TweetDetail`, `UserTweets`, …) | ~300 requests / 15 min / account |
| Search | ~50 requests / 15 min / account |
| Writes (post, like, follow) | a few hundred / day; new accounts are throttled harder |
| DMs | ~500 / day, plus per-recipient limits |

Before a paginated read, Spectre checks the account's lock table and returns `kind: rate_limit` with `retry_after_seconds`. On a 429 it benches that account and retries on the next active one; `set_auto_rotate(false)` keeps every call on one account. `get_rate_limits()` shows the locks and the last `x-rate-limit-*` headers.

Two or three accounts comfortably cover a normal day of work. Cookies last about two weeks; `spectre doctor` tells you when they stop working.

## Scope

Spectre uses the cookies of an account the user already has. It can do what that account can do and nothing more. Premium features (bookmark folders, similar posts) need a Premium account, and Community Notes rating needs an account enrolled in the programme.

Automated access violates X's Terms of Service. The account, and the consequences, are yours.
