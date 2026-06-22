---
name: spectre
description: "X/Twitter automation MCP server — 104 tools for search, posting, media upload, DMs, scheduled tweets, drafts, bookmark folders, lists, communities, topics, community notes, account settings, profile management, highlights, notifications."
tags: [twitter, x, mcp, scraper, social-media, search, automation]
triggers:
  - "search twitter"
  - "search x"
  - "tweet"
  - "twitter profile"
  - "x post"
  - "trending"
  - "find tweets"
  - "post a tweet"
  - "like a tweet"
  - "retweet"
  - "send dm twitter"
  - "upload image to twitter"
  - "schedule tweet"
  - "x automation"
  - "update twitter profile"
  - "change twitter bio"
  - "twitter account settings"
  - "pin tweet"
  - "twitter highlights"
  - "muted accounts"
  - "blocked accounts"
  - "search dms"
  - "twitter notifications"
  - "bookmark folders"
  - "community notes"
  - "draft tweet"
  - "twitter lists"
---

# Spectre MCP — Agent Reference

104 tools for X/Twitter automation via direct GraphQL/REST API. Cookie-based auth, no browser needed.

GitHub: https://github.com/pranrichh/spectre-mcp

## Setup

```bash
uvx spectre-mcp
```

User adds account via CLI (not the agent):
```bash
spectre add myaccount "auth_token=xxx; ct0=yyy"
```

Cookies from: Browser DevTools → Application → Cookies → x.com (need both `auth_token` and `ct0`).

## How To Use Each Category

### Searching X

```
search("AI startups", limit=20, mode="latest")           # Recent tweets
search("from:elonmusk", limit=10)                         # User's tweets
search("AI since:2026-06-01 filter:media", limit=50)      # Media tweets since date
search_users("openai", limit=10)                          # Find users
```

Supports all X operators: `from:`, `since:`, `until:`, `#hashtag`, `filter:media`, `filter:links`, `lang:en`, `min_retweets:N`, `min_faves:N`, `-"term"`, `OR`

### Getting User Info

```
get_user("elonmusk")                    # Profile (returns user_id — save this!)
get_user_tweets("elonmusk", limit=50)   # Recent tweets
get_user_tweets_and_replies("elonmusk") # Tweets + replies
get_user_media("elonmusk", limit=20)    # Photos/videos only
get_followers("elonmusk", limit=100)    # Follower list
get_following("elonmusk", limit=100)    # Following list
get_user_likes(user_id=44196397)        # Their liked tweets
get_user_highlights(user_id=44196397)   # Their highlights
get_verified_followers(user_id=44196397) # Blue-verified followers
get_followers_you_know(user_id=44196397) # Mutual followers
```

**TIP:** Many write operations need `user_id` (numeric), not username. Always call `get_user()` first to get the ID.

### Posting & Media Upload

```
# Simple tweet
post_tweet(text="Hello world!")

# Tweet with image (upload first, then post)
upload_media(file_path="/path/to/image.jpg")  # Returns media_id
post_tweet(text="Check this out!", media_ids="1234567890")

# Reply
post_tweet(text="Great point!", reply_to=1234567890)

# Quote tweet
post_tweet(text="My take on this:", quote_tweet=1234567890)
```

Media upload works with just cookies — no API keys needed. Supports: jpg, png, gif, mp4, mov.

**TIP:** Upload media first, get media_id, then post. Multiple media: comma-separated IDs.

### Engagement

```
like_tweet(1234567890)         # Like
unlike_tweet(1234567890)       # Unlike
retweet(1234567890)            # Retweet
unretweet(1234567890)          # Undo retweet
bookmark_tweet(1234567890)     # Bookmark
unbookmark_tweet(1234567890)   # Remove bookmark
```

All engagement tools take tweet_id (numeric). Get it from search results or user timelines.

### Tweet Info

```
get_tweet(1234567890)                # Full tweet data
get_tweet_replies(1234567890)        # Replies
get_thread(1234567890)               # Full thread
get_retweeters(1234567890)           # Who retweeted
get_favoriters(1234567890)           # Who liked
get_tweet_edit_history(1234567890)   # Edit history
get_similar_posts(1234567890)        # Related posts
get_community_notes(1234567890)      # Community notes
```

### Social Actions (⚠️ Destructive)

```
follow_user(1234567890)        # Needs user_id, not username
unfollow_user(1234567890)
mute_user(1234567890)
unmute_user(1234567890)
block_user(1234567890)
unblock_user(1234567890)
remove_follower(1234567890)    # ⚠️ Remove someone from your followers
pin_reply(1234567890)          # Pin a reply to a thread
unpin_reply(1234567890)        # Unpin a reply
```

**Always confirm with user before follow/unfollow/block.**

### DMs

```
send_dm(user_id=1234567890, text="Hey!")           # Send DM (needs user_id)
get_dm_inbox(limit=20)                              # Recent conversations
get_dm_conversation(conversation_id="123-456")      # Messages in a conversation
search_dm(query="meeting")                         # Search all DMs
search_dm_groups(query="project")                  # Search group DMs
search_dm_people(query="john")                     # Search DM contacts
get_dm_muted(limit=20)                             # Muted DM conversations
dm_block_user(1234567890)                          # Block in DMs
dm_unblock_user(1234567890)                        # Unblock in DMs
```

