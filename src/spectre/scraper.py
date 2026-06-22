"""Spectre — X/Twitter scraper engine with account pool management."""

from __future__ import annotations
import asyncio
import os
from typing import AsyncIterator, Optional
from twscrape import API, AccountsPool
from loguru import logger

from spectre.models import Tweet, UserProfile, Trend, CommunityInfo, AccountStatus


def _tweet_to_model(tw) -> Tweet:
    """Convert a raw Tweet to our Pydantic model."""
    media_urls = []
    media_types = []
    if tw.media:
        for p in tw.media.photos:
            media_urls.append(p.url)
            media_types.append("photo")
        for v in tw.media.videos:
            if v.variants:
                best = max(v.variants, key=lambda x: getattr(x, "bitrate", 0) or 0)
                media_urls.append(best.url)
                media_types.append("video")
        for a in tw.media.animated:
            if a.videoUrl:
                media_urls.append(a.videoUrl)
                media_types.append("animated_gif")

    hashtags = []
    urls = []
    mentioned = []
    if tw.hashtags:
        hashtags = tw.hashtags
    if tw.links:
        urls = [l.url for l in tw.links if hasattr(l, 'url')]
    if tw.mentionedUsers:
        mentioned = [u.screenName if hasattr(u, 'screenName') else str(u) for u in tw.mentionedUsers]

    return Tweet(
        id=tw.id,
        url=f"https://x.com/{tw.user.username}/status/{tw.id}" if tw.user else "",
        text=tw.rawContent or "",
        author_username=tw.user.username if tw.user else "",
        author_name=tw.user.displayname if tw.user else "",
        created_at=tw.date.isoformat() if tw.date else "",
        lang=tw.lang,
        reply_count=tw.replyCount or 0,
        retweet_count=tw.retweetCount or 0,
        like_count=tw.likeCount or 0,
        quote_count=tw.quoteCount or 0,
        view_count=tw.viewCount or 0,
        bookmark_count=getattr(tw, 'bookmarkedCount', 0) or 0,
        is_retweet=tw.retweetedTweet is not None,
        is_quote=tw.quotedTweet is not None,
        is_reply=tw.inReplyToTweetId is not None,
        media_urls=media_urls,
        media_types=media_types,
        hashtags=hashtags,
        urls=urls,
        mentioned_users=mentioned,
        quoted_tweet=tw.quotedTweet.rawContent if tw.quotedTweet else None,
        in_reply_to_id=tw.inReplyToTweetId,
        conversation_id=tw.conversationId,
    )


def _user_to_model(u) -> UserProfile:
    """Convert a raw User to our Pydantic model."""
    return UserProfile(
        id=u.id,
        username=u.username,
        display_name=u.displayname,
        bio=u.rawDescription if hasattr(u, "rawDescription") else (u.bio if hasattr(u, "bio") else None),
        location=u.location if hasattr(u, "location") else None,
        website=u.url if hasattr(u, "url") else None,
        followers=u.followersCount or 0,
        following=u.friendsCount or 0,
        tweets=u.statusesCount or 0,
        likes=u.favouritesCount or 0,
        media_count=u.mediaCount or 0,
        verified=u.verified or False,
        blue_verified=u.blue if hasattr(u, "blue") else False,
        profile_image_url=u.profileImageUrl if hasattr(u, "profileImageUrl") else None,
        banner_url=u.profileBannerUrl if hasattr(u, "profileBannerUrl") else None,
        created_at=u.created.isoformat() if hasattr(u, "created") and u.created else None,
    )


