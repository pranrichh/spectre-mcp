"""Spectre — MCP server: the tools an agent actually calls.

Design rules for this layer:

* A tool returns JSON, always. Failures come back as `{"error", "kind", "hint"}`
  so the caller can branch on `kind` instead of parsing prose.
* X ids are accepted as strings (or full x.com URLs); that is the schema.
* Docstrings describe *when* to call a tool and what it costs, not its argument
  list — the schema already does arguments.
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Optional

from fastmcp import FastMCP
from pydantic import BeforeValidator, WithJsonSchema
from twscrape.accounts_pool import AccountsPool

from spectre.errors import XError
from spectre.scraper import Scraper
from spectre.writer import Writer
from spectre.xclient import XClient

INSTRUCTIONS = """Spectre gives you X/Twitter: search, timelines, profiles, posting,
media, DMs, lists, bookmarks, notifications, scheduled posts and account management.

Start with get_me() to confirm which account is live, then search()/get_user().
Ids are strings or x.com URLs. Read tools are cheap;
write tools are public and permanent, so confirm intent with the user first.
Errors carry `kind`: rate_limit (wait or switch account), auth (re-add cookies),
permission (X Premium / privacy), validation (fix the input), not_found."""

mcp = FastMCP("spectre", instructions=INSTRUCTIONS)

DB_PATH = os.environ.get("SPECTRE_DB", os.path.join(os.path.expanduser("~"), ".spectre", "accounts.db"))

_pool: Optional[AccountsPool] = None
_client: Optional[XClient] = None
_writer: Optional[Writer] = None
_scraper: Optional[Scraper] = None


def _get_pool() -> AccountsPool:
    """One pool for reads, writes and account management (shared SQLite state)."""
    global _pool
    if _pool is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        _pool = AccountsPool(DB_PATH)
    return _pool


def _get_client() -> XClient:
    global _client
    if _client is None:
        _client = XClient(_get_pool(), proxy=os.environ.get("SPECTRE_PROXY"))
    return _client


def _get_writer() -> Writer:
    global _writer
    if _writer is None:
        _writer = Writer(_get_client(), db_path=DB_PATH)
    return _writer


def _get_scraper() -> Scraper:
    global _scraper
    if _scraper is None:
        _scraper = Scraper(_get_pool(), proxy=os.environ.get("SPECTRE_PROXY"))
    return _scraper


async def _out(result) -> str:
    """Await a result and render it as tool JSON, converting failures cleanly."""
    try:
        value = await result
    except XError as exc:
        value = exc.to_dict()
    except Exception as exc:  # noqa: BLE001 - a tool must never crash the server
        value = {"error": f"{type(exc).__name__}: {exc}", "kind": "internal"}
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


def _id(value):
    """Coerce an X id to an int, accepting a string or a full x.com URL."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Invalid X id: {value!r}")
    if isinstance(value, int):
        return value
    text = str(value).strip().rstrip("/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    text = text.split("?")[0].split("#")[0]
    if not text.isdigit():
        raise ValueError(
            f"Invalid X id: {value!r} - pass the numeric id as a string "
            '(e.g. "2111332908657148356") or an x.com URL.'
        )
    return int(text)


XId = Annotated[int, BeforeValidator(_id), WithJsonSchema({"type": "string"})]
OptXId = Optional[XId]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


# ══════════════════════════════════════════════════════════════
#  Sessions & accounts
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_me() -> str:
    """Identify the account this server is actually authenticated as.

    Call this first in any session. Returns the live handle, id, bio and counts
    straight from X — not from the local pool — plus whether the stored pool
    handle has gone stale (accounts get renamed; a stale handle makes every
    profile lookup on it return "not found").
    """
    return await _out(_get_writer().me())


@mcp.tool()
async def list_accounts() -> str:
    """List the accounts in the pool with their state (active / locked / error).

    Use before heavy work to see how much rate-limit headroom the pool has, and
    when a call fails with `kind: auth` to spot the dead account.
    """
    accounts = await _get_pool().get_all()
    rows = [
        {
            "username": a.username,
            "state": "active" if (a.active and not a.error_msg) else ("error" if a.error_msg else "locked"),
            "error": a.error_msg,
            "proxy": getattr(a, "proxy", None),
            "last_used": str(a.last_used) if a.last_used else None,
        }
        for a in accounts
    ]
    if not rows:
        return json.dumps({"message": 'No accounts. Add one: spectre add <name> "auth_token=...; ct0=..."'})
    return json.dumps(rows, indent=2)


@mcp.tool()
async def pool_status() -> str:
    """Account pool health: counts plus per-account state.

    Faster to read than list_accounts when all you need is "do I have a working
    account right now".
    """
    accounts = await _get_pool().get_all()
    active = [a for a in accounts if a.active and not a.error_msg]
    errored = [a for a in accounts if a.error_msg]
    return json.dumps(
        {
            "total": len(accounts),
            "active": len(active),
            "locked": len(accounts) - len(active) - len(errored),
            "error": len(errored),
            "accounts": [{"username": a.username, "state": "active" if a in active else ("error" if a.error_msg else "locked"), "error": a.error_msg} for a in accounts],
        },
        indent=2,
    )


@mcp.tool()
async def set_active_account(username: str) -> str:
    """Make one account the first choice for every call.

    The pool still falls back to the others on a rate limit unless auto-rotation
    is off. Use when a specific account must own the action (posting as a brand,
    DMs from a personal handle).
    """
    accounts = await _get_pool().get_all()
    target = next((a for a in accounts if a.username.lower() == username.lstrip("@").lower()), None)
    if not target:
        return json.dumps({"error": f"@{username} is not in the pool.", "kind": "validation", "accounts": [a.username for a in accounts]}, indent=2)
    _get_client().set_preferred_account(target.username)
    return json.dumps({"status": "primary", "username": target.username}, indent=2)


@mcp.tool()
async def set_auto_rotate(enabled: bool) -> str:
    """Turn automatic account rotation on or off.

    On (default): a rate-limited or dead account is benched and the next active
    account retries the call. Off: the call fails instead, so you always know
    which account acted.
    """
    _get_client().set_auto_rotate(enabled)
    return json.dumps(
        {
            "auto_rotate": enabled,
            "behaviour": "rotate to another account on rate limit / auth failure" if enabled else "fail instead of rotating",
        },
        indent=2,
    )


@mcp.tool()
async def remove_account(username: str) -> str:
    """Remove an account and its cookies from the local pool.

    Destructive: the cookies are gone, so re-adding requires fresh browser
    cookies. Does not touch the X account itself.
    """
    target = username.lstrip("@").lower()
    accounts = await _get_pool().get_all()
    match = next((a for a in accounts if a.username.lower() == target), None)
    if not match:
        return json.dumps(
            {"error": f"@{target} is not in the pool.", "kind": "validation", "accounts": [a.username for a in accounts]},
            indent=2,
        )
    await _get_pool().delete_accounts([match.username])
    return json.dumps({"status": "removed", "username": match.username}, indent=2)


@mcp.tool()
async def get_rate_limits() -> str:
    """Per-account rate-limit state: locks, last use, last X rate-limit headers.

    Call before a bulk job to decide how many accounts can absorb it, and after a
    `kind: rate_limit` error to see when the window resets.
    """
    return await _out(_get_writer().rate_limits())


# ══════════════════════════════════════════════════════════════
#  Search
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def search(query: str, limit: int = 20, mode: str = "latest") -> str:
    """Search X posts with the full operator language.

    Supports from:, since:/until:, #tag, filter:media, filter:links, lang:,
    min_retweets:, min_faves:, -"term", OR, quoted_tweet_id:. Use mode="latest"
    for recency, "top" for relevance, "media" for visual posts only.
    Costs one request per ~20 results — the expensive call in bulk workflows.
    """
    limit = _clamp(limit, 1, 100)
    return await _out(_get_scraper().search(query, limit=limit, mode=mode))


@mcp.tool()
async def search_users(query: str, limit: int = 10) -> str:
    """Find accounts by name or keyword.

    Cheaper than search() when you only need the handle/id. Follow up with
    get_user() for the full profile.
    """
    limit = _clamp(limit, 1, 50)
    return await _out(_get_scraper().search_users(query, limit=limit))


# ══════════════════════════════════════════════════════════════
#  Users
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_user(username: str) -> str:
    """Full profile for one handle (without the @).

    Returns the numeric id you need for follow/block/DM/like-style tools. Also
    the right call to check whether an account still exists before acting on it.
    """
    return await _out(_get_writer().user(username))


@mcp.tool()
async def get_user_by_id(user_id: XId) -> str:
    """Resolve a numeric user id to a profile.

    Use when an id arrives from a DM, list membership or a tweet's author_id and
    you need the handle. Cheaper and more reliable than guessing a handle.
    """
    return await _out(_get_writer().user_by_id(str(user_id)))


@mcp.tool()
async def get_users_by_ids(user_ids: str) -> str:
    """Resolve many user ids at once (comma-separated).

    One call per id internally, so keep it to a handful; missing ids come back in
    `missing` rather than failing the batch.
    """
    ids = [x.strip() for x in str(user_ids).split(",") if x.strip()]
    if not ids:
        return json.dumps({"error": "Pass at least one id", "kind": "validation"})
    return await _out(_get_writer().users_by_ids(ids[:50]))


@mcp.tool()
async def get_user_tweets(username: str, limit: int = 20) -> str:
    """A user's own posts, newest first (no replies).

    X caps how far back this reaches (~3,200 posts). For older material use
    search("from:<handle> since:...").
    """
    limit = _clamp(limit, 1, 500)
    return await _out(_get_scraper().user_tweets(username, limit=limit))


@mcp.tool()
async def get_user_tweets_and_replies(username: str, limit: int = 20) -> str:
    """A user's posts including their replies.

    Use to see who someone talks to and how — good for tone/relationship
    analysis. Costs more than get_user_tweets because replies dilute the page.
    """
    limit = _clamp(limit, 1, 500)
    return await _out(_get_scraper().user_tweets(username, limit=limit, replies=True))


@mcp.tool()
async def get_user_media(username: str, limit: int = 20) -> str:
    """Photos, videos and GIFs a user posted, with direct media URLs.

    Use before download_media() when you need the files, or for visual research.
    """
    limit = _clamp(limit, 1, 200)
    return await _out(_get_scraper().user_tweets(username, limit=limit, media_only=True))


@mcp.tool()
async def get_followers(username: str, limit: int = 20) -> str:
    """A user's followers, with a real limit.

    `limit` is honoured exactly (the old 100 cap is gone) up to 5000; long walks
    stop at a time budget and set `truncated: true`. `total_available` is the
    account's follower count so you can see how far you got.
    """
    limit = _clamp(limit, 1, 5000)
    return await _out(_get_scraper().followers(username, limit=limit))


@mcp.tool()
async def get_following(username: str, limit: int = 20) -> str:
    """Accounts a user follows, with a real limit (up to 5000).

    Same truncation contract as get_followers: `truncated` tells you the walk
    stopped early, `total_available` is the profile's following count.
    """
    limit = _clamp(limit, 1, 5000)
    return await _out(_get_scraper().following(username, limit=limit))


@mcp.tool()
async def get_verified_followers(user_id: XId, limit: int = 20) -> str:
    """Blue-verified followers of a user.

    A cheap proxy for "who matters in this audience" — useful for prioritising
    outreach without walking thousands of followers.
    """
    limit = _clamp(limit, 1, 200)
    return await _out(_get_scraper().verified_followers(str(user_id), limit=limit))


@mcp.tool()
async def get_followers_you_know(user_id: XId, limit: int = 20) -> str:
    """Mutual followers between you and another account.

    Best first move before cold outreach: the overlap is the warm-intro list.
    """
    limit = _clamp(limit, 1, 100)
    return await _out(_followers_you_know(str(user_id), limit))


async def _followers_you_know(user_id: str, limit: int) -> dict:
    data = await _get_client().graphql("FollowersYouKnow", {"userId": user_id, "count": limit, "includePromotedContent": False})
    from spectre.parse import timeline

    _, users, cursor = timeline(data)
    return {"users": users, "count": len(users), "next_cursor": cursor}


@mcp.tool()
async def get_user_likes(user_id: XId, limit: int = 20) -> str:
    """Posts a user liked.

    Usually empty: X hides likes for most accounts.
    """
    limit = _clamp(limit, 1, 100)
    data = await _get_client().graphql("Likes", {"userId": str(user_id), "count": limit, "includePromotedContent": False})
    from spectre.parse import timeline

    tweets, _, cursor = timeline(data)
    return json.dumps({"tweets": tweets, "count": len(tweets), "next_cursor": cursor, "note": "Empty usually means the user hides their likes."}, indent=2, default=str, ensure_ascii=False)


@mcp.tool()
async def get_user_highlights(user_id: XId, limit: int = 20) -> str:
    """Posts a user pinned to their profile Highlights section.

    Highlights are curated, so this is the closest thing to "what they want to be
    known for".
    """
    limit = _clamp(limit, 1, 100)
    data = await _get_client().graphql("UserHighlightsTweets", {"userId": str(user_id), "count": limit, "includePromotedContent": False, "withVoice": False})
    from spectre.parse import timeline

    tweets, _, cursor = timeline(data)
    return json.dumps({"tweets": tweets, "count": len(tweets), "next_cursor": cursor}, indent=2, default=str, ensure_ascii=False)


@mcp.tool()
async def create_highlight(tweet_ids: str) -> str:
    """Add posts to your profile's Highlights section (comma-separated ids).

    Highlights are public. X limits the feature to eligible accounts and answers
    `kind: permission` for the rest.
    """
    ids = [x.strip() for x in str(tweet_ids).split(",") if x.strip()]
    if not ids:
        return json.dumps({"error": "Pass at least one tweet id", "kind": "validation"})
    return await _out(_get_writer().create_highlight(ids[:20]))


@mcp.tool()
async def delete_highlight(tweet_id: XId) -> str:
    """Remove a post from your profile's Highlights section."""
    return await _out(_get_writer().delete_highlight(str(tweet_id)))


# ══════════════════════════════════════════════════════════════
#  Posts
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_tweet(tweet_id: XId) -> str:
    """One post with full text, metrics, media URLs and author.

    Long-form posts are returned in full (the note_tweet body), not truncated at
    280 characters. Use get_tweets() to batch several ids.
    """
    return await _out(_get_writer().tweet(str(tweet_id)))


@mcp.tool()
async def get_tweets(tweet_ids: str) -> str:
    """Fetch several posts by id in one call (comma-separated).

    Cheaper than looping get_tweet. Missing ids are reported in `missing` instead
    of failing the whole batch.
    """
    ids = [x.strip() for x in str(tweet_ids).split(",") if x.strip()]
    if not ids:
        return json.dumps({"error": "Pass at least one id", "kind": "validation"})
    return await _out(_get_writer().tweets(ids[:100]))


@mcp.tool()
async def get_tweet_replies(tweet_id: XId, limit: int = 20) -> str:
    """Direct replies to a post.

    Use get_thread() instead when you need the whole conversation including the
    parent chain.
    """
    limit = _clamp(limit, 1, 200)
    return await _out(_get_scraper().replies(str(tweet_id), limit=limit))


@mcp.tool()
async def get_thread(tweet_id: XId, limit: int = 50) -> str:
    """The conversation a post belongs to, oldest first.

    Pass any id in the thread. Includes the focal post, its ancestors and the
    replies X returns for that conversation.
    """
    limit = _clamp(limit, 1, 200)
    return await _out(_get_writer().thread(str(tweet_id), limit=limit))


@mcp.tool()
async def get_tweet_quotes(tweet_id: XId, limit: int = 20, cursor: str = "") -> str:
    """Posts that quote a given post.

    Quotes are where the commentary lives — more useful than replies for judging
    reaction. Paginate with next_cursor.
    """
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().quotes(str(tweet_id), limit=limit, cursor=cursor or None))


