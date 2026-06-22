"""Write operations for X/Twitter via GraphQL mutations and REST API.

Handles all write operations (post, like, retweet, bookmark, follow, etc.)
using the same cookie-based auth as read operations. No OAuth 1.0a needed.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx
from loguru import logger

# X's web app bearer token (public, embedded in the JS bundle)
BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
GQL_URL = "https://x.com/i/api/graphql"

# Default feature flags required by most GraphQL operations
DEFAULT_FEATURES = {
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_home_pinned_timelines_enabled": True,
    "blue_business_profile_image_shape_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "graphql_timeline_v2_bookmark_timeline": True,
    "hidden_profile_likes_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "interactive_text_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_richtext_consumption_enabled": True,
    "profile_foundations_tweet_stats_enabled": True,
    "profile_foundations_tweet_stats_tweet_frequency": True,
    "responsive_web_birdwatch_note_limit_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_text_conversations_enabled": False,
    "responsive_web_twitter_article_data_v2_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": False,
    "responsive_web_twitter_blue_verified_badge_is_enabled": True,
    "rweb_lists_timeline_redesign_enabled": True,
    "spaces_2022_h2_clipping": True,
    "spaces_2022_h2_spaces_communities": True,
    "standardized_nudges_misinfo": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "verified_phone_label_enabled": False,
    "vibe_api_enabled": True,
    "view_counts_everywhere_api_enabled": True,
}

# Default variables required by many GraphQL operations (matches trevorhobenshield)
DEFAULT_VARIABLES = {
    "count": 1000,
    "withSafetyModeUserFields": True,
    "includePromotedContent": True,
    "withQuickPromoteEligibilityTweetFields": True,
    "withVoice": True,
    "withV2Timeline": True,
    "withDownvotePerspective": False,
    "withBirdwatchNotes": True,
    "withCommunity": True,
    "withSuperFollowsUserFields": True,
    "withMessages": True,
}

# Standard feature flags for timeline/profile queries (matches X web app)
TIMELINE_FEATURES = {
    "rweb_video_screen_enabled": False,
    "rweb_cashtags_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
}
TIMELINE_FIELD_TOGGLES = ["withPayments", "withAuxiliaryUserLabels"]

# Write operation IDs — these rotate every few months.
# Update via env vars: SPECTRE_OP_CREATE_TWEET, etc.
# Source: fa0311/TwitterInternalAPIDocument (auto-generated from X's JS)
OPERATIONS = {
    "CreateTweet": "DQIp0b4mKIciCAZ3bfrwAA",
    "CreateRetweet": "mbRO74GrOvSfRcJnlMapnQ",
    "DeleteRetweet": "ZyZigVsNiFO6v1dEks1eWg",
    "FavoriteTweet": "lI07N6Otwv1PhnEgXILM7A",
    "UnfavoriteTweet": "ZYKSe-w7KEslx3JhSIk5LA",
    "CreateBookmark": "aoDbu3RHznuiSkQ9aNM67Q",
    "DeleteBookmark": "Wlmlj2-xzyS1GN3a6cj-mQ",
    # Follow/Unfollow use REST v1.1 (friendships/create.json, friendships/destroy.json)
    "DeleteTweet": "nxpZCY2K-I6QoFHAHeojFQ",
    "CreateList": "hQAsnViq2BrMLbPuQ9umDA",
    "UpdateList": "4dCEFWtxEbhnSLcJdJ6PNg",
    "ListAddMember": "P8tyfv2_0HzofrB5f6_ugw",
    "ListRemoveMember": "DBZowzFN492FFkBPBptCwg",
    "JoinCommunity": "8lR4bNpbNZKbmK6MwZtU-Q",
    "LeaveCommunity": "0YUrwfndvmPYbgmQxPFySQ",
    "useSendMessageMutation": "MaxK2PKX1F9Z-9SwqwavTw",
    # Scheduled tweets
    "CreateScheduledTweet": "LCVzRQGxOaGnOnYH01NQXg",
    "FetchScheduledTweets": "H2elmT2R9DLhWoo0DZFNkA",
    "DeleteScheduledTweet": "CTOVqej0JBXAZSwkp1US0g",
    # Draft tweets
    "CreateDraftTweet": "cH9HZWz_EW9gnswvA4ZRiQ",
    "FetchDraftTweets": "L9RqKWmAWxK6vGtR3Qdsxw",
    "DeleteDraftTweet": "bkh9G3FGgTldS9iTKWWYYw",
    # Bookmark folders
    "BookmarkFoldersSlice": "i78YDd0Tza-dV4SYs58kRg",
    "createBookmarkFolder": "6Xxqpq8TM_CREYiuof_h5w",
    "DeleteBookmarkFolder": "2UTTsO-6zs93XqlEUZPsSg",
    "EditBookmarkFolder": "a6kPp1cS1Dgbsjhapz1PNw",
    "bookmarkTweetToFolder": "4KHZvvNbHNf07bsgnL9gWA",
    "RemoveTweetFromBookmarkFolder": "2Qbj9XZvtUvyJB4gFwWfaA",
    # Lists
    "DeleteList": "UnN9Th1BDbeLjpgjGSpL3Q",
    # Topics
    "TopicFollow": "ElqSLWFmsPL4NlZI5e1Grg",
    "TopicUnfollow": "srwjU6JM_ZKTj_QMfUGNcw",
    # Community Notes
    "BirdwatchCreateNote": "c9kb2zackjmDEFG8hmii5Q",
    "BirdwatchFetchNotes": "ZGMhf1M7kPKMOhEk1nz0Yw",
    "BirdwatchCreateRating": "gbshFt1Vmddrlio4vHWhhQ",
    # Account Settings
    "PinTweet": "VIHsNu89pK-kW35JpHq7Xw",
    "UnpinTweet": "BhKei844ypCyLYCg0nwigw",
    "CreateHighlight": "7jEc7ECTTDcNaqsMhjTxXg",
    "DeleteHighlight": "ea-VVDSLIEYNY2_2aPg3Uw",
    "UserHighlightsTweets": "W3_o6ulKbViS-IIJJYmzmQ",
    "BlueVerifiedFollowers": "OBBd6Dw-4qEYbsu3hGkyxg",
    "MutedAccounts": "RiyYWu0qlF6QyfUkDOCoxA",
    "BlockedAccountsAll": "dXAVNBZjLy9JoZd6JCjc-A",
    "DmAllSearchSlice": "iRnhDpR6lACfABoAfB15Fw",
    "DmGroupSearchSlice": "LxrvmqF3Lokl_BYZ1c83LA",
    "DmMutedTimeline": "QyDqQSyzNScMdXRc0bl-Lw",
    "DmPeopleSearchSlice": "c1MnRRmI-_Bggpntlq9-hQ",
    "Likes": "enfPHxWV3DDAG1XBw3obTg",
    "BookmarkFolderTimeline": "ANUliFjDZdjSWb_3FNe9sQ",
    "BookmarkSearchTimeline": "vqy7GkKMR5TYk8_ysuhmfA",
    "BookmarksAllDelete": "skiACZKC1GDYli-M8RzEPQ",
    "dmBlockUser": "IYw9u1KEhrS-t-BXsau4Uw",
    "dmUnblockUser": "Krbs6Nak_o7liWQwfV1jOQ",
    # Home Timeline
    "HomeTimeline": "MP5Mn45hEc4i_q_UwIHBkw",
    "HomeLatestTimeline": "n2m8OTpLdsM3Zhv33ljKoA",
    # Edit operations
    "EditDraftTweet": "JIeXE-I6BZXHfxsgOkyHYQ",
    "EditScheduledTweet": "_mHkQ5LHpRRjSXKOcG6eZw",
    # Tweet info
    "Favoriters": "6SsQvi19ZR-txuiu7Uo2OA",
    "TweetEditHistory": "pMXJaYs8H1xEAJ4NOhxIoQ",
    "SimilarPosts": "V44P4GxNvHeAgh5zTFLljw",
    # Social
    "RemoveFollower": "QpNfg0kpPRfjROQ_9eOLXA",
    "PinReply": "GA2_1uKP9b_GyR4MVAQXAw",
    "UnpinReply": "iRe6ig5OV1EzOtldNIuGDQ",
    "FollowersYouKnow": "Zo44022i9Z7XcX7T-Ez7Og",
    # Lists (extended)
    "ListSubscribe": "HclInJtqqdh2wU7Q5-cevA",
    "ListUnsubscribe": "GcrwbuN8ZdD84wYDaBlSSg",
    "ListMemberships": "jQSaHZiOSU9LcOTyid6Xlw",
    "ListOwnerships": "_4Kw0FQkvL1gb8NgcO_7Rw",
    "ListSubscribers": "T_fzE_mzqtsd-rhNvL5YaQ",
    # Topics (extended)
    "TopicByRestId": "4OUZZOonV2h60I0wdlQb_w",
    # Notifications
    "NotificationsTimeline": "N3mgBYxj7qj5GUZmyYuKFg",
    # User (extended)
    "UserTweetsAndReplies": "plVqzvVGaDxbFEPoOe_i-A",
}

# Allow env overrides for operation IDs
for op_name in OPERATIONS:
    env_key = f"SPECTRE_OP_{op_name.upper()}"
    if env_val := os.environ.get(env_key):
        OPERATIONS[op_name] = env_val


def _get_operation(name: str) -> str:
    op_id = OPERATIONS.get(name)
    if not op_id:
        raise ValueError(f"Unknown operation: {name}")
    return f"{op_id}/{name}"


def _rate_limit_error(operation: str, retry_after: int | None = None) -> dict:
    """Build a clear rate limit error message for agents."""
    msg = {
        "error": "rate_limited",
        "operation": operation,
        "message": f"X rate limit hit on {operation}.",
    }
    if retry_after:
        msg["retry_after_seconds"] = retry_after
        msg["instruction"] = f"Wait {retry_after} seconds, then retry. Or use list_accounts() to see available accounts and set_active_account() to switch to a different one."
    else:
        msg["instruction"] = "Use list_accounts() to see available accounts. Use set_active_account(username) to switch to a different account. Or wait a few minutes and retry."
    return msg


class Writer:
    """Authenticated write operations with account pool management.

    Supports selecting a specific account for operations, or auto-selects
    the first active account. Rate limits are caught and surfaced clearly.
    """

    def __init__(self, pool, proxy: Optional[str] = None, db_path: Optional[str] = None):
        self.pool = pool
        self.proxy = proxy
        self.db_path = db_path
        self._preferred_account: Optional[str] = None
        self._auto_rotate: bool = True  # When False, only use preferred account

    def set_preferred_account(self, username: Optional[str]) -> None:
        """Set a preferred account for write operations. None = auto-select."""
        self._preferred_account = username

    def set_auto_rotate(self, enabled: bool) -> None:
        """Enable/disable automatic account rotation on rate limits.

        When disabled and a preferred account is set, only that account is used.
        Rate limits will be returned as errors instead of silently rotating.
        """
        self._auto_rotate = enabled

    async def _get_session(self, preferred: Optional[str] = None) -> tuple[httpx.AsyncClient, dict]:
        """Get an authenticated HTTP client from the pool.

        Args:
            preferred: Username to prefer. Falls back to self._preferred_account, then first active.
        """
        accounts = await self.pool.get_all()
        if not accounts:
            raise RuntimeError("No accounts in pool. Add one with: spectre add <username> \"auth_token=xxx; ct0=yyy\"")

        target = preferred or self._preferred_account
        acc = None

        # Try preferred account first
        if target:
            for a in accounts:
                if a.username == target and a.active and not a.error_msg:
                    acc = a
                    break
            if not acc:
                if not self._auto_rotate:
                    raise RuntimeError(f"Account @{target} is not available and auto-rotate is disabled. Use list_accounts() to check status, or enable auto-rotate.")
                available = [a.username for a in accounts if a.active and not a.error_msg]
                if available:
                    logger.warning(f"Preferred account @{target} not available, using @{available[0]}")
                    acc = next(a for a in accounts if a.username == available[0])

        # Fall back to first active (only if auto-rotate is on)
        if not acc:
            for a in accounts:
                if a.active and not a.error_msg:
                    acc = a
                    break

        if not acc:
            error_accounts = [a for a in accounts if a.error_msg]
            if error_accounts:
                errors = "; ".join(f"@{a.username}: {a.error_msg}" for a in error_accounts)
                raise RuntimeError(f"All accounts have errors: {errors}. Use set_active_account() to reset or add_account_cookies() to add fresh cookies.")
            raise RuntimeError("No active accounts. Use add_account_cookies() to add one.")

        cookies = acc.cookies
        if isinstance(cookies, str):
            cookies = json.loads(cookies)

        headers = {
            "authorization": f"Bearer {BEARER_TOKEN}",
            "x-csrf-token": cookies.get("ct0", ""),
            "content-type": "application/json",
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "user-agent": acc.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "referer": "https://x.com/",
        }

        cookie_jar = httpx.Cookies()
        cookie_jar.set("auth_token", cookies.get("auth_token", ""), domain=".x.com")
        cookie_jar.set("ct0", cookies.get("ct0", ""), domain=".x.com")
        # Also set cookies for twitter.com and api.twitter.com (REST v1.1 endpoints)
        cookie_jar.set("auth_token", cookies.get("auth_token", ""), domain=".twitter.com")
        cookie_jar.set("ct0", cookies.get("ct0", ""), domain=".twitter.com")
        cookie_jar.set("auth_token", cookies.get("auth_token", ""), domain="api.twitter.com")
        cookie_jar.set("ct0", cookies.get("ct0", ""), domain="api.twitter.com")

        proxy_url = self.proxy or acc.proxy
        client = httpx.AsyncClient(
            headers=headers,
            cookies=cookie_jar,
            proxy=proxy_url,
            timeout=30,
        )
        return client, {"username": acc.username}

    async def _post(self, operation: str, variables: dict, features: dict | None = None, field_toggles: dict | None = None) -> dict:
        """Make an authenticated POST to X's GraphQL API."""
        op_path = _get_operation(operation)
        url = f"{GQL_URL}/{op_path}"
        path = f"/i/api/graphql/{op_path}"

        body: dict = {"variables": DEFAULT_VARIABLES | variables}
        body["queryId"] = op_path.split("/")[0]  # Include queryId in body (twitter-cli pattern)
        body["features"] = features or DEFAULT_FEATURES
        if field_toggles is not None:
            body["fieldToggles"] = field_toggles

        client, acc_info = await self._get_session()
        try:
            # Generate x-client-transaction-id
            try:
                from twscrape.queue_client import XClIdGenStore
                gen = await XClIdGenStore.get(acc_info["username"])
                txn_id = gen.calc("POST", path)
                client.headers["x-client-transaction-id"] = txn_id
            except Exception as e:
                logger.warning(f"Could not generate x-client-transaction-id: {e}")

            resp = await client.post(url, json=body)

            # Handle rate limits
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("x-rate-limit-reset", 0))
                logger.error(f"Rate limited ({operation}): retry after {retry_after}")
                return _rate_limit_error(operation, retry_after)

            try:
                data = resp.json()
            except Exception:
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:300], "account": acc_info["username"]}

            if resp.status_code != 200:
                logger.error(f"Write failed ({operation}): {resp.status_code} {json.dumps(data)[:300]}")
                return {"error": f"HTTP {resp.status_code}", "detail": data, "account": acc_info["username"]}

            # X sometimes returns errors alongside data (non-fatal DecodeException)
            # Only treat as error if there's no data alongside it
            if "errors" in data and "data" not in data:
                errors = "; ".join(e.get("message", str(e)) for e in data["errors"])
                logger.error(f"Write errors ({operation}): {errors}")
                return {"error": errors, "account": acc_info["username"]}
            if "errors" in data:
                logger.warning(f"Write warnings ({operation}): {data['errors']}")

            return data
        finally:
            await client.aclose()

    async def _get(self, operation: str, variables: dict, features: dict | None = None, field_toggles: list | None = None) -> dict:
        """Make an authenticated GET to X's GraphQL API."""
        op_path = _get_operation(operation)
        url = f"{GQL_URL}/{op_path}"
        path = f"/i/api/graphql/{op_path}"

        params = {"variables": json.dumps(variables)}
        if features:
            params["features"] = json.dumps(features)
        if field_toggles is not None:
            params["fieldToggles"] = json.dumps(field_toggles)

        client, acc_info = await self._get_session()
        try:
            # Generate x-client-transaction-id (same as _post)
            try:
                from twscrape.queue_client import XClIdGenStore
                gen = await XClIdGenStore.get(acc_info["username"])
                txn_id = gen.calc("GET", path)
                client.headers["x-client-transaction-id"] = txn_id
            except Exception as e:
                logger.warning(f"Could not generate x-client-transaction-id: {e}")

            resp = await client.get(url, params=params)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("x-rate-limit-reset", 0))
                return _rate_limit_error(operation, retry_after)

            try:
                data = resp.json()
            except Exception:
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:300], "account": acc_info["username"]}

            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "detail": data, "account": acc_info["username"]}

            if "errors" in data:
                errors = "; ".join(e.get("message", str(e)) for e in data["errors"])
                return {"error": errors, "account": acc_info["username"]}

            return data
        finally:
            await client.aclose()

    # ── Tweet Operations ──

    async def post_tweet(self, text: str, reply_to: int | None = None, quote_tweet: int | None = None, media_ids: list[int] | None = None) -> dict:
        """Post a new tweet, optionally as a reply or quote."""
        media_entities = [{"media_id": str(mid), "tagged_users": []} for mid in (media_ids or [])]
        variables = {
            "tweet_text": text,
            "dark_request": False,
            "media": {"media_entities": media_entities, "possibly_sensitive": False},
            "semantic_annotation_ids": [],
        }
        if reply_to:
            variables["reply"] = {"in_reply_to_tweet_id": str(reply_to), "exclude_reply_user_ids": []}
        if quote_tweet:
            variables["attachment_url"] = f"https://x.com/i/status/{quote_tweet}"

        features = {
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": True,
            "responsive_web_jetfuel_frame": False,
            "responsive_web_grok_share_attachment_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "responsive_web_grok_show_grok_translated_post": False,
            "responsive_web_grok_analysis_button_from_backend": True,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "verified_phone_label_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "responsive_web_grok_image_annotation_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }

        data = await self._post("CreateTweet", variables, features=features, field_toggles={})

        tweet_id = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
            .get("rest_id")
        )
        if tweet_id:
            return {"status": "posted", "tweet_id": tweet_id, "url": f"https://x.com/i/status/{tweet_id}"}
        if "error" in data:
            return data
        return {"status": "unknown", "response": data}

    async def delete_tweet(self, tweet_id: int) -> dict:
        """Delete a tweet."""
        variables = {"tweet_id": str(tweet_id)}
        data = await self._post("DeleteTweet", variables)
        return {"status": "deleted", "tweet_id": tweet_id}

    # ── Engagement Operations ──

    async def like(self, tweet_id: int) -> dict:
        variables = {"tweet_id": str(tweet_id)}
        await self._post("FavoriteTweet", variables)
        return {"status": "liked", "tweet_id": tweet_id}

    async def unlike(self, tweet_id: int) -> dict:
        variables = {"tweet_id": str(tweet_id)}
        await self._post("UnfavoriteTweet", variables)
        return {"status": "unliked", "tweet_id": tweet_id}

    async def retweet(self, tweet_id: int) -> dict:
        variables = {"tweet_id": str(tweet_id), "dark_request": False}
        await self._post("CreateRetweet", variables)
        return {"status": "retweeted", "tweet_id": tweet_id}

    async def unretweet(self, tweet_id: int) -> dict:
        variables = {"source_tweet_id": str(tweet_id), "dark_request": False}
        await self._post("DeleteRetweet", variables)
        return {"status": "unretweeted", "tweet_id": tweet_id}

    async def bookmark(self, tweet_id: int) -> dict:
        variables = {"tweet_id": str(tweet_id)}
        await self._post("CreateBookmark", variables)
        return {"status": "bookmarked", "tweet_id": tweet_id}

    async def unbookmark(self, tweet_id: int) -> dict:
        variables = {"tweet_id": str(tweet_id)}
        await self._post("DeleteBookmark", variables)
        return {"status": "unbookmarked", "tweet_id": tweet_id}

    # ── Social Operations ──

    async def follow(self, user_id: int) -> dict:
        """Follow a user via REST API."""
        result = await self._rest_post("friendships/create.json", {"user_id": str(user_id)})
        if "error" in result:
            return result
        return {"status": "followed", "user_id": user_id}

    async def unfollow(self, user_id: int) -> dict:
        """Unfollow a user via REST API."""
        result = await self._rest_post("friendships/destroy.json", {"user_id": str(user_id)})
        if "error" in result:
            return result
        return {"status": "unfollowed", "user_id": user_id}

    # ── REST API Operations (mute/block use v1.1 REST, not GraphQL) ──

    async def _rest_post(self, endpoint: str, data: dict) -> dict:
        """Make an authenticated POST to X's REST API v1.1."""
        url = f"https://api.twitter.com/1.1/{endpoint}"
        client, acc_info = await self._get_session()
        try:
            # Pop content-type so httpx sets application/x-www-form-urlencoded
            original_ct = client.headers.pop("content-type", None)
            resp = await client.post(url, data=data)
            if original_ct:
                client.headers["content-type"] = original_ct
            result = resp.json()

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("x-rate-limit-reset", 0))
                return _rate_limit_error(endpoint, retry_after)

            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "detail": result, "account": acc_info["username"]}
            return result
        finally:
            await client.aclose()

    async def mute(self, user_id: int) -> dict:
        result = await self._rest_post("mutes/users/create.json", {"user_id": str(user_id)})
        if "error" in result:
            return result
        return {"status": "muted", "user_id": user_id}

    async def unmute(self, user_id: int) -> dict:
        result = await self._rest_post("mutes/users/destroy.json", {"user_id": str(user_id)})
        if "error" in result:
            return result
        return {"status": "unmuted", "user_id": user_id}

    async def block(self, user_id: int) -> dict:
        result = await self._rest_post("blocks/create.json", {"user_id": str(user_id)})
        if "error" in result:
            return result
        return {"status": "blocked", "user_id": user_id}

    async def unblock(self, user_id: int) -> dict:
        result = await self._rest_post("blocks/destroy.json", {"user_id": str(user_id)})
        if "error" in result:
            return result
        return {"status": "unblocked", "user_id": user_id}

    # ── List Management ──

    async def create_list(self, name: str, description: str = "") -> dict:
        variables = {"name": name, "description": description, "isPrivate": False}
        data = await self._post("CreateList", variables)
        list_id = data.get("data", {}).get("list", {}).get("id_str") or data.get("data", {}).get("create_list", {}).get("list", {}).get("id_str")
        if list_id:
            return {"status": "created", "list_id": list_id, "name": name}
        if "error" in data:
            return data
        return {"status": "unknown", "response": data}

    async def update_list(self, list_id: int, name: str, description: str = "") -> dict:
        variables = {"listId": str(list_id), "name": name, "description": description}
        await self._post("UpdateList", variables)
        return {"status": "updated", "list_id": list_id}

    async def add_list_member(self, list_id: int, user_id: int) -> dict:
        variables = {"listId": str(list_id), "userId": str(user_id)}
        await self._post("ListAddMember", variables)
        return {"status": "added", "list_id": list_id, "user_id": user_id}

    async def remove_list_member(self, list_id: int, user_id: int) -> dict:
        variables = {"listId": str(list_id), "userId": str(user_id)}
        await self._post("ListRemoveMember", variables)
        return {"status": "removed", "list_id": list_id, "user_id": user_id}

    async def subscribe_list(self, list_id: int) -> dict:
        """Subscribe to a list."""
        variables = {"listId": str(list_id)}
        await self._post("ListSubscribe", variables)
        return {"status": "subscribed", "list_id": list_id}

    async def unsubscribe_list(self, list_id: int) -> dict:
        """Unsubscribe from a list."""
        variables = {"listId": str(list_id)}
        await self._post("ListUnsubscribe", variables)
        return {"status": "unsubscribed", "list_id": list_id}

    async def get_list_memberships(self, user_id: int, limit: int = 20) -> dict:
        """Get lists a user is a member of."""
        variables = {"userId": str(user_id), "count": limit}
        data = await self._get("ListMemberships", variables, features=TIMELINE_FEATURES, field_toggles=TIMELINE_FIELD_TOGGLES)
        if "error" in data:
            return data
        # Try to parse lists from timeline; may still fail due to X API bug
        lists = []
        try:
            instructions = self._find_instructions(data)
            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if "Cursor" in entry_type:
                        continue
                    item_content = content.get("itemContent", {})
                    list_result = item_content.get("list")
                    if not list_result:
                        list_result = item_content
                    if list_result and list_result.get("id_str"):
                        lists.append({
                            "list_id": list_result.get("id_str"),
                            "name": list_result.get("name"),
                            "description": list_result.get("description", ""),
                            "member_count": list_result.get("member_count", 0),
                            "follower_count": list_result.get("follower_count", 0),
                        })
        except Exception as e:
            logger.warning(f"Error parsing list memberships: {e}")
        if not lists:
            return {"error": "X API DecodeException — known server-side bug with ListMemberships. This is not a Spectre bug.", "lists": []}
        return {"lists": lists, "count": len(lists)}

    async def get_list_ownerships(self, user_id: int, limit: int = 20) -> dict:
        """Get lists owned by a user."""
        variables = {"userId": str(user_id), "count": limit, "isListMemberTargetUserId": str(user_id)}
        data = await self._get("ListOwnerships", variables, features=TIMELINE_FEATURES, field_toggles=TIMELINE_FIELD_TOGGLES)
        if "error" in data:
            return data
        lists = []
        try:
            instructions = self._find_instructions(data)
            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if "Cursor" in entry_type:
                        continue
                    item_content = content.get("itemContent", {})
                    list_result = item_content.get("list")
                    if not list_result:
                        list_result = item_content
                    if list_result and list_result.get("id_str"):
                        lists.append({
                            "list_id": list_result.get("id_str"),
                            "name": list_result.get("name"),
                            "description": list_result.get("description", ""),
                            "member_count": list_result.get("member_count", 0),
                            "follower_count": list_result.get("follower_count", 0),
                        })
        except Exception as e:
            logger.warning(f"Error parsing list ownerships: {e}")
        if not lists:
            return {"error": "X API DecodeException — known server-side bug with ListOwnerships. This is not a Spectre bug.", "lists": []}
        return {"lists": lists, "count": len(lists)}

    async def get_list_subscribers(self, list_id: int, limit: int = 20) -> dict:
        """Get subscribers of a list."""
        variables = {"listId": str(list_id), "count": limit}
        data = await self._get("ListSubscribers", variables)
        if "error" in data:
            return data
        return self._parse_any_user_list(data)

    # ── Community Operations ──

    async def join_community(self, community_id: int) -> dict:
        variables = {"communityId": str(community_id)}
        await self._post("JoinCommunity", variables)
        return {"status": "joined", "community_id": community_id}

    async def leave_community(self, community_id: int) -> dict:
        variables = {"communityId": str(community_id)}
        await self._post("LeaveCommunity", variables)
        return {"status": "left", "community_id": community_id}

    # ── DM Operations ──

    async def send_dm(self, user_id: int, text: str) -> dict:
        """Send a direct message to a user.

        Creates a new DM conversation or adds to an existing one.
        Note: The recipient must allow DMs from you (either they follow you,
        or they have "Allow message requests from everyone" enabled).
        """
        import uuid as _uuid
        variables = {
            "message": {
                "card": None,
                "media": None,
                "text": {"text": text},
                "tweet": None,
            },
            "requestId": str(_uuid.uuid4()),
            "target": {
                "participant_ids": [str(user_id)]
            },
        }
        data = await self._post("useSendMessageMutation", variables)
        if "error" in data:
            return data
        result = data.get("data", {}).get("create_dm", {})
        typename = result.get("__typename", "")
        if typename == "CreateDmSuccess":
            return {
                "status": "sent",
                "user_id": user_id,
                "text": text,
                "conversation_id": result.get("conversation_id"),
                "dm_id": result.get("dm_id"),
            }
        failure = result.get("dm_validation_failure_type", "Unknown error")
        return {"error": f"DM send failed: {failure}", "user_id": user_id}

    async def get_dm_inbox(self, limit: int = 20) -> dict:
        """Get DM inbox — recent conversations and messages.

        Returns the most recent DM conversations with message previews.
        Note: Message requests (from non-followed users) appear in the
        'untrusted' inbox timeline.
        """
        client, acc_info = await self._get_session()
        try:
            resp = await client.get("https://x.com/i/api/1.1/dm/inbox_initial_state.json")
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
            data = resp.json()
            inbox = data.get("inbox_initial_state", {})
            entries = inbox.get("entries", [])
            users = inbox.get("users", {})
            conversations = inbox.get("conversations", {})

            messages = []
            for entry in entries[:limit]:
                msg = entry.get("message", {})
                msg_data = msg.get("message_data", {})
                sender_id = msg_data.get("sender_id", "")
                sender = users.get(sender_id, {})
                messages.append({
                    "message_id": msg.get("id"),
                    "conversation_id": msg.get("conversation_id"),
                    "text": msg_data.get("text", ""),
                    "sender_id": sender_id,
                    "sender_username": sender.get("screen_name", ""),
                    "recipient_id": msg_data.get("recipient_id"),
                    "timestamp": msg_data.get("time"),
                })

            return {
                "messages": messages,
                "count": len(messages),
                "conversation_count": len(conversations),
            }
        finally:
            await client.aclose()

    async def get_dm_conversation(self, conversation_id: str, limit: int = 50) -> dict:
        """Get messages in a DM conversation.

        Args:
            conversation_id: The conversation ID (e.g. '17874544-2038267693875294208').
                             Get IDs from get_dm_inbox() results.
            limit: Max messages to return.
        """
        client, acc_info = await self._get_session()
        try:
            resp = await client.get(
                f"https://x.com/i/api/1.1/dm/conversation/{conversation_id}.json",
                params={"context": "FETCH_DM_CONVERSATION_HISTORY", "include_conversation_info": "true"},
            )
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
            data = resp.json()
            timeline = data.get("conversation_timeline", {})
            entries = timeline.get("entries", [])
            users = timeline.get("users", {})

            messages = []
            for entry in entries[:limit]:
                msg = entry.get("message", {})
                msg_data = msg.get("message_data", {})
                sender_id = msg_data.get("sender_id", "")
                sender = users.get(sender_id, {})
                messages.append({
                    "message_id": msg.get("id"),
                    "text": msg_data.get("text", ""),
                    "sender_id": sender_id,
                    "sender_username": sender.get("screen_name", ""),
                    "recipient_id": msg_data.get("recipient_id"),
                    "timestamp": msg_data.get("time"),
                })

            return {
                "conversation_id": conversation_id,
                "messages": messages,
                "count": len(messages),
            }
        finally:
            await client.aclose()

    # ── Scheduled Tweets ──

    async def schedule_tweet(self, text: str, execute_at: str, reply_to: int | None = None) -> dict:
        """Schedule a tweet for future posting.

        Args:
            text: Tweet content.
            execute_at: ISO 8601 datetime string (e.g. "2026-06-25T14:00:00Z").
            reply_to: Optional tweet ID to reply to.
        """
        from datetime import datetime, timezone
        # Convert ISO string to Unix timestamp (seconds)
        try:
            dt = datetime.fromisoformat(execute_at.replace("Z", "+00:00"))
            execute_at_ts = int(dt.timestamp())
        except ValueError:
            return {"error": f"Invalid datetime format: {execute_at}. Use ISO 8601 (e.g. 2026-06-25T14:00:00Z)"}
        variables = {
            "post_tweet_request": {
                "status": text,
                "media_ids": [],
            },
            "execute_at": execute_at_ts,
        }
        if reply_to:
            variables["post_tweet_request"]["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
        data = await self._post("CreateScheduledTweet", variables)
        if "error" in data:
            return data
        return {"status": "scheduled", "execute_at": execute_at, "execute_at_timestamp": execute_at_ts}

    async def get_scheduled_tweets(self) -> dict:
        """Get all scheduled tweets."""
        data = await self._post("FetchScheduledTweets", {"ascending": False})
        if "error" in data:
            return data
        scheduled = []
        try:
            items = data.get("data", {}).get("viewer", {}).get("scheduled_tweet_list", [])
            for item in items:
                info = item.get("scheduling_info", {})
                req = item.get("tweet_create_request", {})
                scheduled.append({
                    "scheduled_id": item.get("rest_id"),
                    "text": req.get("status", ""),
                    "execute_at": info.get("execute_at"),
                    "state": info.get("state", ""),
                    "media_ids": req.get("media_ids", []),
                })
        except Exception:
            return data
        return {"scheduled_tweets": scheduled, "count": len(scheduled)}

    async def delete_scheduled_tweet(self, tweet_id: str) -> dict:
        """Delete a scheduled tweet."""
        data = await self._post("DeleteScheduledTweet", {"scheduled_tweet_id": tweet_id})
        return {"status": "deleted", "scheduled_tweet_id": tweet_id}

    # ── Draft Tweets ──

    async def create_draft(self, text: str) -> dict:
        """Save a tweet draft."""
        variables = {"post_tweet_request": {"status": text, "media_ids": []}}
        data = await self._post("CreateDraftTweet", variables)
        if "error" in data:
            return data
        # Try multiple response paths
        draft_id = (
            data.get("data", {}).get("create_draft_tweet", {}).get("draft_tweet", {}).get("id")
            or data.get("data", {}).get("create_draft_tweet", {}).get("rest_id")
        )
        if not draft_id:
            # Deep search for rest_id
            def _find_rest_id(obj, depth=0):
                if depth > 5: return None
                if isinstance(obj, dict):
                    if "rest_id" in obj and obj.get("__typename") in ("DraftTweet", "Tweet", None):
                        return obj["rest_id"]
                    for v in obj.values():
                        r = _find_rest_id(v, depth + 1)
                        if r: return r
                elif isinstance(obj, list):
                    for item in obj:
                        r = _find_rest_id(item, depth + 1)
                        if r: return r
                return None
            draft_id = _find_rest_id(data)
        return {"status": "draft_created", "draft_id": draft_id}

    async def get_drafts(self) -> dict:
        """Get all draft tweets."""
        data = await self._post("FetchDraftTweets", {"ascending": False})
        if "error" in data:
            return data
        drafts = []
        try:
            items = data.get("data", {}).get("viewer", {}).get("draft_list", {}).get("response_data", [])
            for item in items:
                req = item.get("tweet_create_request", {})
                drafts.append({
                    "draft_id": item.get("rest_id"),
                    "text": req.get("status", ""),
                    "media_ids": req.get("media_ids", []),
                })
        except Exception:
            return data
        return {"drafts": drafts, "count": len(drafts)}

    async def delete_draft(self, tweet_id: str) -> dict:
        """Delete a draft tweet."""
        data = await self._post("DeleteDraftTweet", {"draft_tweet_id": tweet_id})
        return {"status": "deleted", "draft_id": tweet_id}

    async def edit_draft(self, draft_id: str, text: str) -> dict:
        """Edit an existing draft tweet."""
        variables = {"draft_tweet_id": draft_id, "post_tweet_request": {"status": text, "media_ids": []}}
        data = await self._post("EditDraftTweet", variables)
        if "error" in data:
            return data
        return {"status": "edited", "draft_id": draft_id}

    async def edit_scheduled_tweet(self, scheduled_id: str, text: str, execute_at: str) -> dict:
        """Edit an existing scheduled tweet."""
        from datetime import datetime
        dt = datetime.fromisoformat(execute_at.replace("Z", "+00:00"))
        execute_at_ts = int(dt.timestamp())
        variables = {"scheduled_tweet_id": scheduled_id, "post_tweet_request": {"status": text, "media_ids": []}, "execute_at": execute_at_ts}
        data = await self._post("EditScheduledTweet", variables)
        if "error" in data:
            return data
        return {"status": "edited", "scheduled_id": scheduled_id}

    # ── Bookmark Folders ──

    async def get_bookmark_folders(self) -> dict:
        """Get all bookmark folders."""
        data = await self._post("BookmarkFoldersSlice", {})
        if "error" in data:
            return data
        return self._parse_bookmark_folders(data)

    async def create_bookmark_folder(self, name: str) -> dict:
        """Create a bookmark folder."""
        variables = {"name": name}
        data = await self._post("createBookmarkFolder", variables)
        if "error" in data:
            return data
        # Try multiple response paths for folder_id
        folder_id = (
            data.get("data", {}).get("bookmark_folder", {}).get("id")
            or data.get("data", {}).get("create_bookmark_folder", {}).get("bookmark_folder", {}).get("id")
        )
        if not folder_id:
            # Deep search for id in bookmark_folder-like objects
            def _find_folder_id(obj, depth=0):
                if depth > 5: return None
                if isinstance(obj, dict):
                    if obj.get("__typename") == "BookmarkFolder" or ("id" in obj and "name" in obj):
                        return obj.get("id")
                    for v in obj.values():
                        r = _find_folder_id(v, depth + 1)
                        if r: return r
                elif isinstance(obj, list):
                    for item in obj:
                        r = _find_folder_id(item, depth + 1)
                        if r: return r
                return None
            folder_id = _find_folder_id(data)
        return {"status": "created", "folder_id": folder_id, "name": name}

    async def delete_bookmark_folder(self, folder_id: str) -> dict:
        """Delete a bookmark folder."""
        data = await self._post("DeleteBookmarkFolder", {"folder_id": folder_id})
        return {"status": "deleted", "folder_id": folder_id}

    async def edit_bookmark_folder(self, folder_id: str, name: str) -> dict:
        """Rename a bookmark folder."""
        variables = {"folder_id": folder_id, "name": name}
        data = await self._post("EditBookmarkFolder", variables)
        return {"status": "updated", "folder_id": folder_id, "name": name}

    async def add_tweet_to_folder(self, folder_id: str, tweet_id: int) -> dict:
        """Add a tweet to a bookmark folder."""
        variables = {"folder_id": folder_id, "tweet_id": str(tweet_id)}
        data = await self._post("bookmarkTweetToFolder", variables)
        return {"status": "added", "folder_id": folder_id, "tweet_id": tweet_id}

    async def remove_tweet_from_folder(self, folder_id: str, tweet_id: int) -> dict:
        """Remove a tweet from a bookmark folder."""
        variables = {"folder_id": folder_id, "tweet_id": str(tweet_id)}
        data = await self._post("RemoveTweetFromBookmarkFolder", variables)
        return {"status": "removed", "folder_id": folder_id, "tweet_id": tweet_id}

    async def clear_all_bookmarks(self) -> dict:
        """Delete all bookmarks."""
        data = await self._post("BookmarksAllDelete", {})
        if "error" in data:
            return data
        return {"status": "cleared"}

    async def search_bookmarks(self, query: str, limit: int = 20) -> dict:
        """Search bookmarks by text."""
        variables = {"rawQuery": query, "count": limit}
        data = await self._get("BookmarkSearchTimeline", variables)
        if "error" in data:
            return data
        tweets = self._parse_any_timeline(data)
        return {"tweets": tweets, "count": len(tweets)}

    # ── Lists (Delete) ──

    async def delete_list(self, list_id: int) -> dict:
        """Delete a list."""
        variables = {"listId": str(list_id)}
        data = await self._post("DeleteList", variables)
        return {"status": "deleted", "list_id": list_id}

    # ── Topics ──

    async def follow_topic(self, topic_id: str) -> dict:
        """Follow a topic."""
        variables = {"topicId": topic_id}
        await self._post("TopicFollow", variables)
        return {"status": "followed", "topic_id": topic_id}

    async def unfollow_topic(self, topic_id: str) -> dict:
        """Unfollow a topic."""
        variables = {"topicId": topic_id}
        await self._post("TopicUnfollow", variables)
        return {"status": "unfollowed", "topic_id": topic_id}

    # ── Community Notes (Birdwatch) ──

    async def create_community_note(self, tweet_id: int, text: str) -> dict:
        """Create a community note on a tweet."""
        variables = {
            "data_v1": {
                "summary": {"text": text},
                "trustworthy_sources": False,
                "misleading_tags": [],
            },
            "tweet_id": str(tweet_id),
        }
        birdwatch_features = {
            "responsive_web_birdwatch_media_notes_enabled": True,
            "responsive_web_birdwatch_url_notes_enabled": False,
            "responsive_web_grok_community_note_translation_is_enabled": True,
            "responsive_web_birdwatch_fast_notes_badge_enabled": False,
            "responsive_web_birdwatch_live_note_enabled": True,
            "responsive_web_birdwatch_note_internal_insights_enabled": False,
            "responsive_web_grok_community_note_auto_translation_is_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_profile_redirect_enabled": False,
            "rweb_tipjar_consumption_enabled": False,
            "verified_phone_label_enabled": False,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        }
        data = await self._post("BirdwatchCreateNote", variables, features=birdwatch_features)
        if "error" in data:
            return data
        return {"status": "created", "tweet_id": tweet_id}

    async def get_community_notes(self, tweet_id: int) -> dict:
        """Get community notes on a tweet."""
        variables = {"tweet_id": str(tweet_id)}
        data = await self._post("BirdwatchFetchNotes", variables)
        if "error" in data:
            return data
        notes = []
        try:
            # Parse community notes from response
            note_results = (
                data.get("data", {})
                .get("birdwatch_notes", {})
                .get("notes", [])
            )
            if not note_results:
                # Alternative paths
                note_results = data.get("data", {}).get("create_birdwatch_note", {}).get("notes", [])
            if not note_results:
                # Deep search for note-like objects
                def find_notes(obj, depth=0):
                    if depth > 8: return
                    if isinstance(obj, dict):
                        if "note_id" in obj or ("rest_id" in obj and "text" in obj):
                            notes.append({
                                "note_id": obj.get("note_id") or obj.get("rest_id"),
                                "text": obj.get("text", ""),
                                "created_at": obj.get("created_at"),
                                "rating": obj.get("rating", {}),
                            })
                            return
                        for v in obj.values():
                            find_notes(v, depth + 1)
                    elif isinstance(obj, list):
                        for item in obj:
                            find_notes(item, depth + 1)
                find_notes(data)
            else:
                for n in note_results:
                    notes.append({
                        "note_id": n.get("note_id") or n.get("rest_id"),
                        "text": n.get("text", ""),
                        "created_at": n.get("created_at"),
                        "rating": n.get("rating", {}),
                    })
        except Exception as e:
            logger.warning(f"Error parsing community notes: {e}")
        if notes:
            return {"notes": notes, "count": len(notes)}
        return {"notes": [], "count": 0}

    async def get_favoriters(self, tweet_id: int, limit: int = 20) -> dict:
        """Get users who liked a tweet."""
        variables = {"tweetId": str(tweet_id), "count": limit}
        data = await self._get("Favoriters", variables)
        if "error" in data:
            return data
        return self._parse_any_user_list(data)

    async def get_tweet_edit_history(self, tweet_id: int) -> dict:
        """Get edit history of a tweet."""
        variables = {"tweetId": str(tweet_id)}
        data = await self._get("TweetEditHistory", variables)
        if "error" in data:
            return data
        return self._parse_tweet_edit_history(data)

    async def get_similar_posts(self, tweet_id: int, limit: int = 20) -> dict:
        """Get similar/related posts to a tweet."""
        variables = {"tweet_id": str(tweet_id), "count": limit}
        data = await self._get("SimilarPosts", variables)
        if "error" in data:
            return data
        tweets = self._parse_any_timeline(data)
        return {"tweets": tweets, "count": len(tweets)}

    async def get_topic_info(self, topic_id: str) -> dict:
        """Get topic details by ID."""
        variables = {"topicId": topic_id}
        data = await self._get("TopicByRestId", variables)
        if "error" in data:
            return data
        topic = data.get("data", {}).get("topic", {})
        if not topic:
            return {"error": f"Topic {topic_id} not found"}
        return {
            "topic_id": topic.get("topic_id") or topic_id,
            "name": topic.get("name", ""),
            "following": topic.get("following", False),
            "not_interested": topic.get("not_interested", False),
        }

    async def get_notifications(self, limit: int = 20) -> dict:
        """Get notifications timeline."""
        variables = {"count": limit, "withQuickPromoteEligibilityTweetFields": True, "timeline_type": "All"}
        data = await self._get("NotificationsTimeline", variables)
        if "error" in data:
            return data
        return self._parse_notifications(data)

    async def get_user_tweets_and_replies(self, username: str, limit: int = 20) -> dict:
        """Get a user's tweets and replies."""
        from spectre.scraper import Scraper
        scraper = Scraper(db_path=self.db_path, proxy=self.proxy)
        # Use the scraper's GraphQL to get tweets and replies
        user = await scraper.get_user(username)
        if user is None:
            return {"error": f"User @{username} not found"}
        variables = {"userId": str(user.id), "count": limit, "includePromotedContent": False, "withVoice": True}
        data = await self._get("UserTweetsAndReplies", variables)
        if "error" in data:
            return data
        tweets = self._parse_any_timeline(data)
        return {"tweets": tweets, "count": len(tweets)}

    async def rate_community_note(self, note_id: str, rating: str) -> dict:
        """Rate a community note. rating: 'helpful' or 'not_helpful'."""
        variables = {
            "note_id": note_id,
            "rating": rating,
        }
        data = await self._post("BirdwatchCreateRating", variables)
        return {"status": "rated", "note_id": note_id, "rating": rating}

    # ── Account Settings & Profile ──

    async def get_account_settings(self) -> dict:
        """Get account settings via GraphQL (REST v1.1 was deprecated by X)."""
        try:
            accounts = await self.pool.get_all()
            acc = None
            for a in accounts:
                if a.active and not a.error_msg:
                    acc = a
                    break
            if not acc:
                return {"error": "No active accounts available."}
            from spectre.scraper import Scraper
            scraper = Scraper(db_path=self.db_path, proxy=self.proxy)
            result = await scraper.get_user(acc.username)
            if result is None:
                return {"error": f"User @{acc.username} not found"}
            # result is a UserProfile Pydantic model
            data = result.model_dump() if hasattr(result, "model_dump") else result
            return {
                "screen_name": data.get("username"),
                "name": data.get("display_name"),
                "description": data.get("bio"),
                "location": data.get("location"),
                "url": data.get("website"),
                "followers_count": data.get("followers"),
                "friends_count": data.get("following"),
                "statuses_count": data.get("tweets"),
                "note": "Account settings retrieved via GraphQL. REST v1.1 /account/settings.json was deprecated by X.",
            }
        except Exception as e:
            return {"error": str(e)}

    async def update_profile(self, name: str | None = None, bio: str | None = None, location: str | None = None, website: str | None = None) -> dict:
        """Update profile info via REST API v1.1."""
        from urllib.parse import urlencode
        params = {}
        if name is not None:
            params["name"] = name[:50]
        if bio is not None:
            params["description"] = bio[:160]
        if location is not None:
            params["location"] = location[:30]
        if website is not None:
            params["url"] = website
        if not params:
            return {"error": "No fields to update. Provide name, bio, location, or website."}
        client, acc_info = await self._get_session()
        try:
            # Set content-type for form-encoded data
            client.headers["content-type"] = "application/x-www-form-urlencoded"
            # Generate x-client-transaction-id (required for update_profile since late 2024)
            path = "/i/api/1.1/account/update_profile.json"
            try:
                from twscrape.queue_client import XClIdGenStore
                gen = await XClIdGenStore.get(acc_info["username"])
                txn_id = gen.calc("POST", path)
                client.headers["x-client-transaction-id"] = txn_id
            except Exception as e:
                logger.warning(f"Could not generate x-client-transaction-id: {e}")
            urls = [
                "https://api.x.com/1.1/account/update_profile.json",
                "https://x.com/i/api/1.1/account/update_profile.json",
                "https://api.twitter.com/1.1/account/update_profile.json",
            ]
            resp = None
            for url in urls:
                resp = await client.post(url, content=urlencode(params))
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "status": "updated",
                        "name": data.get("name"),
                        "bio": data.get("description"),
                        "location": data.get("location"),
                        "website": data.get("url"),
                    }
            return {"error": f"HTTP {resp.status_code if resp else 'no response'}", "detail": (resp.text[:300] if resp else ""), "tried": urls}
        finally:
            await client.aclose()

    async def update_profile_image(self, file_path: str) -> dict:
        """Update profile avatar image via REST API v1.1."""
        import os
        import mimetypes
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}
        content_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        client, acc_info = await self._get_session()
        try:
            # Pop content-type so httpx sets multipart/form-data with boundary
            original_ct = client.headers.pop("content-type", None)
            with open(file_path, "rb") as f:
                resp = await client.post(
                    "https://api.twitter.com/1.1/account/update_profile_image.json",
                    files={"image": (os.path.basename(file_path), f, content_type)},
                )
            if original_ct:
                client.headers["content-type"] = original_ct
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
            return {"status": "updated", "message": "Profile image updated successfully."}
        finally:
            await client.aclose()

    async def update_profile_banner(self, file_path: str) -> dict:
        """Update profile banner image via REST API v1.1."""
        import os
        import mimetypes
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}
        content_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        client, acc_info = await self._get_session()
        try:
            # Pop content-type so httpx sets multipart/form-data with boundary
            original_ct = client.headers.pop("content-type", None)
            with open(file_path, "rb") as f:
                resp = await client.post(
                    "https://api.twitter.com/1.1/account/update_profile_banner.json",
                    files={"banner": (os.path.basename(file_path), f, content_type)},
                )
            if original_ct:
                client.headers["content-type"] = original_ct
            if resp.status_code not in (200, 201):
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
            return {"status": "updated", "message": "Profile banner updated successfully."}
        finally:
            await client.aclose()

    async def delete_profile_banner(self) -> dict:
        """Remove profile banner via REST API."""
        client, acc_info = await self._get_session()
        try:
            resp = await client.post("https://api.twitter.com/1.1/account/remove_profile_banner.json")
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}
            return {"status": "deleted", "message": "Profile banner removed."}
        finally:
            await client.aclose()

    # ── Muted & Blocked Accounts ──

    async def get_muted_accounts(self, limit: int = 50) -> dict:
        """Get list of muted accounts via GraphQL."""
        variables = {"count": limit, "includePromotedContent": False}
        data = await self._get("MutedAccounts", variables)
        if "error" in data:
            return data
        return self._parse_user_list_from_timeline(data)

    async def get_blocked_accounts(self, limit: int = 50) -> dict:
        """Get list of blocked accounts via GraphQL."""
        variables = {"count": limit}
        data = await self._get("BlockedAccountsAll", variables)
        if "error" in data:
            return data
        return self._parse_user_list_from_timeline(data)

    def _parse_user_list_from_timeline(self, data: dict) -> dict:
        """Extract user objects from GraphQL timeline response (muted/blocked lists)."""
        users = []
        try:
            instructions = (
                data.get("data", {})
                .get("mutedUsers", {})
                .get("timeline", {})
                .get("timeline", {})
                .get("instructions", [])
            )
            if not instructions:
                # Try alternate path for blocked accounts
                instructions = (
                    data.get("data", {})
                    .get("blockedAccounts", {})
                    .get("timeline", {})
                    .get("timeline", {})
                    .get("instructions", [])
                )
            if not instructions:
                # Try yet another nested path
                instructions = (
                    data.get("data", {})
                    .get("user", {})
                    .get("result", {})
                    .get("timeline", {})
                    .get("timeline", {})
                    .get("instructions", [])
                )

            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    item_content = content.get("itemContent", content)
                    # Direct user result
                    user_result = None
                    if "user_results" in item_content:
                        user_result = item_content.get("user_results", {}).get("result", {})
                    elif "user" in item_content:
                        user_result = item_content.get("user", {}).get("result", {})
                    # Also check content.items for nested entries
                    if not user_result and "items" in content:
                        for item in content["items"]:
                            ic = item.get("item", {}).get("itemContent", {})
                            ur = ic.get("user_results", {}).get("result", {})
                            if ur and ur.get("rest_id"):
                                users.append(self._extract_user_info(ur))
                        continue

                    if user_result and user_result.get("rest_id"):
                        users.append(self._extract_user_info(user_result))
        except Exception as e:
            logger.warning(f"Error parsing user list from timeline: {e}")

        return {"users": users, "count": len(users)}

    @staticmethod
    def _extract_user_info(user_result: dict) -> dict:
        """Extract clean user info from a GraphQL user result object."""
        legacy = user_result.get("legacy", {})
        # Some GraphQL endpoints (e.g. BlueVerifiedFollowers) nest differently
        core_result = user_result.get("core", {}).get("user_results", {}).get("result", {})
        core_legacy = core_result.get("legacy", {}) if core_result else {}
        return {
            "user_id": user_result.get("rest_id"),
            "username": legacy.get("screen_name") or core_legacy.get("screen_name"),
            "name": legacy.get("name") or core_legacy.get("name"),
            "description": legacy.get("description") or core_legacy.get("description"),
            "followers_count": legacy.get("followers_count", 0) or core_legacy.get("followers_count", 0),
            "following_count": legacy.get("friends_count", 0) or core_legacy.get("friends_count", 0),
            "statuses_count": legacy.get("statuses_count", 0) or core_legacy.get("statuses_count", 0),
            "profile_image_url": legacy.get("profile_image_url_https") or core_legacy.get("profile_image_url_https"),
            "verified": legacy.get("verified", False) or core_legacy.get("verified", False),
            "blue_verified": user_result.get("is_blue_verified", False),
        }
    @staticmethod
    def _find_instructions(data):
        """Recursively find all 'instructions' arrays in a GraphQL response."""
        results = []
        if isinstance(data, dict):
            for key, val in data.items():
                if key == "instructions" and isinstance(val, list):
                    results.extend(val)
                else:
                    results.extend(Writer._find_instructions(val))
        elif isinstance(data, list):
            for item in data:
                results.extend(Writer._find_instructions(item))
        return results

    def _parse_any_timeline(self, data: dict) -> list:
        """Parse tweets from ANY GraphQL timeline response (generic)."""
        tweets = []
        try:
            instructions = self._find_instructions(data)
            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if "Cursor" in entry_type:
                        continue
                    item_content = content.get("itemContent", {})
                    tweet_result = (
                        item_content.get("tweet_results", {}).get("result", {})
                    )
                    if tweet_result and tweet_result.get("rest_id"):
                        tweets.append(self._extract_tweet_info(tweet_result))
                        continue
                    # Timeline module (conversation threads)
                    if "items" in content:
                        for item in content["items"]:
                            ic = item.get("item", {}).get("itemContent", {})
                            tr = ic.get("tweet_results", {}).get("result", {})
                            if tr and tr.get("rest_id"):
                                tweets.append(self._extract_tweet_info(tr))
        except Exception as e:
            logger.warning(f"Error parsing timeline tweets (generic): {e}")
        return tweets

    def _parse_any_user_list(self, data: dict) -> dict:
        """Parse user objects from ANY GraphQL response (generic)."""
        users = []
        seen = set()
        try:
            instructions = self._find_instructions(data)
            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if "Cursor" in entry_type:
                        continue
                    item_content = content.get("itemContent", content)
                    user_result = None
                    if "user_results" in item_content:
                        user_result = item_content.get("user_results", {}).get("result", {})
                    elif "user" in item_content:
                        user_result = item_content.get("user", {}).get("result", {})
                    # Check nested items
                    if not user_result and "items" in content:
                        for item in content["items"]:
                            ic = item.get("item", {}).get("itemContent", {})
                            ur = ic.get("user_results", {}).get("result", {})
                            if ur and ur.get("rest_id") and ur["rest_id"] not in seen:
                                seen.add(ur["rest_id"])
                                users.append(self._extract_user_info(ur))
                        continue
                    if user_result and user_result.get("rest_id"):
                        if user_result["rest_id"] not in seen:
                            seen.add(user_result["rest_id"])
                            users.append(self._extract_user_info(user_result))
        except Exception as e:
            logger.warning(f"Error parsing user list (generic): {e}")
        return {"users": users, "count": len(users)}

    def _parse_bookmark_folders(self, data: dict) -> dict:
        """Parse bookmark folders from GraphQL response."""
        folders = []
        try:
            # Try standard path
            collections = (
                data.get("data", {}).get("bookmark_collections_v2", {})
                .get("bookmark_collections", [])
            )
            if not collections:
                collections = data.get("data", {}).get("bookmark_folders", {}).get("folders", [])
            if collections:
                for c in collections:
                    folders.append({
                        "id": c.get("id") or c.get("bookmark_collection_id"),
                        "name": c.get("name"),
                        "visibility": c.get("visibility"),
                    })
            else:
                # Deep search for folder-like objects
                def find_folders(obj, depth=0):
                    if depth > 10 or len(folders) > 0:
                        return
                    if isinstance(obj, dict):
                        if "name" in obj and "id" in obj and ("visibility" in obj or "sort_index" in obj):
                            folders.append({
                                "id": obj.get("id"),
                                "name": obj.get("name"),
                                "visibility": obj.get("visibility", "ALL"),
                            })
                            return
                        for v in obj.values():
                            find_folders(v, depth + 1)
                    elif isinstance(obj, list):
                        for item in obj:
                            find_folders(item, depth + 1)
                find_folders(data)
        except Exception as e:
            logger.warning(f"Error parsing bookmark folders: {e}")
        return {"folders": folders, "count": len(folders)}

    def _parse_notifications(self, data: dict) -> dict:
        """Parse notifications from GraphQL response."""
        notifications = []
        try:
            instructions = self._find_instructions(data)
            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if "Cursor" in entry_type:
                        continue
                    item_content = content.get("itemContent", {})
                    if not item_content:
                        for module_item in content.get("items", []):
                            ic = module_item.get("item", {}).get("itemContent", {})
                            if ic:
                                item_content = ic
                                break

                    notif_type = item_content.get("notificationType", "")
                    tweet_results = item_content.get("tweet_results", {})
                    user_results = item_content.get("user_results", {})

                    notif = {
                        "type": notif_type,
                        "id": entry.get("entryId", ""),
                    }

                    tr = tweet_results.get("result", {})
                    if tr and tr.get("rest_id"):
                        notif["tweet"] = self._extract_tweet_info(tr)

                    ur = user_results.get("result", {})
                    if ur and ur.get("rest_id"):
                        notif["user"] = self._extract_user_info(ur)

                    # Multiple results (like/retweet groups)
                    if "items" in content:
                        for item in content["items"]:
                            ic = item.get("item", {}).get("itemContent", {})
                            tr2 = ic.get("tweet_results", {}).get("result", {})
                            if tr2 and tr2.get("rest_id"):
                                notif.setdefault("tweets", []).append(self._extract_tweet_info(tr2))
                            ur2 = ic.get("user_results", {}).get("result", {})
                            if ur2 and ur2.get("rest_id"):
                                notif.setdefault("users", []).append(self._extract_user_info(ur2))

                    if notif_type or notif.get("tweet") or notif.get("user") or notif.get("tweets") or notif.get("users"):
                        notifications.append(notif)
        except Exception as e:
            logger.warning(f"Error parsing notifications: {e}")
        return {"notifications": notifications, "count": len(notifications)}

    def _parse_tweet_edit_history(self, data: dict) -> dict:
        """Parse tweet edit history from GraphQL response."""
        edits = []
        try:
            tweet_result = (
                data.get("data", {})
                .get("tweet_result", {})
                .get("result", {})
            )
            if not tweet_result:
                tweet_result = (
                    data.get("data", {})
                    .get("tweetResults", {})
                    .get("result", {})
                )
            if tweet_result:
                edit_info = tweet_result.get("legacy", {}).get("edit_info", {})
                edit_ids = edit_info.get("edit_ids", [])
                initial = edit_info.get("initial_tweet_id")
                if initial:
                    edits.append({"tweet_id": initial, "is_original": True})
                for eid in edit_ids:
                    if eid != initial:
                        edits.append({"tweet_id": eid, "is_original": False})
        except Exception as e:
            logger.warning(f"Error parsing edit history: {e}")
        return {"edits": edits, "count": len(edits)}

    def _parse_dm_messages(self, data: dict) -> dict:
        """Parse DM search/message results from GraphQL response."""
        messages = []
        try:
            instructions = self._find_instructions(data)
            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if "Cursor" in entry_type:
                        continue
                    item_content = content.get("itemContent", content)
                    msg = {
                        "id": entry.get("entryId", ""),
                        "text": item_content.get("text", ""),
                        "sender_id": item_content.get("sender_id", ""),
                        "conversation_id": item_content.get("conversation_id", ""),
                        "timestamp": item_content.get("time", ""),
                    }
                    if msg["text"] or msg["sender_id"]:
                        messages.append(msg)
                    # Nested items
                    if "items" in content:
                        for item in content["items"]:
                            ic = item.get("item", {}).get("itemContent", {})
                            msg2 = {
                                "id": item.get("entryId", ""),
                                "text": ic.get("text", ""),
                                "sender_id": ic.get("sender_id", ""),
                                "conversation_id": ic.get("conversation_id", ""),
                                "timestamp": ic.get("time", ""),
                            }
                            if msg2["text"] or msg2["sender_id"]:
                                messages.append(msg2)
        except Exception as e:
            logger.warning(f"Error parsing DM messages: {e}")
        return {"messages": messages, "count": len(messages)}

    def _parse_dm_conversations(self, data: dict) -> dict:
        """Parse DM conversation list from GraphQL response."""
        conversations = []
        try:
            instructions = self._find_instructions(data)
            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if "Cursor" in entry_type:
                        continue
                    item_content = content.get("itemContent", content)
                    convo = {
                        "id": entry.get("entryId", ""),
                        "name": item_content.get("name", ""),
                        "participants": item_content.get("participants", []),
                    }
                    if convo["id"] and not convo["id"].startswith("cursor"):
                        conversations.append(convo)
        except Exception as e:
            logger.warning(f"Error parsing DM conversations: {e}")
        return {"conversations": conversations, "count": len(conversations)}


    # ── DM Operations (extended) ──

    async def search_dm(self, query: str, limit: int = 20) -> dict:
        """Search DMs by text query."""
        variables = {"query": query, "count": limit, "withAttachments": False, "withConversationQueryHighlights": False, "withMessageQueryHighlights": False}
        data = await self._get("DmAllSearchSlice", variables)
        if "error" in data:
            return data
        return self._parse_dm_messages(data)

    async def remove_follower(self, user_id: int) -> dict:
        """Remove a follower from your account."""
        variables = {"target_user_id": str(user_id)}
        await self._post("RemoveFollower", variables)
        return {"status": "removed_follower", "user_id": user_id}

    async def pin_reply(self, tweet_id: int) -> dict:
        """Pin a reply to a conversation."""
        variables = {"tweetId": str(tweet_id)}
        await self._post("PinReply", variables)
        return {"status": "pinned_reply", "tweet_id": tweet_id}

    async def unpin_reply(self, tweet_id: int) -> dict:
        """Unpin a reply from a conversation."""
        variables = {"tweetId": str(tweet_id)}
        await self._post("UnpinReply", variables)
        return {"status": "unpinned_reply", "tweet_id": tweet_id}

    async def get_followers_you_know(self, user_id: int, limit: int = 20) -> dict:
        """Get mutual followers (followers you know)."""
        variables = {"userId": str(user_id), "count": limit, "includePromotedContent": False}
        data = await self._get("FollowersYouKnow", variables, features=TIMELINE_FEATURES, field_toggles=TIMELINE_FIELD_TOGGLES)
        if "error" in data:
            return data
        return self._parse_any_user_list(data)

    async def dm_block_user(self, user_id: int) -> dict:
        """Block a user in DMs (prevents them from messaging you)."""
        variables = {"userId": str(user_id)}
        await self._post("dmBlockUser", variables)
        return {"status": "dm_blocked", "user_id": user_id}

    async def dm_unblock_user(self, user_id: int) -> dict:
        """Unblock a user in DMs."""
        variables = {"userId": str(user_id)}
        await self._post("dmUnblockUser", variables)
        return {"status": "dm_unblocked", "user_id": user_id}

    async def search_dm_groups(self, query: str, limit: int = 20) -> dict:
        """Search DMs in group conversations."""
        variables = {"query": query, "count": limit, "withAttachments": False, "withConversationQueryHighlights": False}
        data = await self._get("DmGroupSearchSlice", variables)
        if "error" in data:
            return data
        return self._parse_dm_conversations(data)

    async def get_dm_muted(self, limit: int = 20) -> dict:
        """Get muted DM conversations."""
        variables = {"count": limit}
        data = await self._get("DmMutedTimeline", variables)
        if "error" in data:
            return data
        return self._parse_dm_conversations(data)

    async def search_dm_people(self, query: str, limit: int = 20) -> dict:
        """Search for people in DMs."""
        variables = {"query": query, "count": limit, "withConversationQueryHighlights": False}
        data = await self._get("DmPeopleSearchSlice", variables)
        if "error" in data:
            return data
        return self._parse_any_user_list(data)

    # ── Pin / Unpin Tweet ──

    async def pin_tweet(self, tweet_id: int) -> dict:
        """Pin a tweet to your profile."""
        variables = {"tweet_id": str(tweet_id)}
        await self._post("PinTweet", variables)
        return {"status": "pinned", "tweet_id": tweet_id}

    async def unpin_tweet(self, tweet_id: int) -> dict:
        """Unpin a tweet from your profile."""
        variables = {"tweet_id": str(tweet_id)}
        await self._post("UnpinTweet", variables)
        return {"status": "unpinned", "tweet_id": tweet_id}

    # ── Profile Highlights ──

    async def create_highlight(self, tweet_ids: list[int]) -> dict:
        """Add tweets to your profile highlights."""
        results = []
        for tid in tweet_ids:
            variables = {"tweet_id": str(tid)}
            data = await self._post("CreateHighlight", variables)
            if "error" in data:
                results.append({"tweet_id": tid, "error": data["error"]})
            else:
                results.append({"tweet_id": tid, "status": "added"})
        return {"highlights": results, "count": len(results)}

    async def delete_highlight(self, highlight_id: str) -> dict:
        """Remove a highlight from your profile."""
        variables = {"highlightId": highlight_id}
        await self._post("DeleteHighlight", variables)
        return {"status": "deleted", "highlight_id": highlight_id}

    async def get_user_highlights(self, user_id: int, limit: int = 20) -> dict:
        """Get a user's profile highlights."""
        variables = {"userId": str(user_id), "count": limit, "includePromotedContent": False, "withVoice": False}
        data = await self._get("UserHighlightsTweets", variables)
        if "error" in data:
            return data
        tweets = self._parse_any_timeline(data)
        return {"tweets": tweets, "count": len(tweets)}

    # ── Verified Followers ──

    async def get_verified_followers(self, user_id: int, limit: int = 20) -> dict:
        """Get Blue-verified followers of a user."""
        variables = {"userId": str(user_id), "count": limit, "includePromotedContent": False}
        data = await self._get("BlueVerifiedFollowers", variables)
        if "error" in data:
            return data
        return self._parse_any_user_list(data)

    # ── User Likes ──

    async def get_user_likes(self, user_id: int, limit: int = 20) -> dict:
        """Get a user's liked tweets."""
        variables = {"userId": str(user_id), "count": limit, "includePromotedContent": False, "withQuickPromoteEligibilityTweetFields": True, "withVoice": True, "withV2Timeline": True}
        features = {
            "rweb_video_screen_enabled": False, "rweb_cashtags_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }
        data = await self._get("Likes", variables, features=features)
        if "error" in data:
            return data
        tweets = self._parse_any_timeline(data)
        return {"tweets": tweets, "count": len(tweets)}

    # ── Bookmark Folder Timeline ──

    async def get_bookmark_folder_timeline(self, folder_id: str, limit: int = 20) -> dict:
        """Get tweets in a bookmark folder."""
        variables = {"bookmark_collection_id": folder_id, "count": limit}
        data = await self._get("BookmarkFolderTimeline", variables)
        if "error" in data:
            return data
        tweets = self._parse_any_timeline(data)
        return {"tweets": tweets, "count": len(tweets)}

    # ── Home Timeline ──

    async def get_home_timeline(self, limit: int = 20) -> dict:
        """Get the authenticated user's home timeline via GraphQL."""
        variables = {
            "count": limit,
            "includePromotedContent": True,
            "latestControlAvailable": True,
            "requestContext": "launch",
            "withCommunity": True,
        }
        features = {
            "rweb_video_screen_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }
        data = await self._get("HomeTimeline", variables, features=features)
        if "error" in data:
            return data
        # Parse tweets from timeline entries
        tweets = self._parse_timeline_tweets(data)
        return {"tweets": tweets, "count": len(tweets)}

    def _parse_timeline_tweets(self, data: dict) -> list[dict]:
        """Parse tweets from a GraphQL timeline response."""
        tweets = []
        try:
            instructions = (
                data.get("data", {})
                .get("home", {})
                .get("home_timeline_urt", {})
                .get("instructions", [])
            )
            if not instructions:
                instructions = (
                    data.get("data", {})
                    .get("timeline", {})
                    .get("timeline", {})
                    .get("instructions", [])
                )

            for instruction in instructions:
                entries = instruction.get("entries", [])
                if not entries:
                    entries = instruction.get("moduleItems", [])
                for entry in entries:
                    content = entry.get("content", {})
                    # Direct tweet
                    item_content = content.get("itemContent", {})
                    tweet_result = (
                        item_content.get("tweet_results", {}).get("result", {})
                    )
                    if tweet_result and tweet_result.get("rest_id"):
                        tweets.append(self._extract_tweet_info(tweet_result))
                        continue
                    # Timeline module (e.g., conversation threads)
                    if "items" in content:
                        for item in content["items"]:
                            ic = item.get("item", {}).get("itemContent", {})
                            tr = ic.get("tweet_results", {}).get("result", {})
                            if tr and tr.get("rest_id"):
                                tweets.append(self._extract_tweet_info(tr))
        except Exception as e:
            logger.warning(f"Error parsing timeline tweets: {e}")

        return tweets

    @staticmethod
    def _extract_tweet_info(tweet_result: dict) -> dict:
        """Extract clean tweet info from a GraphQL tweet result object."""
        legacy = tweet_result.get("legacy", {})
        user_legacy = (
            tweet_result.get("core", {})
            .get("user_results", {})
            .get("result", {})
            .get("legacy", {})
        )
        # Fallback: some responses (notifications) nest user differently
        if not user_legacy.get("screen_name"):
            alt_result = tweet_result.get("core", {}).get("user_results", {}).get("result", {})
            if alt_result:
                alt_core = alt_result.get("core", {}).get("user_results", {}).get("result", {})
                if alt_core:
                    user_legacy = alt_core.get("legacy", {}) or user_legacy
        return {
            "tweet_id": tweet_result.get("rest_id"),
            "text": legacy.get("full_text", ""),
            "author_username": user_legacy.get("screen_name"),
            "author_name": user_legacy.get("name"),
            "created_at": legacy.get("created_at"),
            "retweet_count": legacy.get("retweet_count", 0),
            "like_count": legacy.get("favorite_count", 0),
            "reply_count": legacy.get("reply_count", 0),
            "quote_count": legacy.get("quote_count", 0),
            "view_count": tweet_result.get("views", {}).get("count"),
            "lang": legacy.get("lang"),
            "url": f"https://x.com/i/status/{tweet_result.get('rest_id')}",
        }

    # ── Trends ──

    async def get_trends(self, category: str = "trending", limit: int = 20) -> dict:
        """Get trending topics via REST API.

        Args:
            category: 'trending', 'news', 'sport', or 'entertainment'.
            limit: Max trends to return.
        """
        # Map category to WOEID (Where On Earth ID) — 1 = worldwide
        url = "https://api.twitter.com/1.1/trends/place.json"
        client, acc_info = await self._get_session()
        try:
            resp = await client.get(url, params={"id": "1"})
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("x-rate-limit-reset", 0))
                return _rate_limit_error("trends", retry_after)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:300]}

            data = resp.json()
            if not data or not isinstance(data, list):
                return {"trends": [], "count": 0}

            trends_data = data[0].get("trends", [])
            trends = []
            for t in trends_data[:limit]:
                trends.append({
                    "name": t.get("name"),
                    "tweet_count": t.get("tweet_volume"),
                    "url": t.get("url"),
                    "category": category,
                })
            return {"trends": trends, "count": len(trends)}
        finally:
            await client.aclose()

    # ── Media Upload ──

    async def upload_media(self, file_path: str) -> dict:
        """Upload media (image/video/GIF) for use in tweets.

        Uses cookie-based auth with curl_cffi for TLS fingerprinting.
        3-phase upload: INIT → APPEND (4MB chunks) → FINALIZE.
        For videos, polls processing status until complete.
        """
        import mimetypes
        import os

        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        file_size = os.path.getsize(file_path)

        # Use upload2.json for videos, upload.json for images
        is_video = content_type.startswith("video/")
        upload_url = "https://upload.twitter.com/i/media/upload2.json" if is_video else "https://upload.twitter.com/i/media/upload.json"

        # Get authenticated session info
        accounts = await self.pool.get_all()
        acc = None
        for a in accounts:
            if a.active and not a.error_msg:
                acc = a
                break
        if not acc:
            return {"error": "No active accounts available."}

        cookies = acc.cookies
        if isinstance(cookies, str):
            cookies = json.loads(cookies)

        cookie_string = f"auth_token={cookies.get('auth_token', '')}; ct0={cookies.get('ct0', '')}"
        csrf = cookies.get("ct0", "")

        import curl_cffi
        import curl_cffi.requests as curl_requests

        base_headers = {
            "authorization": f"Bearer {BEARER_TOKEN}",
            "cookie": cookie_string,
            "x-csrf-token": csrf,
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "origin": "https://x.com",
            "referer": "https://x.com/compose/post",
            "accept": "*/*",
        }

        try:
            session = curl_requests.AsyncSession(impersonate="chrome")

            # ── Phase 1: INIT ──
            init_data = {
                "command": "INIT",
                "total_bytes": str(file_size),
                "media_type": content_type,
            }
            # For videos, add media_category for proper processing
            if is_video:
                init_data["media_category"] = "tweet_video"

            init_resp = await session.post(
                upload_url,
                data=init_data,
                headers={**base_headers, "content-type": "application/x-www-form-urlencoded"},
            )
            if init_resp.status_code not in (200, 202):
                await session.close()
                return {"error": f"INIT failed (HTTP {init_resp.status_code})", "detail": init_resp.text[:300]}

            media_id = init_resp.json().get("media_id_string")
            if not media_id:
                await session.close()
                return {"error": "INIT response missing media_id_string", "raw": init_resp.text[:300]}

            # ── Phase 2: APPEND (chunked upload) ──
            CHUNK_SIZE = 4 * 1024 * 1024  # 4MB chunks
            with open(file_path, "rb") as f:
                segment = 0
                while chunk := f.read(CHUNK_SIZE):
                    append_data = {
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(segment),
                    }
                    mp = curl_cffi.CurlMime()
                    mp.addpart(
                        name="media",
                        content_type=content_type,
                        filename=os.path.basename(file_path),
                        data=chunk,
                    )
                    append_resp = await session.post(
                        upload_url,
                        data=append_data,
                        multipart=mp,
                        headers=base_headers,
                    )
                    mp.close()
                    if append_resp.status_code not in (200, 204):
                        await session.close()
                        return {"error": f"APPEND segment {segment} failed (HTTP {append_resp.status_code})", "detail": append_resp.text[:300]}
                    segment += 1

            # ── Phase 3: FINALIZE ──
            finalize_data = {
                "command": "FINALIZE",
                "media_id": media_id,
            }
            finalize_resp = await session.post(
                upload_url,
                data=finalize_data,
                headers={**base_headers, "content-type": "application/x-www-form-urlencoded"},
            )
            if finalize_resp.status_code not in (200, 201, 202):
                await session.close()
                return {"error": f"FINALIZE failed (HTTP {finalize_resp.status_code})", "detail": finalize_resp.text[:300]}

            finalize_result = finalize_resp.json()
            processing_info = finalize_result.get("processing_info")

            # ── Phase 4: Poll for video processing (if applicable) ──
            if processing_info and processing_info.get("state") != "succeeded":
                import asyncio
                for _ in range(60):  # max 60 polls (5 min for large videos)
                    await asyncio.sleep(processing_info.get("check_after_secs", 5))
                    status_resp = await session.get(
                        f"{upload_url}?command=STATUS&media_id={media_id}",
                        headers=base_headers,
                    )
                    status = status_resp.json().get("processing_info", {})
                    if status.get("state") == "succeeded":
                        break
                    if status.get("state") == "failed":
                        await session.close()
                        return {"error": "Media processing failed", "detail": status}
                    processing_info = status

            await session.close()

            return {
                "status": "uploaded",
                "media_id": media_id,
                "media_id_string": media_id,
                "media_type": "video" if is_video else "image",
                "usage": f"Pass media_ids=[{media_id}] to post_tweet()",
            }
        except Exception as e:
            return {"error": str(e)}
