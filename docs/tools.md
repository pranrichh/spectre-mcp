<p align="center">
  <img src="../assets/headers/tools.svg" alt="Tools" />
</p>

111 tools, generated from the live registry.
Every tool returns JSON. Failures look like
`{"error": "...", "kind": "auth|rate_limit|permission|validation|not_found|upstream", "hint": "..."}`.

Read [safety.md](safety.md) before calling anything in **Composing**, **Engagement**,
**Social graph**, **Direct messages** or **Lists** — those change state on X.

## Accounts & sessions

Who is logged in, how healthy the pool is, and what to do when a call is rate limited.

### `get_me()`

Identify the account this server is actually authenticated as.

Call this first in any session. Returns the live handle, id, bio and counts straight from X — not from the local pool — plus whether the stored pool handle has gone stale (accounts get renamed; a stale handle makes every profile lookup on it return "not found").

### `list_accounts()`

List the accounts in the pool with their state (active / locked / error).

Use before heavy work to see how much rate-limit headroom the pool has, and when a call fails with `kind: auth` to spot the dead account.

### `pool_status()`

Account pool health: counts plus per-account state.

Faster to read than list_accounts when all you need is "do I have a working account right now".

### `set_active_account(username)`

Make one account the first choice for every call.

The pool still falls back to the others on a rate limit unless auto-rotation is off. Use when a specific account must own the action (posting as a brand, DMs from a personal handle).

### `set_auto_rotate(enabled)`

Turn automatic account rotation on or off.

On (default): a rate-limited or dead account is benched and the next active account retries the call. Off: the call fails instead, so you always know which account acted.

### `get_rate_limits()`

Per-account rate-limit state: locks, last use, last X rate-limit headers.

Call before a bulk job to decide how many accounts can absorb it, and after a `kind: rate_limit` error to see when the window resets.

### `remove_account(username)`

Remove an account and its cookies from the local pool.

Destructive: the cookies are gone, so re-adding requires fresh browser cookies. Does not touch the X account itself.

---

## Search

Find posts and people. Search is the most expensive read — one request per ~20 results.

### `search(query, limit?, mode?)`

Search X posts with the full operator language.

Supports from:, since:/until:, #tag, filter:media, filter:links, lang:, min_retweets:, min_faves:, -"term", OR, quoted_tweet_id:. Use mode="latest" for recency, "top" for relevance, "media" for visual posts only. Costs one request per ~20 results — the expensive call in bulk workflows.

### `search_users(query, limit?)`

Find accounts by name or keyword.

Cheaper than search() when you only need the handle/id. Follow up with get_user() for the full profile.

---

## Profiles & connections

Everything about an account, its audience, and its posting history.

### `get_user(username)`

Full profile for one handle (without the @).

Returns the numeric id you need for follow/block/DM/like-style tools. Also the right call to check whether an account still exists before acting on it.

### `get_user_by_id(user_id)`

Resolve a numeric user id to a profile.

Use when an id arrives from a DM, list membership or a tweet's author_id and you need the handle. Cheaper and more reliable than guessing a handle.

### `get_users_by_ids(user_ids)`

Resolve many user ids at once (comma-separated).

One call per id internally, so keep it to a handful; missing ids come back in `missing` rather than failing the batch.

### `get_user_tweets(username, limit?)`

A user's own posts, newest first (no replies).

X caps how far back this reaches (~3,200 posts). For older material use search("from:<handle> since:...").

### `get_user_tweets_and_replies(username, limit?)`

A user's posts including their replies.

Use to see who someone talks to and how — good for tone/relationship analysis. Costs more than get_user_tweets because replies dilute the page.

### `get_user_media(username, limit?)`

Photos, videos and GIFs a user posted, with direct media URLs.

Use before download_media() when you need the files, or for visual research.

### `get_followers(username, limit?)`

A user's followers, with a real limit.