### Scheduled Tweets & Drafts

```
schedule_tweet(text="Hello future!", execute_at="2026-06-25T14:00:00Z")
get_scheduled_tweets()
edit_scheduled_tweet(id="12345", text="Updated", execute_at="2026-06-26T10:00:00Z")
delete_scheduled_tweet("12345")

create_draft(text="Working on this idea...")
get_drafts()
edit_draft(draft_id="67890", text="Updated draft")
delete_draft("67890")
```

### Bookmark Folders

```
get_bookmark_folders()                          # List folders
create_bookmark_folder("AI Research")           # Create
edit_bookmark_folder("folder_id", "New Name")   # Rename
delete_bookmark_folder("folder_id")             # ⚠️ Delete
add_tweet_to_folder("folder_id", 1234567890)    # Add tweet
remove_tweet_from_folder("folder_id", 1234567890) # Remove tweet
get_bookmark_folder_timeline("folder_id")       # View contents
search_bookmarks("keyword")                     # Search bookmarks
clear_all_bookmarks()                           # ⚠️ Delete ALL bookmarks
```

### Lists

```
create_list("AI Researchers", description="Top AI accounts")
update_list(list_id=123, name="New Name", description="Updated")
delete_list(list_id=123)            # ⚠️ Destructive
add_list_member(list_id=123, user_id=456)
remove_list_member(list_id=123, user_id=456)
get_list_timeline(list_id=123)
get_list_members(list_id=123)
get_list_subscribers(list_id=123)
subscribe_list(list_id=123)
unsubscribe_list(list_id=123)
```

### Communities

```
get_community_info(community_id=123)
get_community_tweets(community_id=123)
join_community(community_id=123)
leave_community(community_id=123)   # ⚠️ Destructive
```

### Account Settings (⚠️ All Destructive)

```
get_account_settings()                          # Read settings
update_profile(bio="Building in public")        # Update bio
update_profile(name="New Name")                 # Change display name
update_profile_image(file_path="/path/avatar.jpg")
update_profile_banner(file_path="/path/banner.jpg")
delete_profile_banner()
```

### Profile & Highlights (⚠️ Destructive)

```
pin_tweet(1234567890)                  # Replaces existing pin
unpin_tweet(1234567890)               # Unpin
create_highlight("123,456,789")        # Add tweets to highlights
delete_highlight("highlight_id")       # Remove highlight
get_user_highlights(user_id=123)       # View highlights
```

### Notifications & Topics

```
get_notifications(limit=20)            # Notifications timeline

get_topic_info(topic_id="123")
follow_topic(topic_id="123")
unfollow_topic(topic_id="123")
```

### Community Notes

```
get_community_notes(tweet_id=123)
rate_community_note(note_id="abc", rating="helpful")
```

> Community Notes creation requires an eligible account (6+ months, verified phone). Not included in current release.

### Safety & Privacy

```
get_muted_accounts(limit=50)
get_blocked_accounts(limit=50)
get_verified_followers(user_id=123)
get_user_likes(user_id=123)
get_followers_you_know(user_id=123)
```

## Account Pool Management

```
list_accounts()                    # See all accounts
set_active_account("username")     # Pick which to use first
set_auto_rotate(false)             # Lock to single account
pool_status()                      # Health check
```

When auto-rotate is on (default): if account A hits a rate limit, Spectre silently switches to account B.

## ⚠️ Destructive Tools — Full List

These tools make **immediate, irreversible changes**. ALWAYS confirm with the user first:

- `post_tweet` — public tweet, live immediately
- `delete_tweet` — permanent
- `pin_tweet` — replaces existing pin silently
- `update_profile` / `update_profile_image` / `update_profile_banner` / `delete_profile_banner`
- `create_highlight` / `delete_highlight`
- `follow_user` / `unfollow_user` / `block_user`
- `mute_user` / `unmute_user` / `unblock_user`
- `remove_follower` — removes someone from your followers
- `send_dm` — sent immediately, no recall
- `dm_block_user` / `dm_unblock_user`
- `schedule_tweet` / `delete_scheduled_tweet` / `delete_draft`
- `delete_list` / `leave_community`
- `clear_all_bookmarks`
- `subscribe_list` / `unsubscribe_list`

## Pitfalls

1. **Cookies expire ~2 weeks.** Re-add when searches return empty results.
2. **ct0 is 160 hex chars**, not 40. Double-check the user copied the full value.
3. **GraphQL operation IDs rotate every few months.** Override via `SPECTRE_OP_*` env vars.
4. **pin_tweet replaces silently.** Only one pin allowed — old pin is unpinned without warning.
5. **Profile images process asynchronously.** May take a few seconds to appear after upload.
6. **update_profile with empty string clears that field.** `update_profile(bio="")` clears the bio.
7. **Rate limits are per-account.** 2-3 accounts recommended for heavy usage.
8. **Default DB:** `~/.spectre/accounts.db`. Override with `SPECTRE_DB`.
9. **Media upload returns HTTP 202** on INIT — this is normal, not an error.
10. **User IDs are numeric**, not handles. Always use `get_user()` to resolve handles to IDs.
11. **Image uploads** — avatar must be valid image (jpg/png), banner must be 200x100 to 8192x8192.
12. **get_list_memberships/get_list_ownerships** — known X API server-side issue, may return empty.