@mcp.tool()
async def get_retweeters(tweet_id: XId, limit: int = 20) -> str:
    """Accounts that retweeted a post."""
    limit = _clamp(limit, 1, 100)
    return await _out(_get_scraper().retweeters(str(tweet_id), limit=limit))


@mcp.tool()
async def get_favoriters(tweet_id: XId, limit: int = 20) -> str:
    """Accounts that liked a post.

    Can be empty on very large accounts: X limits who is listable.
    """
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().favoriters(str(tweet_id), limit=limit))


@mcp.tool()
async def get_tweet_edit_history(tweet_id: XId) -> str:
    """Edit history of a post (ids of every version).

    Only populated for posts that were actually edited.
    """
    return await _out(_get_writer().edit_history(str(tweet_id)))


@mcp.tool()
async def get_similar_posts(tweet_id: XId, limit: int = 20) -> str:
    """Posts X considers related to a given post.

    Premium-gated upstream: on non-Premium accounts this returns an empty list
    with a `note`, not an error.
    """
    limit = _clamp(limit, 1, 50)
    return await _out(_get_writer().similar_posts(str(tweet_id), limit=limit))


@mcp.tool()
async def get_community_notes(tweet_id: XId) -> str:
    """Community Notes attached to a post."""
    return await _out(_get_writer().community_notes(str(tweet_id)))


