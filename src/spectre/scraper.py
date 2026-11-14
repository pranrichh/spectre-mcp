"""Timeline/search reads on top of twscrape, normalised to Spectre's shapes.

twscrape is good at the awkward paginated read endpoints (search, timelines,
follower pages) and bad at surfacing why something came back empty. This module
wraps it so that:

* the requested `limit` is the number of items returned — twscrape happily yields
  a whole page regardless of the limit you ask for;
* a long walk stops on a time budget with `truncated: true` instead of hanging;
* every result is the same dict shape the GraphQL layer returns.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import AsyncIterator, Optional

from twscrape import API, AccountsPool

from spectre.errors import XError
from spectre.parse import iso_time, sid


def _best_video(variants) -> Optional[str]:
    mp4 = [v for v in variants or [] if getattr(v, "contentType", "").startswith("video/")]
    if not mp4:
        return None
    return max(mp4, key=lambda v: getattr(v, "bitrate", 0) or 0).url


def tweet_dict(tw) -> dict:
    """twscrape Tweet -> Spectre tweet shape."""
    if tw is None:
        return {}
    user = getattr(tw, "user", None)
    media_urls, media_types = [], []
    media = getattr(tw, "media", None)
    if media:
        for photo in getattr(media, "photos", []) or []:
            if photo.url:
                media_urls.append(photo.url)
                media_types.append("photo")
        for video in getattr(media, "videos", []) or []:
            url = _best_video(getattr(video, "variants", []))
            if url:
                media_urls.append(url)
                media_types.append("video")
        for gif in getattr(media, "animated", []) or []:
            if getattr(gif, "videoUrl", None):
                media_urls.append(gif.videoUrl)
                media_types.append("animated_gif")

    quoted = getattr(tw, "quotedTweet", None)
    retweeted = getattr(tw, "retweetedTweet", None)
    link_objs = getattr(tw, "links", []) or []
    urls = []
    for link in link_objs:
        url = getattr(link, "url", None)
        if url:
            urls.append(url)
    return {
        "id": sid(tw.id),
        "url": getattr(tw, "url", None),
        "text": getattr(tw, "rawContent", "") or "",
        "author_id": sid(getattr(user, "id", None)),
        "author_username": getattr(user, "username", None),
        "author_name": getattr(user, "displayname", None),
        "created_at": iso_time(getattr(tw, "date", None)),
        "lang": getattr(tw, "lang", None),
        "reply_count": getattr(tw, "replyCount", 0) or 0,
        "retweet_count": getattr(tw, "retweetCount", 0) or 0,
        "like_count": getattr(tw, "likeCount", 0) or 0,
        "quote_count": getattr(tw, "quoteCount", 0) or 0,
        "view_count": getattr(tw, "viewCount", 0) or 0,
        "bookmark_count": getattr(tw, "bookmarkedCount", 0) or 0,
        "is_retweet": retweeted is not None,
        "is_quote": quoted is not None,
        "is_reply": getattr(tw, "inReplyToTweetId", None) is not None,
        "in_reply_to_id": sid(getattr(tw, "inReplyToTweetId", None)),
        "conversation_id": sid(getattr(tw, "conversationId", None)),
        "media_urls": media_urls,
        "media_types": media_types,
        "hashtags": list(getattr(tw, "hashtags", []) or []),
        "urls": urls,
        "mentioned_users": [getattr(u, "username", None) for u in (getattr(tw, "mentionedUsers", []) or []) if getattr(u, "username", None)],
        "quoted_tweet_id": sid(getattr(quoted, "id", None)),
        "quoted_tweet": getattr(quoted, "rawContent", None),
        "retweeted_tweet_id": sid(getattr(retweeted, "id", None)),
    }


def user_dict(u) -> dict:
    """twscrape User -> Spectre user shape."""
    if u is None:
        return {}
    website = getattr(u, "url", None)
    links = getattr(u, "descriptionLinks", None) or []
    if links:
        website = getattr(links[0], "url", website)
    return {
        "id": sid(getattr(u, "id", None)),
        "username": getattr(u, "username", None),
        "display_name": getattr(u, "displayname", None),
        "bio": getattr(u, "rawDescription", None),
        "location": getattr(u, "location", None) or None,
        "website": website,
        "followers": getattr(u, "followersCount", 0) or 0,
        "following": getattr(u, "friendsCount", 0) or 0,
        "tweets": getattr(u, "statusesCount", 0) or 0,
        "likes": getattr(u, "favouritesCount", 0) or 0,
        "media_count": getattr(u, "mediaCount", 0) or 0,
        "verified": bool(getattr(u, "verified", False)),
        "blue_verified": bool(getattr(u, "blue", False)),
        "profile_image_url": getattr(u, "profileImageUrl", None),
        "banner_url": getattr(u, "profileBannerUrl", None),
        "created_at": iso_time(getattr(u, "created", None)),
        "protected": bool(getattr(u, "protected", False)),
    }


async def _take(gen: AsyncIterator, limit: int, deadline: float) -> tuple[list, bool]:
    """Consume at most `limit` items, never blocking past the deadline.

    twscrape's generators sleep while their account pool waits for a rate-limit
    window, so a plain `async for` can hang for hours. Waiting per item with the
    remaining budget turns that into "partial results, truncated=True".
    """
    items: list = []
    iterator = gen.__aiter__()
    while len(items) < limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return items, True
        try:
            item = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return items, False
        except asyncio.TimeoutError:
            return items, True
        items.append(item)
    return items, False


class Scraper:
    """Paginated reads through twscrape, sharing the caller's account pool."""

    def __init__(self, pool: AccountsPool, proxy: Optional[str] = None, default_budget: float = 90.0):
        self._pool = pool
        self.proxy = proxy
        self.default_budget = default_budget
        self._api: Optional[API] = None

    async def api(self) -> API:
        if self._api is None:
            self._api = API(self._pool, proxy=self.proxy)
        return self._api

    async def close(self) -> None:
        # twscrape's AccountsPool has no close(); drop the reference so the
        # connection is garbage collected with the pool the server owns.
        self._api = None


    async def _ensure_available(self, queue: str) -> None:
        """Fail fast when every account is locked for this queue.

        twscrape implements waits by sleeping inside the generator, so without
        this a rate-limited search blocks the tool for minutes. Reading the lock
        table first turns that into an immediate, actionable error.
        """
        accounts = await self._pool.get_all()
        if not accounts:
            raise XError("No accounts in the pool.", kind="auth")
        waits: list[int] = []
        for account in accounts:
            locks = account.locks if isinstance(account.locks, dict) else {}
            until = locks.get(queue)
            if not until:
                return
            try:
                unlock_at = datetime.fromisoformat(str(until).replace("Z", "+00:00")).timestamp()
            except ValueError:
                return
            remaining = int(unlock_at - time.time())
            if remaining <= 0:
                return
            waits.append(remaining)
        if waits:
            retry = min(waits)
            raise XError(
                f"All accounts are rate limited for {queue}.",
                kind="rate_limit",
                retry_after=retry,
                hint=f"Wait {retry}s, or add another account (spectre add ...).",
            )

    # ── lookups ──

    async def _user(self, username: str):
        api = await self.api()
        user = await api.user_by_login(username.lstrip("@"))
        if not user:
            raise XError(f"User @{username} not found.", kind="not_found", code=50)
        return user

    async def user(self, username: str) -> dict:
        await self._ensure_available("UserByScreenName")
        return user_dict(await self._user(username))

    async def user_by_id(self, user_id: str) -> dict:
        await self._ensure_available("UserByRestId")
        api = await self.api()
        user = await api.user_by_id(str(user_id))
        if not user:
            raise XError(f"No user with id {user_id}.", kind="not_found", code=50)
        return user_dict(user)

    # ── search ──

    async def search(self, query: str, limit: int = 20, mode: str = "latest") -> list[dict]:
        await self._ensure_available("SearchTimeline")
        api = await self.api()
        product = {"latest": "Latest", "top": "Top", "media": "Media"}.get(mode.lower())
        if not product:
            raise XError('mode must be "latest", "top" or "media".', kind="validation")
        kv = {"product": product}
        if mode == "media":
            kv["with_tweet_replies"] = False
        deadline = time.monotonic() + self.default_budget
        tweets, truncated = await _take(api.search(query, limit=limit, kv=kv), limit, deadline)
        if truncated and not tweets:
            raise XError(
                "No response from X before the time budget ran out.",
                kind="rate_limit",
                hint="The account is probably locked or rate limited — check pool_status / get_rate_limits.",
            )
        return [tweet_dict(t) for t in tweets]

    async def search_users(self, query: str, limit: int = 10) -> list[dict]:
        await self._ensure_available("SearchTimeline")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        users, _ = await _take(api.search_user(query, limit=limit), limit, deadline)
        return [user_dict(u) for u in users]

    # ── timelines ──

    async def user_tweets(self, username: str, limit: int = 20, replies: bool = False, media_only: bool = False) -> dict:
        await self._ensure_available("UserMedia" if media_only else ("UserTweetsAndReplies" if replies else "UserTweets"))
        api = await self.api()
        user = await self._user(username)
        gen = api.user_media(user.id, limit=limit) if media_only else (
            api.user_tweets_and_replies(user.id, limit=limit) if replies else api.user_tweets(user.id, limit=limit)
        )
        deadline = time.monotonic() + self.default_budget
        tweets, truncated = await _take(gen, limit, deadline)
        return {"tweets": [tweet_dict(t) for t in tweets], "count": len(tweets), "truncated": truncated}

    async def followers(self, username: str, limit: int = 20) -> dict:
        return await self._connections(username, limit, followers=True)

    async def following(self, username: str, limit: int = 20) -> dict:
        return await self._connections(username, limit, followers=False)

    async def _connections(self, username: str, limit: int, followers: bool) -> dict:
        await self._ensure_available("Followers" if followers else "Following")
        api = await self.api()
        user = await self._user(username)
        gen = api.followers(user.id, limit=limit) if followers else api.following(user.id, limit=limit)
        deadline = time.monotonic() + max(self.default_budget, min(300.0, limit / 4))
        users, truncated = await _take(gen, limit, deadline)
        return {
            "users": [user_dict(u) for u in users],
            "count": len(users),
            "truncated": truncated,
            "total_available": getattr(user, "followersCount", None) if followers else getattr(user, "friendsCount", None),
        }

    async def verified_followers(self, user_id: str, limit: int = 20) -> dict:
        await self._ensure_available("BlueVerifiedFollowers")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        users, truncated = await _take(api.verified_followers(int(user_id), limit=limit), limit, deadline)
        return {"users": [user_dict(u) for u in users], "count": len(users), "truncated": truncated}

    # ── conversations ──

    async def tweet(self, tweet_id: str) -> dict:
        await self._ensure_available("TweetDetail")
        api = await self.api()
        tw = await api.tweet_details(int(tweet_id))
        if not tw:
            raise XError(f"Tweet {tweet_id} not found.", kind="not_found", code=144)
        return tweet_dict(tw)

    async def replies(self, tweet_id: str, limit: int = 20) -> dict:
        await self._ensure_available("TweetDetail")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        tweets, truncated = await _take(api.tweet_replies(int(tweet_id), limit=limit), limit, deadline)
        return {"tweets": [tweet_dict(t) for t in tweets], "count": len(tweets), "truncated": truncated}

    async def thread(self, tweet_id: str, limit: int = 50) -> dict:
        await self._ensure_available("TweetDetail")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        tweets, truncated = await _take(api.tweet_thread(int(tweet_id), limit=limit), limit, deadline)
        return {"tweets": [tweet_dict(t) for t in tweets], "count": len(tweets), "truncated": truncated}

    async def retweeters(self, tweet_id: str, limit: int = 20) -> dict:
        await self._ensure_available("Retweeters")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        users, truncated = await _take(api.retweeters(int(tweet_id), limit=limit), limit, deadline)
        return {"users": [user_dict(u) for u in users], "count": len(users), "truncated": truncated}

    # ── lists & communities ──

    async def list_timeline(self, list_id: str, limit: int = 20) -> dict:
        await self._ensure_available("ListLatestTweetsTimeline")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        tweets, truncated = await _take(api.list_timeline(int(list_id), limit=limit), limit, deadline)
        return {"tweets": [tweet_dict(t) for t in tweets], "count": len(tweets), "truncated": truncated}

    async def list_members(self, list_id: str, limit: int = 20) -> dict:
        await self._ensure_available("ListMembers")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        users, truncated = await _take(api.list_members(int(list_id), limit=limit), limit, deadline)
        return {"users": [user_dict(u) for u in users], "count": len(users), "truncated": truncated}

    async def community_tweets(self, community_id: str, limit: int = 20) -> dict:
        await self._ensure_available("CommunityTweetsTimeline")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        tweets, truncated = await _take(api.community_tweets(int(community_id), limit=limit), limit, deadline)
        return {"tweets": [tweet_dict(t) for t in tweets], "count": len(tweets), "truncated": truncated}

    async def community_info(self, community_id: str) -> dict:
        api = await self.api()
        info = await api.community_info(int(community_id))
        if not info:
            raise XError(f"Community {community_id} not found.", kind="not_found")
        return {
            "community_id": sid(getattr(info, "id", community_id)),
            "name": getattr(info, "name", None),
            "description": getattr(info, "description", None),
            "member_count": getattr(info, "memberCount", 0) or 0,
            "created_at": iso_time(getattr(info, "created", None)),
            "admin_ids": [sid(a) for a in (getattr(info, "adminIds", None) or [])],
        }

    # ── bookmarks ──

    async def bookmarks(self, limit: int = 20) -> dict:
        await self._ensure_available("Bookmarks")
        api = await self.api()
        deadline = time.monotonic() + self.default_budget
        tweets, truncated = await _take(api.bookmarks(limit=limit), limit, deadline)
        return {"tweets": [tweet_dict(t) for t in tweets], "count": len(tweets), "truncated": truncated}