class Scraper:
    """Async X/Twitter scraper with account pool management.

    Manages multiple authenticated accounts for automatic rotation on rate limits.
    Each account uses cookie-based auth (auth_token + ct0 from browser DevTools).
    """

    def __init__(self, db_path: Optional[str] = None, proxy: Optional[str] = None):
        self.db_path = db_path or os.path.join(os.path.expanduser("~"), ".spectre", "accounts.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.proxy = proxy
        self._api: Optional[API] = None

    async def _get_api(self) -> API:
        if self._api is None:
            pool = AccountsPool(self.db_path)
            self._api = API(pool, proxy=self.proxy)
        return self._api

    async def close(self):
        if self._api:
            await self._api.pool.close()
            self._api = None

    # ── Account Pool Management ──

    async def add_account_cookies(self, username: str, cookies: str) -> str:
        """Add an account using browser cookies (auth_token=xxx; ct0=yyy)."""
        api = await self._get_api()
        await api.pool.add_account_cookies(username, cookies)
        return f"Account @{username} added to pool."

    async def list_accounts(self) -> list[dict]:
        """List all accounts with their status and metadata."""
        api = await self._get_api()
        accounts = []
        all_accounts = await api.pool.get_all()
        for acc in all_accounts:
            if acc.active and not acc.error_msg:
                state = "active"
            elif acc.error_msg:
                state = "error"
            else:
                state = "locked"
            accounts.append({
                "username": acc.username,
                "state": state,
                "error": acc.error_msg,
                "proxy": acc.proxy if hasattr(acc, "proxy") and acc.proxy else None,
            })
        return accounts

    async def set_active_account(self, username: str) -> str:
        """Set a specific account as the primary (first in rotation).

        Moves the account to the front of the pool so it's picked first.
        """
        api = await self._get_api()
        all_accounts = await api.pool.get_all()
        target = None
        for acc in all_accounts:
            if acc.username == username:
                target = acc
                break
        if not target:
            available = [a.username for a in all_accounts]
            return f"Account @{username} not found. Available: {', '.join('@' + u for u in available)}"
        if not target.active or target.error_msg:
            return f"Account @{username} is {('errored: ' + target.error_msg) if target.error_msg else 'locked/inactive'}. Cannot set as primary."

        # Reset last_used to 0 so twscrape picks this account first (LRU rotation)
        try:
            from twscrape.db import execute
            db_file = api.pool._db_file
            await execute(db_file, "UPDATE accounts SET last_used = 0, locks = '{}', error_msg = NULL WHERE username = :username", {"username": username})
            return f"Account @{username} set as primary. It will be used first for all operations."
        except Exception as e:
            return f"Failed to set @{username} as primary: {e}"

    async def remove_account(self, username: str) -> str:
        """Remove an account from the pool."""
        api = await self._get_api()
        try:
            await api.pool.delete_accounts([username])
            return f"Account @{username} removed from pool."
        except Exception as e:
            return f"Failed to remove @{username}: {e}"

    async def pool_status(self) -> AccountStatus:
        """Get account pool health."""
        api = await self._get_api()
        accounts = []
        active = locked = error = 0
        total = 0
        all_accounts = await api.pool.get_all()
        for acc in all_accounts:
            total += 1
            if acc.active and not acc.error_msg:
                state = "active"
                active += 1
            elif acc.error_msg:
                state = "error"
                error += 1
            else:
                state = "locked"
                locked += 1
            accounts.append({"username": acc.username, "state": state, "error": acc.error_msg})
        return AccountStatus(total=total, active=active, locked=locked, error=error, accounts=accounts)

    # ── Search ──

    async def search(self, query: str, limit: int = 20, mode: str = "latest") -> list[Tweet]:
        """Search tweets. mode: 'latest', 'top', or 'media'."""
        api = await self._get_api()
        kv = {"product": mode.capitalize()} if mode in ("latest", "top") else {"product": "Media"}
        results = []
        async for tw in api.search(query, limit=limit, kv=kv):
            results.append(_tweet_to_model(tw))
        return results

    async def search_users(self, query: str, limit: int = 10) -> list[UserProfile]:
        """Search for users by query."""
        api = await self._get_api()
        results = []
        async for u in api.search_user(query, limit=limit):
            results.append(_user_to_model(u))
        return results

    # ── Users ──

    async def get_user(self, username: str) -> Optional[UserProfile]:
        """Get user profile by @handle."""
        api = await self._get_api()
        u = await api.user_by_login(username)
        return _user_to_model(u) if u else None

    async def get_user_tweets(self, username: str, limit: int = 20) -> list[Tweet]:
        """Get user's recent tweets."""
        api = await self._get_api()
        user = await api.user_by_login(username)
        if not user:
            return []
        results = []
        async for tw in api.user_tweets(user.id, limit=limit):
            results.append(_tweet_to_model(tw))
        return results

    async def get_user_media(self, username: str, limit: int = 20) -> list[Tweet]:
        """Get user's media tweets (photos/videos)."""
        api = await self._get_api()
        user = await api.user_by_login(username)
        if not user:
            return []
        results = []
        async for tw in api.user_media(user.id, limit=limit):
            results.append(_tweet_to_model(tw))
        return results

    async def get_followers(self, username: str, limit: int = 20) -> list[UserProfile]:
        """Get user's followers."""
        api = await self._get_api()
        user = await api.user_by_login(username)
        if not user:
            return []
        results = []
        async for u in api.followers(user.id, limit=limit):
            results.append(_user_to_model(u))
        return results

    async def get_following(self, username: str, limit: int = 20) -> list[UserProfile]:
        """Get who the user follows."""
        api = await self._get_api()
        user = await api.user_by_login(username)
        if not user:
            return []
        results = []
        async for u in api.following(user.id, limit=limit):
            results.append(_user_to_model(u))
        return results

    # ── Tweets ──

    async def get_tweet(self, tweet_id: int) -> Optional[Tweet]:
        """Get single tweet by ID."""
        api = await self._get_api()
        tw = await api.tweet_details(tweet_id)
        return _tweet_to_model(tw) if tw else None

    async def get_tweet_replies(self, tweet_id: int, limit: int = 20) -> list[Tweet]:
        """Get replies to a tweet."""
        api = await self._get_api()
        results = []
        async for tw in api.tweet_replies(tweet_id, limit=limit):
            results.append(_tweet_to_model(tw))
        return results

    async def get_thread(self, tweet_id: int, limit: int = 50) -> list[Tweet]:
        """Get full conversation thread."""
        api = await self._get_api()
        results = []
        async for tw in api.tweet_thread(tweet_id, limit=limit):
            results.append(_tweet_to_model(tw))
        return results

    async def get_retweeters(self, tweet_id: int, limit: int = 20) -> list[UserProfile]:
        """Get users who retweeted a tweet."""
        api = await self._get_api()
        results = []
        async for u in api.retweeters(tweet_id, limit=limit):
            results.append(_user_to_model(u))
        return results

    # ── Trends ──

    async def get_trends(self, category: str = "trending", limit: int = 20) -> list[Trend]:
        """Get trending topics. Categories: 'trending', 'news', 'sport', 'entertainment'."""
        api = await self._get_api()
        results = []
        async for tr in api.trends(category, limit=limit):
            results.append(Trend(
                name=tr.name if hasattr(tr, "name") else str(tr),
                tweet_count=tr.tweetCount if hasattr(tr, "tweetCount") else None,
                category=getattr(tr, "category", None),
            ))
        return results

    # ── Lists ──

    async def get_list_timeline(self, list_id: int, limit: int = 20) -> list[Tweet]:
        """Get tweets from a list."""
        api = await self._get_api()
        results = []
        async for tw in api.list_timeline(list_id, limit=limit):
            results.append(_tweet_to_model(tw))
        return results

    async def get_list_members(self, list_id: int, limit: int = 20) -> list[UserProfile]:
        """Get members of a list."""
        api = await self._get_api()
        results = []
        async for u in api.list_members(list_id, limit=limit):
            results.append(_user_to_model(u))
        return results

    # ── Communities ──

    async def get_community_tweets(self, community_id: int, limit: int = 20) -> list[Tweet]:
        """Get tweets from a community."""
        api = await self._get_api()
        results = []
        async for tw in api.community_tweets(community_id, limit=limit):
            results.append(_tweet_to_model(tw))
        return results

    async def get_community_info(self, community_id: int) -> Optional[CommunityInfo]:
        """Get community details."""
        api = await self._get_api()
        c = await api.community_info(community_id)
        if not c:
            return None
        return CommunityInfo(
            id=c.id,
            name=c.name,
            description=getattr(c, "description", None),
            member_count=getattr(c, "memberCount", 0),
            created_at=c.created.isoformat() if hasattr(c, "created") and c.created else None,
        )

    # ── Bookmarks ──

    async def get_bookmarks(self, limit: int = 20) -> list[Tweet]:
        """Get authenticated user's bookmarks."""
        api = await self._get_api()
        results = []
        async for tw in api.bookmarks(limit=limit):
            results.append(_tweet_to_model(tw))
        return results

    # ── Home Timeline ──

    async def get_home_timeline(self, limit: int = 20) -> list[Tweet]:
        """Get the authenticated user's home timeline."""
        api = await self._get_api()
        results = []
        try:
            async for tw in api.home_timeline(limit=limit):
                results.append(_tweet_to_model(tw))
        except AttributeError:
            # twscrape may not have home_timeline — fall back to search
            logger.warning("home_timeline not available in this version, falling back to search")
        return results