@mcp.tool()
async def rate_community_note(note_id: str, rating: str) -> str:
    """Rate a Community Note: helpful, somewhat_helpful, or not_helpful.

    Requires an account enrolled in Community Notes.
    """
    return await _out(_get_writer().rate_community_note(note_id, rating))


@mcp.tool()
async def get_home_timeline(limit: int = 20) -> str:
    """The authenticated account's "For You" feed, with authors resolved.

    Use for ambient awareness rather than targeted research. For the reverse
    chronological feed use search("filter:follows").
    """
    limit = _clamp(limit, 1, 100)
    data = await _get_client().graphql(
        "HomeTimeline",
        {"count": limit, "includePromotedContent": True, "latestControlAvailable": True, "requestContext": "launch"},
    )
    from spectre.parse import timeline

    tweets, _, cursor = timeline(data)
    return json.dumps({"tweets": tweets[:limit], "count": min(len(tweets), limit), "next_cursor": cursor}, indent=2, default=str, ensure_ascii=False)


@mcp.tool()
async def get_notifications(limit: int = 20, cursor: str = "") -> str:
    """Notifications timeline: likes, follows, replies, mentions, reposts.

    Use it to find what needs a response; each item carries the type plus the
    user/tweet involved. Paginate with next_cursor.
    """
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().notifications(limit=limit, cursor=cursor or None))