`limit` is honoured exactly (the old 100 cap is gone) up to 5000; long walks stop at a time budget and set `truncated: true`. `total_available` is the account's follower count so you can see how far you got.

### `get_following(username, limit?)`

Accounts a user follows, with a real limit (up to 5000).

Same truncation contract as get_followers: `truncated` tells you the walk stopped early, `total_available` is the profile's following count.

### `get_verified_followers(user_id, limit?)`

Blue-verified followers of a user.

A cheap proxy for "who matters in this audience" — useful for prioritising outreach without walking thousands of followers.

### `get_followers_you_know(user_id, limit?)`

Mutual followers between you and another account.

Best first move before cold outreach: the overlap is the warm-intro list.

### `get_user_likes(user_id, limit?)`

Posts a user liked.

Usually empty: X hides likes for most accounts.

### `get_user_highlights(user_id, limit?)`

Posts a user pinned to their profile Highlights section.

Highlights are curated, so this is the closest thing to "what they want to be known for".

---

## Posts

Read individual posts, conversations, and who engaged with them.

### `get_tweet(tweet_id)`

One post with full text, metrics, media URLs and author.

Long-form posts are returned in full (the note_tweet body), not truncated at 280 characters. Use get_tweets() to batch several ids.

### `get_tweets(tweet_ids)`

Fetch several posts by id in one call (comma-separated).

Cheaper than looping get_tweet. Missing ids are reported in `missing` instead of failing the whole batch.

### `get_tweet_replies(tweet_id, limit?)`

Direct replies to a post.

Use get_thread() instead when you need the whole conversation including the parent chain.

### `get_thread(tweet_id, limit?)`

The conversation a post belongs to, oldest first.

Pass any id in the thread. Includes the focal post, its ancestors and the replies X returns for that conversation.

### `get_tweet_quotes(tweet_id, limit?, cursor?)`

Posts that quote a given post.

Quotes are where the commentary lives — more useful than replies for judging reaction. Paginate with next_cursor.

### `get_retweeters(tweet_id, limit?)`

Accounts that retweeted a post.

### `get_favoriters(tweet_id, limit?)`

Accounts that liked a post.

Can be empty on very large accounts: X limits who is listable.

### `get_tweet_edit_history(tweet_id)`

Edit history of a post (ids of every version).

Only populated for posts that were actually edited.

### `get_similar_posts(tweet_id, limit?)`

Posts X considers related to a given post.

Premium-gated upstream: on non-Premium accounts this returns an empty list with a `note`, not an error.

### `get_community_notes(tweet_id)`

Community Notes attached to a post.

### `rate_community_note(note_id, rating)`

Rate a Community Note: helpful, somewhat_helpful, or not_helpful.

Requires an account enrolled in Community Notes.

---

## Composing & media

Anything that publishes or prepares content. Public the moment it runs.

### `post_tweet(text, reply_to?, quote_tweet?, media_ids?)`

Publish a post, reply or quote. Public the moment it runs.

Confirm with the user first. Upload media before posting and pass the ids here (comma-separated). Standard accounts cap at 280 characters, Premium at 25,000; X rejects identical text as a duplicate.

### `delete_tweet(tweet_id)`

Delete one of your posts. Permanent — confirm first.

### `upload_media(file_path)`

Upload an image, GIF or video and get the media id for post_tweet.

Cookie auth, no API keys. Chunked (4 MiB) with processing polling for video, so large files take a while but do not time out. jpg/png/webp/gif/mp4/mov.

### `download_media(source, dest_dir?)`

Download a post's media (or a single media URL) to disk.

Pass a tweet id/URL to get everything attached, or a direct pbs/video URL. Returns the saved paths so you can open or analyse them.

### `schedule_tweet(text, execute_at, reply_to?, media_ids?)`

Schedule a post for a future ISO-8601 time (e.g. 2026-12-01T12:00:00Z).

Posting happens later without you — clear it with the user, and note the time is UTC unless the string carries an offset.