# ══════════════════════════════════════════════════════════════
#  Composing
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def post_tweet(text: str, reply_to: OptXId = None, quote_tweet: OptXId = None, media_ids: str = "") -> str:
    """Publish a post, reply or quote. Public the moment it runs.

    Confirm with the user first. Upload media before posting and pass the ids
    here (comma-separated). Standard accounts cap at 280 characters, Premium at
    25,000; X rejects identical text as a duplicate.
    """
    ids = [x.strip() for x in str(media_ids).split(",") if x.strip()] if media_ids else None
    return await _out(
        _get_writer().post(text, reply_to=str(reply_to) if reply_to else None, quote_tweet=str(quote_tweet) if quote_tweet else None, media_ids=ids)
    )


@mcp.tool()
async def delete_tweet(tweet_id: XId) -> str:
    """Delete one of your posts. Permanent — confirm first."""
    return await _out(_get_writer().delete_tweet(str(tweet_id)))


@mcp.tool()
async def upload_media(file_path: str) -> str:
    """Upload an image, GIF or video and get the media id for post_tweet.

    Cookie auth, no API keys. Chunked (4 MiB) with processing polling for video,
    so large files take a while but do not time out. jpg/png/webp/gif/mp4/mov.
    """
    return await _out(_get_writer().upload_media(file_path))


@mcp.tool()
async def download_media(source: str, dest_dir: str = "") -> str:
    """Download a post's media (or a single media URL) to disk.

    Pass a tweet id/URL to get everything attached, or a direct pbs/video URL.
    Returns the saved paths so you can open or analyse them.
    """
    return await _out(_get_writer().download_media(source, dest_dir or os.path.join(os.path.expanduser("~"), ".spectre", "media")))


# ══════════════════════════════════════════════════════════════
#  Engagement
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def like_tweet(tweet_id: XId) -> str:
    """Like a post. Reversible with unlike_tweet."""
    return await _out(_get_writer().like(str(tweet_id)))


@mcp.tool()
async def unlike_tweet(tweet_id: XId) -> str:
    """Remove your like from a post."""
    return await _out(_get_writer().unlike(str(tweet_id)))


@mcp.tool()
async def retweet(tweet_id: XId) -> str:
    """Repost someone's post to your followers. Public — confirm first."""
    return await _out(_get_writer().retweet(str(tweet_id)))


@mcp.tool()
async def unretweet(tweet_id: XId) -> str:
    """Undo your repost."""
    return await _out(_get_writer().unretweet(str(tweet_id)))


@mcp.tool()
async def bookmark_tweet(tweet_id: XId) -> str:
    """Save a post to your bookmarks. Private, reversible."""
    return await _out(_get_writer().bookmark(str(tweet_id)))


@mcp.tool()
async def unbookmark_tweet(tweet_id: XId) -> str:
    """Remove a post from your bookmarks."""
    return await _out(_get_writer().unbookmark(str(tweet_id)))


@mcp.tool()
async def pin_tweet(tweet_id: XId) -> str:
    """Pin a post to your profile. Replaces any existing pin without warning."""
    return await _out(_get_writer().pin(str(tweet_id)))


@mcp.tool()
async def unpin_tweet(tweet_id: XId) -> str:
    """Unpin the post from your profile."""
    return await _out(_get_writer().unpin(str(tweet_id)))


@mcp.tool()
async def pin_reply(tweet_id: XId, conversation_id: str = "") -> str:
    """Pin a reply inside its conversation (needs the conversation id).

    The conversation id is a tweet's `conversation_id`; get it from get_tweet.
    """
    if not conversation_id:
        tweet = await _get_writer().tweet(str(tweet_id))
        if isinstance(tweet, dict) and tweet.get("conversation_id"):
            conversation_id = tweet["conversation_id"]
        else:
            return json.dumps({"error": "conversation_id required (could not derive it)", "kind": "validation"}, indent=2)
    return await _out(_get_writer().pin_reply(str(tweet_id), conversation_id))


@mcp.tool()
async def unpin_reply(tweet_id: XId, conversation_id: str = "") -> str:
    """Unpin a reply from its conversation."""
    if not conversation_id:
        tweet = await _get_writer().tweet(str(tweet_id))
        if isinstance(tweet, dict) and tweet.get("conversation_id"):
            conversation_id = tweet["conversation_id"]
        else:
            return json.dumps({"error": "conversation_id required (could not derive it)", "kind": "validation"}, indent=2)
    return await _out(_get_writer().unpin_reply(str(tweet_id), conversation_id))


# ══════════════════════════════════════════════════════════════
#  Social graph
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def follow_user(user_id: XId) -> str:
    """Follow an account. Takes a numeric user id — resolve handles with get_user first."""
    return await _out(_get_writer().follow(str(user_id)))


@mcp.tool()
async def unfollow_user(user_id: XId) -> str:
    """Unfollow an account."""
    return await _out(_get_writer().unfollow(str(user_id)))


@mcp.tool()
async def mute_user(user_id: XId) -> str:
    """Mute an account (you stop seeing them; they are not told)."""
    return await _out(_get_writer().mute(str(user_id)))