### `get_scheduled_tweets()`

Everything currently queued, with execute_at in ISO-8601 and state.

### `edit_scheduled_tweet(scheduled_id, text, execute_at)`

Change the text or time of a queued post.

### `delete_scheduled_tweet(scheduled_id)`

Cancel a queued post.

### `create_draft(text)`

Save a draft (never publishes by itself).

### `get_drafts()`

Your saved drafts.

### `edit_draft(draft_id, text)`

Rewrite a saved draft.

### `delete_draft(draft_id)`

Delete a saved draft.

---

## Engagement

Likes, reposts, bookmarks and pins. All reversible.

### `like_tweet(tweet_id)`

Like a post. Reversible with unlike_tweet.

### `unlike_tweet(tweet_id)`

Remove your like from a post.

### `retweet(tweet_id)`

Repost someone's post to your followers. Public — confirm first.

### `unretweet(tweet_id)`

Undo your repost.

### `bookmark_tweet(tweet_id)`

Save a post to your bookmarks. Private, reversible.

### `unbookmark_tweet(tweet_id)`

Remove a post from your bookmarks.

### `pin_tweet(tweet_id)`

Pin a post to your profile. Replaces any existing pin without warning.

### `unpin_tweet(tweet_id)`

Unpin the post from your profile.

### `pin_reply(tweet_id, conversation_id?)`

Pin a reply inside its conversation (needs the conversation id).

The conversation id is a tweet's `conversation_id`; get it from get_tweet.

### `unpin_reply(tweet_id, conversation_id?)`

Unpin a reply from its conversation.

---

## Social graph

Follow, mute, block and the lists of who is currently muted or blocked.

### `follow_user(user_id)`

Follow an account. Takes a numeric user id — resolve handles with get_user first.

### `unfollow_user(user_id)`

Unfollow an account.

### `mute_user(user_id)`

Mute an account (you stop seeing them; they are not told).

### `unmute_user(user_id)`

Unmute an account.

### `block_user(user_id)`

Block an account. They lose access to you; this is visible to them.

### `unblock_user(user_id)`

Unblock an account.

### `remove_follower(user_id)`

Remove someone from your followers (soft-block). They can follow again.

### `get_muted_accounts(limit?)`

Accounts you have muted.

### `get_blocked_accounts(limit?)`

Accounts you have blocked.

---

## Direct messages

Read and send DMs. Sending has no recall.

### `send_dm(user_id, text)`

Send a direct message. No recall — confirm the recipient and text first.

The recipient must accept DMs from you (mutual follow, or open message requests). Failures come back as `kind: validation` with X's reason.

### `get_dm_inbox(limit?)`

Recent DM conversations and their latest messages.

Returns both `messages` (flat, newest first) and `conversations` (threads with participants). Use a conversation_id from here with get_dm_conversation.

### `get_dm_conversation(conversation_id, limit?)`

Every message in one DM thread, oldest first.

Includes both directions and the participants' profiles. If a reply the user can see on x.com is missing here, X is not serving it to the cookie session — report that instead of assuming it does not exist.

### `search_dm(query, limit?)`

Search across all DM messages.

### `search_dm_groups(query, limit?)`

Search group DM conversations.

### `search_dm_people(query, limit?)`

Search for people you have DM history with.

### `get_dm_muted(limit?)`

Muted DM conversations.

### `dm_block_user(user_id)`

Block a user from sending you DMs (does not block them globally).

### `dm_unblock_user(user_id)`

Allow a user to DM you again.

---

## Lists

Full CRUD, membership, subscribers and the list timeline.

### `get_list_info(list_id)`

Name, description, member/subscriber counts and owner of a list.

### `create_list(name, description?, private?)`

Create a list. Returns the list_id you need for members and timelines.

### `update_list(list_id, name, description?, private?)`

Rename or re-describe a list.

### `delete_list(list_id)`

Delete a list permanently. Members are not affected.