@mcp.tool()
async def unmute_user(user_id: XId) -> str:
    """Unmute an account."""
    return await _out(_get_writer().unmute(str(user_id)))


@mcp.tool()
async def block_user(user_id: XId) -> str:
    """Block an account. They lose access to you; this is visible to them."""
    return await _out(_get_writer().block(str(user_id)))


@mcp.tool()
async def unblock_user(user_id: XId) -> str:
    """Unblock an account."""
    return await _out(_get_writer().unblock(str(user_id)))


@mcp.tool()
async def remove_follower(user_id: XId) -> str:
    """Remove someone from your followers (soft-block). They can follow again."""
    return await _out(_get_writer().remove_follower(str(user_id)))


@mcp.tool()
async def get_muted_accounts(limit: int = 50) -> str:
    """Accounts you have muted."""
    limit = _clamp(limit, 1, 200)
    data = await _get_client().graphql("MutedAccounts", {"count": limit, "includePromotedContent": False})
    from spectre.parse import timeline

    _, users, cursor = timeline(data)
    return json.dumps({"users": users, "count": len(users), "next_cursor": cursor}, indent=2, default=str, ensure_ascii=False)


@mcp.tool()
async def get_blocked_accounts(limit: int = 50) -> str:
    """Accounts you have blocked."""
    limit = _clamp(limit, 1, 200)
    data = await _get_client().graphql("BlockedAccountsAll", {"count": limit})
    from spectre.parse import timeline

    _, users, cursor = timeline(data)
    return json.dumps({"users": users, "count": len(users), "next_cursor": cursor}, indent=2, default=str, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
#  Direct messages
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def send_dm(user_id: XId, text: str) -> str:
    """Send a direct message. No recall — confirm the recipient and text first.

    The recipient must accept DMs from you (mutual follow, or open message
    requests). Failures come back as `kind: validation` with X's reason.
    """
    return await _out(_get_writer().send_dm(str(user_id), text))


@mcp.tool()
async def get_dm_inbox(limit: int = 20) -> str:
    """Recent DM conversations and their latest messages.

    Returns both `messages` (flat, newest first) and `conversations` (threads with
    participants). Use a conversation_id from here with get_dm_conversation.
    """
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().dm_inbox(limit=limit))


@mcp.tool()
async def get_dm_conversation(conversation_id: str, limit: int = 50) -> str:
    """Every message in one DM thread, oldest first.

    Includes both directions and the participants' profiles. If a reply the user
    can see on x.com is missing here, X is not serving it to the cookie session —
    report that instead of assuming it does not exist.
    """
    limit = _clamp(limit, 1, 200)
    return await _out(_get_writer().dm_conversation(conversation_id, limit=limit))


@mcp.tool()
async def search_dm(query: str, limit: int = 20) -> str:
    """Search across all DM messages."""
    limit = _clamp(limit, 1, 50)
    return await _out(_get_writer().dm_search(query, limit=limit, kind="all"))


@mcp.tool()
async def search_dm_groups(query: str, limit: int = 20) -> str:
    """Search group DM conversations."""
    limit = _clamp(limit, 1, 50)
    return await _out(_get_writer().dm_search(query, limit=limit, kind="groups"))


@mcp.tool()
async def search_dm_people(query: str, limit: int = 20) -> str:
    """Search for people you have DM history with."""
    limit = _clamp(limit, 1, 50)
    return await _out(_get_writer().dm_search(query, limit=limit, kind="people"))


@mcp.tool()
async def get_dm_muted(limit: int = 20) -> str:
    """Muted DM conversations."""
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().dm_muted(limit=limit))


@mcp.tool()
async def dm_block_user(user_id: XId) -> str:
    """Block a user from sending you DMs (does not block them globally)."""
    return await _out(_get_writer().dm_block(str(user_id)))


@mcp.tool()
async def dm_unblock_user(user_id: XId) -> str:
    """Allow a user to DM you again."""
    return await _out(_get_writer().dm_unblock(str(user_id)))


# ══════════════════════════════════════════════════════════════
#  Lists
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_list_info(list_id: XId) -> str:
    """Name, description, member/subscriber counts and owner of a list."""
    return await _out(_get_writer().list_info(str(list_id)))


@mcp.tool()
async def create_list(name: str, description: str = "", private: bool = False) -> str:
    """Create a list. Returns the list_id you need for members and timelines."""
    return await _out(_get_writer().create_list(name, description, private))


@mcp.tool()
async def update_list(list_id: XId, name: str, description: str = "", private: Optional[bool] = None) -> str:
    """Rename or re-describe a list."""
    return await _out(_get_writer().update_list(str(list_id), name, description, private))


@mcp.tool()
async def delete_list(list_id: XId) -> str:
    """Delete a list permanently. Members are not affected."""
    return await _out(_get_writer().delete_list(str(list_id)))


@mcp.tool()
async def add_list_member(list_id: XId, user_id: XId) -> str:
    """Add an account to a list."""
    return await _out(_get_writer().add_list_member(str(list_id), str(user_id)))


@mcp.tool()
async def remove_list_member(list_id: XId, user_id: XId) -> str:
    """Remove an account from a list."""
    return await _out(_get_writer().remove_list_member(str(list_id), str(user_id)))


@mcp.tool()
async def get_list_timeline(list_id: XId, limit: int = 20) -> str:
    """Posts from the members of a list (the main reason to build lists)."""
    limit = _clamp(limit, 1, 200)
    return await _out(_get_scraper().list_timeline(str(list_id), limit=limit))


@mcp.tool()
async def get_list_members(list_id: XId, limit: int = 20) -> str:
    """Members of a list."""
    limit = _clamp(limit, 1, 500)
    return await _out(_get_scraper().list_members(str(list_id), limit=limit))


@mcp.tool()
async def get_list_subscribers(list_id: XId, limit: int = 20) -> str:
    """Accounts subscribed to a list."""
    limit = _clamp(limit, 1, 200)
    return await _out(_get_writer().list_subscribers(str(list_id), limit=limit))


@mcp.tool()
async def get_list_memberships(user_id: XId, limit: int = 20) -> str:
    """Lists a user belongs to — a fast map of someone's information diet."""
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().list_memberships(str(user_id), limit=limit))


@mcp.tool()
async def get_list_ownerships(user_id: XId, limit: int = 20) -> str:
    """Lists a user created."""
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().list_ownerships(str(user_id), limit=limit))


@mcp.tool()
async def subscribe_list(list_id: XId) -> str:
    """Subscribe to someone else's list so it appears in your timeline."""
    return await _out(_get_writer().subscribe_list(str(list_id)))


@mcp.tool()
async def unsubscribe_list(list_id: XId) -> str:
    """Unsubscribe from a list."""
    return await _out(_get_writer().unsubscribe_list(str(list_id)))


# ══════════════════════════════════════════════════════════════
#  Communities & topics
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_community_info(community_id: XId) -> str:
    """Community name, description, member count and join policy."""
    return await _out(_get_writer().community_info(str(community_id)))


@mcp.tool()
async def get_community_tweets(community_id: XId, limit: int = 20) -> str:
    """Posts inside a community."""
    limit = _clamp(limit, 1, 100)
    return await _out(_get_scraper().community_tweets(str(community_id), limit=limit))


@mcp.tool()
async def join_community(community_id: XId) -> str:
    """Join a community. Visible to its members."""
    return await _out(_get_writer().join_community(str(community_id)))


@mcp.tool()
async def leave_community(community_id: XId) -> str:
    """Leave a community."""
    return await _out(_get_writer().leave_community(str(community_id)))


@mcp.tool()
async def get_topic_info(topic_id: str) -> str:
    """Details and follow state of a topic."""
    return await _out(_get_writer().topic_info(str(topic_id)))


@mcp.tool()
async def follow_topic(topic_id: str) -> str:
    """Follow a topic (X's curated interest feeds)."""
    return await _out(_get_writer().follow_topic(str(topic_id)))


@mcp.tool()
async def unfollow_topic(topic_id: str) -> str:
    """Unfollow a topic."""
    return await _out(_get_writer().unfollow_topic(str(topic_id)))


@mcp.tool()
async def get_trends(woeid: int = 1, limit: int = 20) -> str:
    """Trending topics for a place (woeid 1 = worldwide).

    Find a woeid with get_trend_locations. Tweet volumes are present only for
    trends X decides to publish them for.
    """
    limit = _clamp(limit, 1, 50)
    return await _out(_get_writer().trends(woeid=woeid, limit=limit))


@mcp.tool()
async def get_trend_locations() -> str:
    """Places you can request trends for, with their woeids."""
    return await _out(_get_writer().trend_locations())


# ══════════════════════════════════════════════════════════════
#  Bookmarks
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_bookmarks(limit: int = 20, cursor: str = "") -> str:
    """Your bookmarked posts, newest first. Paginate with next_cursor."""
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().bookmarks(limit=limit, cursor=cursor or None))


@mcp.tool()
async def search_bookmarks(query: str, limit: int = 20, cursor: str = "") -> str:
    """Full-text search inside your bookmarks."""
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().search_bookmarks(query, limit=limit, cursor=cursor or None))


@mcp.tool()
async def clear_all_bookmarks() -> str:
    """Delete every bookmark. Irreversible — confirm first."""
    return await _out(_get_writer().clear_bookmarks())


@mcp.tool()
async def get_bookmark_folders() -> str:
    """List your bookmark folders.

    X gates bookmark folders behind Premium.
    """
    return await _out(_get_writer().bookmark_folders())