### `add_list_member(list_id, user_id)`

Add an account to a list.

### `remove_list_member(list_id, user_id)`

Remove an account from a list.

### `get_list_members(list_id, limit?)`

Members of a list.

### `get_list_timeline(list_id, limit?)`

Posts from the members of a list (the main reason to build lists).

### `get_list_subscribers(list_id, limit?)`

Accounts subscribed to a list.

### `get_list_memberships(user_id, limit?)`

Lists a user belongs to — a fast map of someone's information diet.

### `get_list_ownerships(user_id, limit?)`

Lists a user created.

### `subscribe_list(list_id)`

Subscribe to someone else's list so it appears in your timeline.

### `unsubscribe_list(list_id)`

Unsubscribe from a list.

---

## Communities, topics & trends

Community posts, topic follows, and what is trending where.

### `get_community_info(community_id)`

Community name, description, member count and join policy.

### `get_community_tweets(community_id, limit?)`

Posts inside a community.

### `join_community(community_id)`

Join a community. Visible to its members.

### `leave_community(community_id)`

Leave a community.

### `get_topic_info(topic_id)`

Details and follow state of a topic.

### `follow_topic(topic_id)`

Follow a topic (X's curated interest feeds).

### `unfollow_topic(topic_id)`

Unfollow a topic.

### `get_trends(woeid?, limit?)`

Trending topics for a place (woeid 1 = worldwide).

Find a woeid with get_trend_locations. Tweet volumes are present only for trends X decides to publish them for.

### `get_trend_locations()`

Places you can request trends for, with their woeids.

---

## Bookmarks

Saved posts, search inside them, and folder management (folders are Premium-gated by X).

### `get_bookmarks(limit?, cursor?)`

Your bookmarked posts, newest first. Paginate with next_cursor.

### `search_bookmarks(query, limit?, cursor?)`

Full-text search inside your bookmarks.

### `clear_all_bookmarks()`

Delete every bookmark. Irreversible — confirm first.

### `get_bookmark_folders()`

List your bookmark folders.

X gates bookmark folders behind Premium.

### `create_bookmark_folder(name)`

Create a bookmark folder (Premium-gated by X).

### `edit_bookmark_folder(folder_id, name)`

Rename a bookmark folder (Premium-gated by X).

### `delete_bookmark_folder(folder_id)`

Delete a bookmark folder. The bookmarks inside are not deleted.

### `add_tweet_to_folder(folder_id, tweet_id)`

Put a bookmarked post into a folder.

### `remove_tweet_from_folder(folder_id, tweet_id)`

Remove a post from a folder (keeps the bookmark itself).

### `get_bookmark_folder_timeline(folder_id, limit?)`

Posts inside one bookmark folder.

---

## Timelines

Ambient feeds for the authenticated account.

### `get_home_timeline(limit?)`

The authenticated account's "For You" feed, with authors resolved.

Use for ambient awareness rather than targeted research. For the reverse chronological feed use search("filter:follows").

### `get_notifications(limit?, cursor?)`

Notifications timeline: likes, follows, replies, mentions, reposts.

Use it to find what needs a response; each item carries the type plus the user/tweet involved. Paginate with next_cursor.

---

## Profile

Read and edit the authenticated account's own profile.

### `get_account_settings()`

The authenticated account as X sees it, plus a stale-handle warning.

X removed the REST settings endpoint, so language/timezone are no longer exposed; everything here comes from GraphQL Viewer.

### `update_profile(name?, bio?, location?, website?)`

Change your public display name, bio, location or website.

Only the fields you pass are touched (empty means "leave it"). Bio cannot contain < > or & — X rejects them with code 120.

### `update_profile_image(file_path)`

Replace the avatar. Takes a local jpg/png/gif path.

### `update_profile_banner(file_path)`

Replace the banner/header image (recommended 1500x500).

### `delete_profile_banner()`

Remove the banner image.

---