@mcp.tool()
async def create_bookmark_folder(name: str) -> str:
    """Create a bookmark folder (Premium-gated by X)."""
    return await _out(_get_writer().create_bookmark_folder(name))


@mcp.tool()
async def edit_bookmark_folder(folder_id: str, name: str) -> str:
    """Rename a bookmark folder (Premium-gated by X)."""
    return await _out(_get_writer().edit_bookmark_folder(folder_id, name))


@mcp.tool()
async def delete_bookmark_folder(folder_id: str) -> str:
    """Delete a bookmark folder. The bookmarks inside are not deleted."""
    return await _out(_get_writer().delete_bookmark_folder(folder_id))


@mcp.tool()
async def add_tweet_to_folder(folder_id: str, tweet_id: XId) -> str:
    """Put a bookmarked post into a folder."""
    return await _out(_get_writer().add_to_folder(folder_id, str(tweet_id)))


@mcp.tool()
async def remove_tweet_from_folder(folder_id: str, tweet_id: XId) -> str:
    """Remove a post from a folder (keeps the bookmark itself)."""
    return await _out(_get_writer().remove_from_folder(folder_id, str(tweet_id)))


@mcp.tool()
async def get_bookmark_folder_timeline(folder_id: str, limit: int = 20) -> str:
    """Posts inside one bookmark folder."""
    limit = _clamp(limit, 1, 100)
    return await _out(_get_writer().folder_timeline(folder_id, limit=limit))


# ══════════════════════════════════════════════════════════════
#  Scheduled posts & drafts
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def schedule_tweet(text: str, execute_at: str, reply_to: OptXId = None, media_ids: str = "") -> str:
    """Schedule a post for a future ISO-8601 time (e.g. 2026-12-01T12:00:00Z).

    Posting happens later without you — clear it with the user, and note the time
    is UTC unless the string carries an offset.
    """
    ids = [x.strip() for x in str(media_ids).split(",") if x.strip()] if media_ids else None
    return await _out(_get_writer().schedule_tweet(text, execute_at, reply_to=str(reply_to) if reply_to else None, media_ids=ids))


@mcp.tool()
async def get_scheduled_tweets() -> str:
    """Everything currently queued, with execute_at in ISO-8601 and state."""
    return await _out(_get_writer().scheduled_tweets())


@mcp.tool()
async def edit_scheduled_tweet(scheduled_id: str, text: str, execute_at: str) -> str:
    """Change the text or time of a queued post."""
    return await _out(_get_writer().edit_scheduled_tweet(scheduled_id, text, execute_at))


@mcp.tool()
async def delete_scheduled_tweet(scheduled_id: str) -> str:
    """Cancel a queued post."""
    return await _out(_get_writer().delete_scheduled_tweet(scheduled_id))


@mcp.tool()
async def create_draft(text: str) -> str:
    """Save a draft (never publishes by itself)."""
    return await _out(_get_writer().create_draft(text))


@mcp.tool()
async def get_drafts() -> str:
    """Your saved drafts."""
    return await _out(_get_writer().drafts())


@mcp.tool()
async def edit_draft(draft_id: str, text: str) -> str:
    """Rewrite a saved draft."""
    return await _out(_get_writer().edit_draft(draft_id, text))


@mcp.tool()
async def delete_draft(draft_id: str) -> str:
    """Delete a saved draft."""
    return await _out(_get_writer().delete_draft(draft_id))


# ══════════════════════════════════════════════════════════════
#  Profile
# ══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_account_settings() -> str:
    """The authenticated account as X sees it, plus a stale-handle warning.

    X removed the REST settings endpoint, so language/timezone are no longer
    exposed; everything here comes from GraphQL Viewer.
    """
    return await _out(_get_writer().account_settings())


@mcp.tool()
async def update_profile(name: str = "", bio: str = "", location: str = "", website: str = "") -> str:
    """Change your public display name, bio, location or website.

    Only the fields you pass are touched (empty means "leave it"). Bio cannot
    contain < > or & — X rejects them with code 120.
    """
    return await _out(
        _get_writer().update_profile(
            name=name or None, bio=bio if bio != "" else None, location=location or None, website=website or None
        )
    )


@mcp.tool()
async def update_profile_image(file_path: str) -> str:
    """Replace the avatar. Takes a local jpg/png/gif path."""
    return await _out(_get_writer().update_profile_image(file_path))


@mcp.tool()
async def update_profile_banner(file_path: str) -> str:
    """Replace the banner/header image (recommended 1500x500)."""
    return await _out(_get_writer().update_profile_banner(file_path))


@mcp.tool()
async def delete_profile_banner() -> str:
    """Remove the banner image."""
    return await _out(_get_writer().delete_profile_banner())


# ── Entry point ──


def main() -> None:
    """Run the Spectre MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
