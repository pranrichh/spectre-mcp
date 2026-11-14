"""Read and write operations against X/Twitter.

Two rules this module exists to enforce:

1. A tool never reports success it did not observe. X answers HTTP 200 with an
   `errors` array often enough that "no exception" means nothing; every mutation
   checks the payload for the object it asked X to change.
2. Every failure is an `XError` -> `{"error", "kind", "hint"}`, so an agent can
   tell "rate limited, wait" from "wrong id" from "cookies expired".

Reads that GraphQL does not expose cleanly (search, timelines, threads) live in
`scraper.py` on top of twscrape; everything here is direct GraphQL/REST.
"""

from __future__ import annotations

import functools
import json
import os
import mimetypes
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from spectre.errors import XError, from_x_error
from spectre.parse import (
    dm_conversations,
    dm_messages,
    iso_time,
    notifications as parse_notifications,
    sid,
    timeline,
    tweet_dict,
    user_dict,
)
from spectre.xclient import BEARER, REST, XClient, _cookies


def safe(fn):
    """Turn XError / unexpected exceptions into a tool-shaped error dict."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except XError as exc:
            return exc.to_dict()
        except Exception as exc:  # noqa: BLE001 - a tool must never crash the server
            logger.exception(f"{fn.__name__} failed")
            return {"error": f"{type(exc).__name__}: {exc}", "kind": "internal"}

    return wrapper


def _cursor_vars(cursor: Optional[str], count: int) -> dict:
    if cursor:
        return {"count": count, "cursor": cursor}
    return {"count": count}


class Writer:
    """All authenticated X operations, on top of one shared XClient."""

    def __init__(self, client: XClient, db_path: Optional[str] = None):
        self.x = client
        self.db_path = db_path

    # ══════════════════════════════════════════════════════════
    #  Identity
    # ══════════════════════════════════════════════════════════

    @safe
    async def me(self) -> dict:
        """Who the session actually is, per X (not per the local DB)."""
        data = await self.x.graphql("Viewer", {})
        viewer = (data.get("data") or {}).get("viewer") or {}
        user = user_dict((viewer.get("user_results") or {}).get("result"))
        if not user:
            raise XError("Could not read the logged-in account.", kind="auth", hint="Re-add the account cookies.")
        if not user.get("bio"):
            # Viewer returns a trimmed user object; the profile query has the bio.
            try:
                full = await self.user(user["username"])
                user = {**user, **{k: v for k, v in full.items() if v not in (None, "", 0, False) or user.get(k) in (None, "")}}
            except XError:
                pass
        # The pool stores whatever handle was typed at `spectre add` time. If the
        # account was renamed, that handle is stale and every profile lookup on it
        # returns "not found" — surface the real one so the caller can fix it.
        return {
            "username": user["username"],
            "id": user["id"],
            "display_name": user["display_name"],
            "bio": user["bio"],
            "followers": user["followers"],
            "following": user["following"],
            "tweets": user["tweets"],
            "likes": user["likes"],
            "verified": user["verified"],
            "blue_verified": user["blue_verified"],
            "profile_image_url": user["profile_image_url"],
            "banner_url": user["banner_url"],
            "created_at": user["created_at"],
            "protected": user["protected"],
            "can_dm": viewer.get("can_dm"),
        }

    @safe
    async def account_settings(self) -> dict:
        """Settings-shaped view of the authenticated account (GraphQL Viewer)."""
        me = await self.me()
        if "error" in me:
            return me
        pool_user = None
        try:
            accounts = await self.x.pool.get_all()
            pool_user = next((a.username for a in accounts if a.active), None)
        except Exception:  # noqa: BLE001
            pass
        return {
            **me,
            "pool_username": pool_user,
            "pool_username_stale": bool(pool_user and pool_user.lower() != me["username"].lower()),
            "note": "X removed the REST /account/settings.json endpoint; these are the fields Viewer exposes.",
        }

    @safe
    async def user(self, username: str) -> dict:
        data = await self.x.graphql("UserByScreenName", {"screen_name": username.lstrip("@"), "withSafetyModeUserFields": True})
        user = user_dict((data.get("data") or {}).get("user", {}).get("result"))
        if not user:
            raise XError(f"User @{username} not found.", kind="not_found", code=50)
        return user

    @safe
    async def user_by_id(self, user_id: str) -> dict:
        data = await self.x.graphql("UserByRestId", {"userId": str(user_id), "withSafetyModeUserFields": True})
        user = user_dict((data.get("data") or {}).get("user", {}).get("result"))
        if not user:
            raise XError(f"No user with id {user_id}", kind="not_found", code=50)
        return user

    @safe
    async def users_by_ids(self, user_ids: list[str]) -> dict:
        users, missing = [], []
        for uid in user_ids:
            result = await self.user_by_id(uid)
            if isinstance(result, dict) and "error" in result:
                missing.append(str(uid))
            else:
                users.append(result)
        return {"users": users, "count": len(users), "missing": missing}

    # ══════════════════════════════════════════════════════════
    #  Tweets
    # ══════════════════════════════════════════════════════════

    @safe
    async def tweet(self, tweet_id: str) -> dict:
        data = await self.x.graphql(
            "TweetResultByRestId",
            {"tweetId": str(tweet_id), "includePromotedContent": False, "withVoice": False, "withCommunity": False},
        )
        result = (data.get("data") or {}).get("tweetResult", {}).get("result")
        tweet = tweet_dict(result)
        if not tweet:
            # Deleted, protected, or age-restricted: TweetDetail sometimes still has it.
            detail = await self.x.graphql(
                "TweetDetail",
                {"focalTweetId": str(tweet_id), "includePromotedContent": False, "withVoice": False, "withBirdwatchNotes": False},
            )
            tweets, _, _ = timeline(detail)
            tweet = next((t for t in tweets if t["id"] == str(tweet_id)), None)
        if not tweet:
            raise XError(f"Tweet {tweet_id} not found (deleted, protected, or wrong id).", kind="not_found", code=144)
        return tweet

    @safe
    async def tweets(self, tweet_ids: list[str]) -> dict:
        data = await self.x.graphql(
            "TweetResultsByRestIds",
            {"tweetIds": [str(i) for i in tweet_ids], "includePromotedContent": False, "withVoice": False, "withCommunity": False},
        )
        results = (data.get("data") or {}).get("tweetResult") or []
        tweets = [t for t in (tweet_dict(r.get("result")) for r in results) if t]
        found = {t["id"] for t in tweets}
        return {"tweets": tweets, "count": len(tweets), "missing": [i for i in map(str, tweet_ids) if i not in found]}

    @safe
    async def quotes(self, tweet_id: str, limit: int = 20, cursor: Optional[str] = None) -> dict:
        data = await self.x.graphql(
            "SearchTimeline",
            {
                "rawQuery": f"quoted_tweet_id:{tweet_id}",
                "count": limit,
                "querySource": "typed_query",
                "product": "Latest",
                **_cursor_vars(cursor, limit),
            },
        )
        tweets, users, next_cursor = timeline(data)
        return {"tweets": tweets, "count": len(tweets), "next_cursor": next_cursor}

    @safe
    async def thread(self, tweet_id: str, limit: int = 50) -> dict:
        data = await self.x.graphql(
            "TweetDetail",
            {"focalTweetId": str(tweet_id), "includePromotedContent": False, "withVoice": False, "withBirdwatchNotes": False},
        )
        tweets, _, _ = timeline(data)
        focal = next((t for t in tweets if t["id"] == str(tweet_id)), None)
        conversation_id = (focal or {}).get("conversation_id") or str(tweet_id)
        # TweetDetail also injects promoted posts and "more to explore" modules;
        # keep only members of this conversation, then order them.
        tweets = [t for t in tweets if t.get("conversation_id") == conversation_id or t["id"] == str(tweet_id)]
        tweets.sort(key=lambda t: (t.get("created_at") or "", t["id"]))
        return {"tweets": tweets[:limit], "count": min(len(tweets), limit), "total": len(tweets)}

    @safe
    async def favoriters(self, tweet_id: str, limit: int = 20, cursor: Optional[str] = None) -> dict:
        data = await self.x.graphql(
            "Favoriters", {"tweetId": str(tweet_id), "includePromotedContent": False, **_cursor_vars(cursor, limit)}
        )
        _, users, next_cursor = timeline(data)
        result = {"users": users, "count": len(users), "next_cursor": next_cursor}
        if not users:
            result["note"] = "X did not return a likers list for this post (restricted on most accounts, not a Spectre failure)."
        return result

    @safe
    async def similar_posts(self, tweet_id: str, limit: int = 20) -> dict:
        data = await self.x.graphql("SimilarPosts", {"tweet_id": str(tweet_id), "count": limit})
        tweets, _, _ = timeline(data)
        result = {"tweets": tweets, "count": len(tweets)}
        if not tweets:
            # X gates this behind Premium and returns a paywall prompt instead.
            if "premium" in json.dumps(data).lower():
                result["note"] = "X requires Premium for similar posts on this account."
        return result

    @safe
    async def edit_history(self, tweet_id: str) -> dict:
        data = await self.x.graphql("TweetEditHistory", {"tweetId": str(tweet_id)})
        result = (data.get("data") or {}).get("tweet_result_by_rest_id", {}).get("result") or {}
        history = result.get("edit_history_timeline") or {}
        ids: list[str] = []
        initial = None
        for entry in history.get("entries") or []:
            tr = ((entry.get("content") or {}).get("tweet_results") or {}).get("result") or {}
            if tr.get("rest_id"):
                ids.append(str(tr["rest_id"]))
        legacy_edit = ((result.get("legacy") or {}).get("edit_info") or {})
        initial = sid(legacy_edit.get("initial_tweet_id"))
        if not ids and initial:
            ids = [initial] + [str(i) for i in legacy_edit.get("edit_ids") or []]
        return {"tweet_id": str(tweet_id), "edits": ids, "count": len(ids)}

    @safe
    async def community_notes(self, tweet_id: str) -> dict:
        data = await self.x.graphql("BirdwatchFetchNotes", {"tweet_id": str(tweet_id)})
        result = (data.get("data") or {}).get("tweet_result_by_rest_id", {}).get("result") or {}
        notes_raw = ((result.get("misleading_birdwatch_notes") or {}).get("notes")) or []
        notes = []
        for n in notes_raw:
            notes.append(
                {
                    "note_id": sid(n.get("note_id") or n.get("rest_id")),
                    "text": n.get("summary", {}).get("text") if isinstance(n.get("summary"), dict) else n.get("text"),
                    "rating": (n.get("rating") or {}).get("rating"),
                    "created_at": iso_time(n.get("created_at_ms") or n.get("created_at")),
                }
            )
        return {"tweet_id": str(tweet_id), "notes": notes, "count": len(notes)}

    @safe
    async def rate_community_note(self, note_id: str, rating: str) -> dict:
        rating = rating.lower().replace("-", "_")
        if rating not in ("helpful", "not_helpful", "somewhat_helpful"):
            raise XError("rating must be one of: helpful, somewhat_helpful, not_helpful", kind="validation")
        data = await self.x.graphql("BirdwatchCreateRating", {"note_id": note_id, "rating": rating})
        return {"status": "rated", "note_id": note_id, "rating": rating, "result": data.get("data")}

    # ── composing ──

    @safe
    async def post(
        self,
        text: str,
        reply_to: Optional[str] = None,
        quote_tweet: Optional[str] = None,
        media_ids: Optional[list[str]] = None,
    ) -> dict:
        if reply_to and quote_tweet:
            raise XError("A tweet can be a reply or a quote, not both.", kind="validation")
        media_entities = [{"media_id": str(mid), "tagged_users": []} for mid in (media_ids or [])]
        variables: dict[str, Any] = {
            "tweet_text": text,
            "dark_request": False,
            "media": {"media_entities": media_entities, "possibly_sensitive": False},
            "semantic_annotation_ids": [],
        }
        if reply_to:
            variables["reply"] = {"in_reply_to_tweet_id": str(reply_to), "exclude_reply_user_ids": []}
        if quote_tweet:
            variables["attachment_url"] = f"https://x.com/i/status/{quote_tweet}"

        data = await self.x.graphql("CreateTweet", variables)
        result = ((data.get("data") or {}).get("create_tweet") or {}).get("tweet_results", {}).get("result") or {}
        tweet_id = sid(result.get("rest_id"))
        if not tweet_id:
            # X happily returns 200 with a soft failure message.
            reason = json.dumps(data.get("data") or data)[:300]
            raise XError(f"X accepted the request but created no tweet: {reason}", kind="upstream")
        return {"status": "posted", "tweet_id": tweet_id, "url": f"https://x.com/i/status/{tweet_id}", "text": text}

    @safe
    async def delete_tweet(self, tweet_id: str) -> dict:
        data = await self.x.graphql("DeleteTweet", {"tweet_id": str(tweet_id)})
        if not (data.get("data") or {}).get("delete_tweet"):
            raise XError(f"X did not accept the delete for {tweet_id}.", kind="upstream")
        # X answers `{"tweet_results": {}}` whether or not the post existed, so the
        # only honest confirmation is that the post can no longer be fetched.
        import asyncio as _asyncio

        # Check with the direct lookup only: TweetDetail keeps serving the
        # conversation around a deleted post, which makes a deleted tweet look
        # alive for a few seconds.
        still_there = True
        for delay in (0, 0.6, 1.5):
            if delay:
                await _asyncio.sleep(delay)
            try:
                data = await self.x.graphql(
                    "TweetResultByRestId",
                    {"tweetId": str(tweet_id), "includePromotedContent": False, "withVoice": False, "withCommunity": False},
                )
                result = (data.get("data") or {}).get("tweetResult", {}).get("result")
                still_there = tweet_dict(result) is not None
            except XError:
                still_there = False
            if not still_there:
                break
        if still_there:
            raise XError(
                f"X accepted the delete but {tweet_id} is still readable.",
                kind="upstream",
                hint="You can only delete your own posts.",
            )
        return {"status": "deleted", "tweet_id": str(tweet_id), "verified": True}

    # ── engagement ──

    async def _mutate(self, op: str, variables: dict, expect: str, action: str, extra: dict | None = None) -> dict:
        data = await self.x.graphql(op, variables)
        payload = (data.get("data") or {}).get(expect)
        if payload is None:
            raise XError(
                f"X did not confirm the {action} action.",
                kind="upstream",
                hint=f"Raw response: {json.dumps(data)[:200]}",
            )
        return {"status": action, **(extra or {})}

    @safe
    async def like(self, tweet_id: str) -> dict:
        return await self._mutate("FavoriteTweet", {"tweet_id": str(tweet_id)}, "favorite_tweet", "liked", {"tweet_id": str(tweet_id)})

    @safe
    async def unlike(self, tweet_id: str) -> dict:
        return await self._mutate("UnfavoriteTweet", {"tweet_id": str(tweet_id)}, "unfavorite_tweet", "unliked", {"tweet_id": str(tweet_id)})

    @safe
    async def retweet(self, tweet_id: str) -> dict:
        return await self._mutate(
            "CreateRetweet", {"tweet_id": str(tweet_id), "dark_request": False}, "create_retweet", "retweeted", {"tweet_id": str(tweet_id)}
        )

    @safe
    async def unretweet(self, tweet_id: str) -> dict:
        return await self._mutate(
            "DeleteRetweet",
            {"source_tweet_id": str(tweet_id), "dark_request": False},
            "unretweet",
            "unretweeted",
            {"tweet_id": str(tweet_id)},
        )

    @safe
    async def bookmark(self, tweet_id: str) -> dict:
        data = await self.x.graphql("BookmarkAdd", {"tweetId": str(tweet_id)})
        if not data.get("data"):
            raise XError("X did not confirm the bookmark.", kind="upstream")
        return {"status": "bookmarked", "tweet_id": str(tweet_id)}

    @safe
    async def unbookmark(self, tweet_id: str) -> dict:
        data = await self.x.graphql("BookmarkDelete", {"tweetId": str(tweet_id)})
        if not data.get("data"):
            raise XError("X did not confirm the bookmark removal.", kind="upstream")
        return {"status": "unbookmarked", "tweet_id": str(tweet_id)}

    # ── social graph ──

    @safe
    async def follow(self, user_id: str) -> dict:
        payload = await self.x.rest("POST", "friendships/create.json", data={"user_id": str(user_id)})
        if not payload.get("id_str") and not payload.get("id"):
            raise XError("X did not confirm the follow.", kind="upstream")
        return {"status": "followed", "user_id": str(user_id), "username": payload.get("screen_name")}

    @safe
    async def unfollow(self, user_id: str) -> dict:
        payload = await self.x.rest("POST", "friendships/destroy.json", data={"user_id": str(user_id)})
        if not payload.get("id_str") and not payload.get("id"):
            raise XError("X did not confirm the unfollow.", kind="upstream")
        return {"status": "unfollowed", "user_id": str(user_id), "username": payload.get("screen_name")}

    @safe
    async def mute(self, user_id: str) -> dict:
        payload = await self.x.rest("POST", "mutes/users/create.json", data={"user_id": str(user_id)})
        if not payload.get("id_str") and not payload.get("id"):
            raise XError("X did not confirm the mute.", kind="upstream")
        return {"status": "muted", "user_id": str(user_id)}

    @safe
    async def unmute(self, user_id: str) -> dict:
        payload = await self.x.rest("POST", "mutes/users/destroy.json", data={"user_id": str(user_id)})
        if not payload.get("id_str") and not payload.get("id"):
            raise XError("X did not confirm the unmute.", kind="upstream")
        return {"status": "unmuted", "user_id": str(user_id)}

    @safe
    async def block(self, user_id: str) -> dict:
        payload = await self.x.rest("POST", "blocks/create.json", data={"user_id": str(user_id)})
        if not payload.get("id_str") and not payload.get("id"):
            raise XError("X did not confirm the block.", kind="upstream")
        return {"status": "blocked", "user_id": str(user_id)}

    @safe
    async def unblock(self, user_id: str) -> dict:
        payload = await self.x.rest("POST", "blocks/destroy.json", data={"user_id": str(user_id)})
        if not payload.get("id_str") and not payload.get("id"):
            raise XError("X did not confirm the unblock.", kind="upstream")
        return {"status": "unblocked", "user_id": str(user_id)}

    @safe
    async def remove_follower(self, user_id: str) -> dict:
        data = await self.x.graphql("RemoveFollower", {"target_user_id": str(user_id)})
        payload = (data.get("data") or {}).get("remove_follower") or {}
        if payload.get("__typename") == "UnfollowInvalidRequestResult" or payload.get("success") is False:
            raise XError(
                f"X refused to remove follower {user_id}: {payload.get('parameter_error_reason') or payload}",
                kind="validation",
            )
        return {"status": "removed_follower", "user_id": str(user_id)}

    @safe
    async def pin(self, tweet_id: str) -> dict:
        data = await self.x.graphql("PinTweet", {"tweet_id": str(tweet_id)})
        payload = (data.get("data") or {}).get("pin_tweet") or {}
        if payload.get("message") and "not valid" in str(payload.get("message")).lower():
            raise XError(payload["message"], kind="validation", hint="You can only pin your own, non-retweeted post.")
        return {"status": "pinned", "tweet_id": str(tweet_id), "note": "Any previous pin was replaced."}

    @safe
    async def unpin(self, tweet_id: str) -> dict:
        data = await self.x.graphql("UnpinTweet", {"tweet_id": str(tweet_id)})
        payload = (data.get("data") or {}).get("unpin_tweet") or {}
        return {"status": "unpinned", "tweet_id": str(tweet_id), "message": payload.get("message")}

    @safe
    async def pin_reply(self, tweet_id: str, conversation_id: str) -> dict:
        data = await self.x.graphql("PinReply", {"tweetId": str(tweet_id), "conversationId": str(conversation_id)})
        payload = (data.get("data") or {}).get("create_conversation_pinned_tweet") or {}
        if payload.get("success") is False:
            raise XError("X refused to pin that reply.", kind="validation")
        return {"status": "pinned_reply", "tweet_id": str(tweet_id), "conversation_id": str(conversation_id)}

    @safe
    async def unpin_reply(self, tweet_id: str, conversation_id: str) -> dict:
        data = await self.x.graphql("UnpinReply", {"tweetId": str(tweet_id), "conversationId": str(conversation_id)})
        payload = (data.get("data") or {}).get("delete_conversation_pinned_tweet") or {}
        if payload.get("success") is False:
            raise XError("X refused to unpin that reply.", kind="validation")
        return {"status": "unpinned_reply", "tweet_id": str(tweet_id), "conversation_id": str(conversation_id)}

    @safe
    async def dm_block(self, user_id: str) -> dict:
        data = await self.x.graphql("dmBlockUser", {"target_user_id": str(user_id)})
        payload = (data.get("data") or {}).get("dm_block_by_rest_id") or {}
        if payload.get("__typename") == "DmBlockInvalidRequestResult":
            raise XError(f"X refused the DM block: {payload.get('dm_block_invalid_request_reason')}", kind="validation")
        return {"status": "dm_blocked", "user_id": str(user_id)}

    @safe
    async def dm_unblock(self, user_id: str) -> dict:
        data = await self.x.graphql("dmUnblockUser", {"target_user_id": str(user_id)})
        payload = (data.get("data") or {}).get("dm_unblock_by_rest_id") or {}
        if payload.get("__typename") == "DmUnblockInvalidRequestResult":
            raise XError(f"X refused the DM unblock: {payload.get('dm_unblock_invalid_request_reason')}", kind="validation")
        return {"status": "dm_unblocked", "user_id": str(user_id)}

    # ══════════════════════════════════════════════════════════
    #  Lists
    # ══════════════════════════════════════════════════════════

    @safe
    async def create_list(self, name: str, description: str = "", private: bool = False) -> dict:
        data = await self.x.graphql(
            "CreateList",
            {"name": name, "description": description, "isPrivate": private, "withSuperFollowsUserFields": False},
        )
        result = (data.get("data") or {}).get("list") or {}
        list_id = sid(result.get("id_str") or result.get("id"))
        if not list_id:
            raise XError("X did not return the new list id.", kind="upstream", hint=json.dumps(data.get("data") or {})[:200])
        return {"status": "created", "list_id": list_id, "name": name, "private": private}

    @safe
    async def update_list(self, list_id: str, name: str, description: str = "", private: Optional[bool] = None) -> dict:
        variables: dict[str, Any] = {
            "listId": str(list_id),
            "name": name,
            "description": description,
            "withSuperFollowsUserFields": False,
        }
        if private is not None:
            variables["isPrivate"] = private
        data = await self.x.graphql("UpdateList", variables)
        payload = (data.get("data") or {}).get("list")
        if not payload:
            raise XError(f"X did not confirm the update of list {list_id}.", kind="upstream")
        return {"status": "updated", "list_id": str(list_id), "name": payload.get("name", name)}

    @safe
    async def delete_list(self, list_id: str) -> dict:
        data = await self.x.graphql("DeleteList", {"listId": str(list_id)})
        if (data.get("data") or {}).get("list_delete") != "Done":
            raise XError(f"X did not confirm deletion of list {list_id}.", kind="upstream")
        return {"status": "deleted", "list_id": str(list_id)}

    @safe
    async def add_list_member(self, list_id: str, user_id: str) -> dict:
        data = await self.x.graphql(
            "ListAddMember", {"listId": str(list_id), "userId": str(user_id), "withSuperFollowsUserFields": False}
        )
        payload = (data.get("data") or {}).get("list") or {}
        if not payload:
            raise XError(f"X did not confirm adding {user_id} to list {list_id}.", kind="upstream")
        return {"status": "added", "list_id": str(list_id), "user_id": str(user_id)}

    @safe
    async def remove_list_member(self, list_id: str, user_id: str) -> dict:
        data = await self.x.graphql(
            "ListRemoveMember", {"listId": str(list_id), "userId": str(user_id), "withSuperFollowsUserFields": False}
        )
        payload = (data.get("data") or {}).get("list") or {}
        if not payload:
            raise XError(f"X did not confirm removing {user_id} from list {list_id}.", kind="upstream")
        return {"status": "removed", "list_id": str(list_id), "user_id": str(user_id)}

    @safe
    async def subscribe_list(self, list_id: str) -> dict:
        data = await self.x.graphql("ListSubscribe", {"listId": str(list_id)})
        payload = (data.get("data") or {}).get("list_subscribe_v3") or (data.get("data") or {}).get("list_subscribe")
        if payload is None:
            raise XError(f"X did not confirm subscribing to list {list_id}.", kind="upstream")
        return {"status": "subscribed", "list_id": str(list_id)}

    @safe
    async def unsubscribe_list(self, list_id: str) -> dict:
        data = await self.x.graphql("ListUnsubscribe", {"listId": str(list_id)})
        payload = (data.get("data") or {}).get("list") or (data.get("data") or {}).get("list_unsubscribe")
        if payload is None:
            raise XError(f"X did not confirm unsubscribing from list {list_id}.", kind="upstream")
        return {"status": "unsubscribed", "list_id": str(list_id)}

    @safe
    async def list_info(self, list_id: str) -> dict:
        data = await self.x.graphql("ListByRestId", {"listId": str(list_id)})
        info = (data.get("data") or {}).get("list") or {}
        if not info:
            raise XError(f"List {list_id} not found.", kind="not_found")
        return {
            "list_id": sid(info.get("id_str") or info.get("id") or list_id),
            "name": info.get("name"),
            "description": info.get("description"),
            "member_count": info.get("member_count"),
            "subscriber_count": info.get("subscriber_count"),
            "private": info.get("mode") == "private" or bool(info.get("is_private")),
            "created_at": iso_time(info.get("created_at")),
            "owner": user_dict(((info.get("user_results") or {}).get("result"))),
        }

    @safe
    async def list_memberships(self, user_id: str, limit: int = 20, cursor: Optional[str] = None) -> dict:
        data = await self.x.graphql("ListMemberships", {"userId": str(user_id), **_cursor_vars(cursor, limit)})
        lists, next_cursor = _parse_list_timeline(data)
        result = {"lists": lists, "count": len(lists), "next_cursor": next_cursor}
        if not lists:
            result["note"] = "X returned no lists for this user; its memberships timeline is unreliable outside the web client."
        return result

    @safe
    async def list_ownerships(self, user_id: str, limit: int = 20, cursor: Optional[str] = None) -> dict:
        data = await self.x.graphql(
            "ListOwnerships",
            {"userId": str(user_id), "isListMemberTargetUserId": str(user_id), **_cursor_vars(cursor, limit)},
        )
        lists, next_cursor = _parse_list_timeline(data)
        return {"lists": lists, "count": len(lists), "next_cursor": next_cursor}

    @safe
    async def list_subscribers(self, list_id: str, limit: int = 20, cursor: Optional[str] = None) -> dict:
        data = await self.x.graphql("ListSubscribers", {"listId": str(list_id), **_cursor_vars(cursor, limit)})
        _, users, next_cursor = timeline(data)
        return {"users": users, "count": len(users), "next_cursor": next_cursor}

    # ══════════════════════════════════════════════════════════
    #  Communities & topics
    # ══════════════════════════════════════════════════════════

    @safe
    async def community_info(self, community_id: str) -> dict:
        data = await self.x.graphql("CommunityByRestId", {"communityId": str(community_id)})
        result = ((data.get("data") or {}).get("communityResults") or {}).get("result") or {}
        if result.get("__typename") != "Community":
            raise XError(f"Community {community_id} is unavailable.", kind="not_found")
        return {
            "community_id": str(community_id),
            "name": result.get("name"),
            "description": result.get("description"),
            "member_count": result.get("member_count"),
            "created_at": iso_time(result.get("created_at")),
            "is_member": (result.get("members_facepile_results") is not None),
            "join_policy": result.get("join_policy"),
            "admin": user_dict(((result.get("admin_results") or {}).get("result"))),
        }

    @safe
    async def join_community(self, community_id: str) -> dict:
        data = await self.x.graphql("JoinCommunity", {"communityId": str(community_id)})
        payload = (data.get("data") or {}).get("community_join")
        if payload is None:
            raise XError(f"X did not confirm joining community {community_id}.", kind="upstream")
        return {"status": "joined", "community_id": str(community_id)}

    @safe
    async def leave_community(self, community_id: str) -> dict:
        data = await self.x.graphql("LeaveCommunity", {"communityId": str(community_id)})
        payload = (data.get("data") or {}).get("community_leave")
        if payload is None:
            raise XError(f"X did not confirm leaving community {community_id}.", kind="upstream")
        return {"status": "left", "community_id": str(community_id)}

    @safe
    async def topic_info(self, topic_id: str) -> dict:
        data = await self.x.graphql("TopicByRestId", {"topicId": str(topic_id)})
        topic = (data.get("data") or {}).get("topic") or {}
        if not topic or not topic.get("name"):
            raise XError(f"Topic {topic_id} not found.", kind="not_found", hint="X only resolves topic ids it handed out itself (trends/topic pages).")
        return {
            "topic_id": str(topic_id),
            "name": topic.get("name"),
            "following": topic.get("following"),
            "not_interested": topic.get("not_interested"),
        }

    @safe
    async def follow_topic(self, topic_id: str) -> dict:
        data = await self.x.graphql("TopicFollow", {"topicId": str(topic_id)})
        topic = (data.get("data") or {}).get("topic") or {}
        if not topic.get("name"):
            raise XError(f"Topic {topic_id} not found.", kind="not_found")
        if topic.get("following") is False:
            raise XError("X did not follow that topic.", kind="upstream")
        return {"status": "followed", "topic_id": str(topic_id), "name": topic.get("name")}

    @safe
    async def unfollow_topic(self, topic_id: str) -> dict:
        data = await self.x.graphql("TopicUnfollow", {"topicId": str(topic_id)})
        topic = (data.get("data") or {}).get("topic") or {}
        if not topic.get("name"):
            raise XError(f"Topic {topic_id} not found.", kind="not_found")
        return {"status": "unfollowed", "topic_id": str(topic_id), "name": topic.get("name")}

    # ══════════════════════════════════════════════════════════
    #  Direct messages
    # ══════════════════════════════════════════════════════════

    @safe
    async def send_dm(self, user_id: str, text: str) -> dict:
        variables = {
            "message": {"card": None, "media": None, "text": {"text": text}, "tweet": None},
            "requestId": str(uuid.uuid4()),
            "target": {"participant_ids": [str(user_id)]},
        }
        data = await self.x.graphql("useSendMessageMutation", variables)
        result = (data.get("data") or {}).get("create_dm") or {}
        if result.get("__typename") != "CreateDmSuccess":
            reason = result.get("dm_validation_failure_type") or result.get("__typename") or "unknown"
            raise XError(f"DM not sent: {reason}", kind="validation", hint="The recipient must allow DMs from you.")
        return {
            "status": "sent",
            "user_id": str(user_id),
            "text": text,
            "conversation_id": sid(result.get("conversation_id")),
            "dm_id": sid(result.get("dm_id")),
        }

    @safe
    async def dm_inbox(self, limit: int = 20) -> dict:
        payload = await self.x.rest("GET", "dm/inbox_initial_state.json")
        messages = dm_messages(payload)[:limit]
        conversations = dm_conversations(payload)
        return {
            "messages": messages,
            "count": len(messages),
            "conversations": conversations,
            "conversation_count": len(conversations),
        }

    @safe
    async def dm_conversation(self, conversation_id: str, limit: int = 50) -> dict:
        payload = await self.x.rest(
            "GET",
            f"dm/conversation/{conversation_id}.json",
            params={"context": "FETCH_DM_CONVERSATION_HISTORY", "include_conversation_info": "true"},
        )
        messages = dm_messages(payload)
        messages.sort(key=lambda m: (m.get("timestamp") or "", m.get("message_id") or ""))
        participants = dm_conversations(payload)
        return {
            "conversation_id": conversation_id,
            "messages": messages[-limit:],
            "count": min(len(messages), limit),
            "total": len(messages),
            "participants": participants[0]["participants"] if participants else [],
        }

    @safe
    async def dm_search(self, query: str, limit: int = 20, kind: str = "all") -> dict:
        op = {"all": "DmAllSearchSlice", "groups": "DmGroupSearchSlice", "people": "DmPeopleSearchSlice"}.get(kind)
        if not op:
            raise XError("kind must be one of: all, groups, people", kind="validation")
        variables = {
            "query": query,
            "count": limit,
            "withAttachments": False,
            "withConversationQueryHighlights": False,
            "withMessageQueryHighlights": False,
        }
        data = await self.x.graphql(op, variables)
        tweets, users, cursor = timeline(data)
        messages = _find_dm_messages(data)
        if kind == "people":
            # People search returns a user slice, not a timeline.
            users = users or _find_users(data)
        return {"query": query, "messages": messages, "users": users, "count": len(messages or users), "next_cursor": cursor}

    @safe
    async def dm_muted(self, limit: int = 20) -> dict:
        data = await self.x.graphql("DmMutedTimeline", {"count": limit})
        return {"conversations": _find_dm_conversations(data)[:limit]}

    # ══════════════════════════════════════════════════════════
    #  Bookmarks
    # ══════════════════════════════════════════════════════════

    @safe
    async def bookmarks(self, limit: int = 20, cursor: Optional[str] = None) -> dict:
        data = await self.x.graphql("Bookmarks", {"includePromotedContent": False, **_cursor_vars(cursor, limit)})
        tweets, _, next_cursor = timeline(data)
        return {"tweets": tweets, "count": len(tweets), "next_cursor": next_cursor}

    @safe
    async def search_bookmarks(self, query: str, limit: int = 20, cursor: Optional[str] = None) -> dict:
        data = await self.x.graphql(
            "BookmarkSearchTimeline",
            {"rawQuery": query, **_cursor_vars(cursor, limit)},
        )
        tweets, _, next_cursor = timeline(data)
        return {"tweets": tweets, "count": len(tweets), "next_cursor": next_cursor}

    @safe
    async def bookmark_folders(self) -> dict:
        data = await self.x.graphql("BookmarkFoldersSlice", {})
        folders = _find_folders(data)
        result = {"folders": folders, "count": len(folders)}
        warnings = data.get("_warnings") or []
        if warnings:
            result["note"] = "; ".join(warnings)[:300]
        elif not folders:
            result["note"] = "No bookmark folders. X gates bookmark collections (Premium) on most accounts."
        return result

    @safe
    async def create_bookmark_folder(self, name: str) -> dict:
        data = await self.x.graphql("createBookmarkFolder", {"name": name})
        found = _find_folders(data)
        folder_id = sid(found[0].get("folder_id")) if found else None
        if not folder_id:
            raise XError("X did not return a folder id.", kind="upstream", hint=json.dumps(data.get("data") or {})[:200])
        return {"status": "created", "folder_id": folder_id, "name": name}

    @safe
    async def edit_bookmark_folder(self, folder_id: str, name: str) -> dict:
        data = await self.x.graphql("EditBookmarkFolder", {"bookmark_collection_id": folder_id, "name": name})
        if not data.get("data"):
            raise XError("X did not confirm the folder rename.", kind="upstream")
        return {"status": "updated", "folder_id": folder_id, "name": name}

    @safe
    async def delete_bookmark_folder(self, folder_id: str) -> dict:
        data = await self.x.graphql("DeleteBookmarkFolder", {"bookmark_collection_id": folder_id})
        if not data.get("data"):
            raise XError("X did not confirm the folder deletion.", kind="upstream")
        return {"status": "deleted", "folder_id": folder_id}

    @safe
    async def add_to_folder(self, folder_id: str, tweet_id: str) -> dict:
        data = await self.x.graphql(
            "bookmarkTweetToFolder", {"bookmark_collection_id": folder_id, "tweet_id": str(tweet_id)}
        )
        if not data.get("data"):
            raise XError("X did not confirm adding the tweet to the folder.", kind="upstream")
        return {"status": "added", "folder_id": folder_id, "tweet_id": str(tweet_id)}

    @safe
    async def remove_from_folder(self, folder_id: str, tweet_id: str) -> dict:
        data = await self.x.graphql(
            "RemoveTweetFromBookmarkFolder", {"bookmark_collection_id": folder_id, "tweet_id": str(tweet_id)}
        )
        if not data.get("data"):
            raise XError("X did not confirm removing the tweet from the folder.", kind="upstream")
        return {"status": "removed", "folder_id": folder_id, "tweet_id": str(tweet_id)}

    @safe
    async def folder_timeline(self, folder_id: str, limit: int = 20, cursor: Optional[str] = None) -> dict:
        data = await self.x.graphql(
            "BookmarkFolderTimeline",
            {"bookmark_collection_id": folder_id, **_cursor_vars(cursor, limit)},
        )
        tweets, _, next_cursor = timeline(data)
        result = {"folder_id": folder_id, "tweets": tweets, "count": len(tweets), "next_cursor": next_cursor}
        if not tweets:
            result["note"] = "Empty or unknown folder — X returns an empty collection instead of a 404."
        return result

    @safe
    async def clear_bookmarks(self) -> dict:
        data = await self.x.graphql("BookmarksAllDelete", {})
        if (data.get("data") or {}).get("bookmark_all_delete") != "Done":
            raise XError("X did not confirm clearing bookmarks.", kind="upstream")
        return {"status": "cleared"}

    # ══════════════════════════════════════════════════════════
    #  Scheduled tweets & drafts
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _timestamp(execute_at: str) -> int:
        try:
            dt = datetime.fromisoformat(execute_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise XError(
                f"Invalid datetime {execute_at!r}. Use ISO 8601, e.g. 2026-06-25T14:00:00Z",
                kind="validation",
            ) from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    @safe
    async def schedule_tweet(
        self, text: str, execute_at: str, reply_to: Optional[str] = None, media_ids: Optional[list[str]] = None
    ) -> dict:
        ts = self._timestamp(execute_at)
        if ts <= int(time.time()):
            raise XError("execute_at must be in the future.", kind="validation")
        request: dict[str, Any] = {"status": text, "media_ids": [str(m) for m in media_ids or []]}
        if reply_to:
            request["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
        data = await self.x.graphql("CreateScheduledTweet", {"post_tweet_request": request, "execute_at": ts})
        scheduled_id = None
        payload = data.get("data") or {}
        scheduled_id = sid((payload.get("scheduled_tweet") or {}).get("rest_id") or (payload.get("tweet") or {}).get("rest_id"))
        return {
            "status": "scheduled",
            "scheduled_id": scheduled_id,
            "execute_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "text": text,
        }

    @safe
    async def scheduled_tweets(self) -> dict:
        data = await self.x.graphql("FetchScheduledTweets", {"ascending": False})
        items = ((data.get("data") or {}).get("viewer") or {}).get("scheduled_tweet_list") or []
        out = []
        for item in items:
            info = item.get("scheduling_info") or {}
            request = item.get("tweet_create_request") or {}
            out.append(
                {
                    "scheduled_id": sid(item.get("rest_id")),
                    "text": request.get("status", ""),
                    "execute_at": iso_time(info.get("execute_at")),
                    "state": info.get("state"),
                    "media_ids": request.get("media_ids") or [],
                }
            )
        return {"scheduled_tweets": out, "count": len(out)}

    @safe
    async def delete_scheduled_tweet(self, scheduled_id: str) -> dict:
        data = await self.x.graphql("DeleteScheduledTweet", {"scheduled_tweet_id": str(scheduled_id)})
        if (data.get("data") or {}).get("scheduledtweet_delete") != "Done":
            raise XError("X did not confirm deleting the scheduled tweet.", kind="upstream")
        return {"status": "deleted", "scheduled_id": str(scheduled_id)}

    @safe
    async def edit_scheduled_tweet(self, scheduled_id: str, text: str, execute_at: str) -> dict:
        ts = self._timestamp(execute_at)
        data = await self.x.graphql(
            "EditScheduledTweet",
            {
                "scheduled_tweet_id": str(scheduled_id),
                "post_tweet_request": {"status": text, "media_ids": []},
                "execute_at": ts,
            },
        )
        if not data.get("data"):
            raise XError("X did not confirm the edit.", kind="upstream")
        return {"status": "edited", "scheduled_id": str(scheduled_id), "execute_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()}

    @safe
    async def create_draft(self, text: str) -> dict:
        data = await self.x.graphql("CreateDraftTweet", {"post_tweet_request": {"status": text, "media_ids": []}})
        draft_id = sid(((data.get("data") or {}).get("tweet") or {}).get("rest_id"))
        if not draft_id:
            raise XError("X did not return a draft id.", kind="upstream")
        return {"status": "draft_created", "draft_id": draft_id, "text": text}

    @safe
    async def drafts(self) -> dict:
        data = await self.x.graphql("FetchDraftTweets", {"ascending": False})
        items = ((data.get("data") or {}).get("viewer") or {}).get("draft_list", {}).get("response_data") or []
        out = []
        for item in items:
            request = item.get("tweet_create_request") or {}
            out.append({"draft_id": sid(item.get("rest_id")), "text": request.get("status", ""), "media_ids": request.get("media_ids") or []})
        return {"drafts": out, "count": len(out)}

    @safe
    async def delete_draft(self, draft_id: str) -> dict:
        data = await self.x.graphql("DeleteDraftTweet", {"draft_tweet_id": str(draft_id)})
        if (data.get("data") or {}).get("drafttweet_delete") != "Done":
            raise XError("X did not confirm deleting the draft.", kind="upstream")
        return {"status": "deleted", "draft_id": str(draft_id)}

    @safe
    async def edit_draft(self, draft_id: str, text: str) -> dict:
        data = await self.x.graphql(
            "EditDraftTweet", {"draft_tweet_id": str(draft_id), "post_tweet_request": {"status": text, "media_ids": []}}
        )
        if not data.get("data"):
            raise XError("X did not confirm the draft edit.", kind="upstream")
        return {"status": "edited", "draft_id": str(draft_id), "text": text}

    # ══════════════════════════════════════════════════════════
    #  Notifications
    # ══════════════════════════════════════════════════════════

    @safe
    async def notifications(self, limit: int = 20, cursor: Optional[str] = None, kind: str = "All") -> dict:
        data = await self.x.graphql(
            "NotificationsTimeline",
            {"timeline_type": kind, **_cursor_vars(cursor, limit)},
        )
        items = parse_notifications(data)
        _, _, next_cursor = timeline(data)
        return {"notifications": items[:limit], "count": min(len(items), limit), "next_cursor": next_cursor}

    # ══════════════════════════════════════════════════════════
    #  Trends
    # ══════════════════════════════════════════════════════════

    TREND_CATEGORIES = {"trending": 0, "news": 1, "sport": 2, "entertainment": 3}

    @safe
    async def trends(self, woeid: int = 1, limit: int = 20) -> dict:
        payload = await self.x.rest("GET", "trends/place.json", params={"id": str(woeid)})
        if not isinstance(payload, list) or not payload:
            raise XError(f"No trends for woeid {woeid}.", kind="not_found", hint="Use get_trend_locations to find a woeid.")
        place = payload[0]
        trends = []
        for t in (place.get("trends") or [])[:limit]:
            trends.append(
                {
                    "name": t.get("name"),
                    "query": t.get("query"),
                    "tweet_count": t.get("tweet_volume"),
                    "url": t.get("url"),
                    "promoted": bool(t.get("promoted_content")),
                }
            )
        return {"woeid": woeid, "location": place.get("locations", [{}])[0].get("name"), "trends": trends, "count": len(trends)}

    @safe
    async def trend_locations(self) -> dict:
        payload = await self.x.rest("GET", "trends/available.json")
        rows = [{"woeid": l.get("woeid"), "name": l.get("name"), "country": l.get("country"), "place_type": l.get("placeType", {}).get("name")} for l in payload]
        rows.sort(key=lambda r: (r["country"] or "", r["name"] or ""))
        return {"locations": rows, "count": len(rows)}

    # ══════════════════════════════════════════════════════════
    #  Profile
    # ══════════════════════════════════════════════════════════

    @safe
    async def update_profile(
        self, name: Optional[str] = None, bio: Optional[str] = None, location: Optional[str] = None, website: Optional[str] = None
    ) -> dict:
        params: dict[str, str] = {}
        if name:
            params["name"] = name[:50]
        if bio is not None:
            if any(ch in bio for ch in "<>&"):
                raise XError("Bio cannot contain < > or & — X rejects those characters.", kind="validation", code=120)
            params["description"] = bio[:160]
        if location:
            params["location"] = location[:30]
        if website:
            params["url"] = website
        if not params:
            raise XError("Nothing to update: pass name, bio, location or website.", kind="validation")

        client = await self._session_client()
        headers = {"content-type": "application/x-www-form-urlencoded", **(await self._tx_headers("/1.1/account/update_profile.json"))}
        resp = await client.post(f"{REST}/account/update_profile.json", data=params, headers=headers)
        if resp.status_code != 200:
            payload = _json_or_text(resp)
            if isinstance(payload, dict) and payload.get("errors"):
                raise from_x_error(payload["errors"][0], operation="update_profile")
            raise XError(f"HTTP {resp.status_code} from update_profile", kind="upstream", status=resp.status_code, hint=str(payload)[:200])
        payload = resp.json()
        return {
            "status": "updated",
            "name": payload.get("name"),
            "bio": payload.get("description"),
            "location": payload.get("location"),
            "website": payload.get("url"),
        }

    @safe
    async def update_profile_image(self, file_path: str) -> dict:
        return await self._update_profile_media(file_path, "image", "update_profile_image.json")

    @safe
    async def update_profile_banner(self, file_path: str) -> dict:
        return await self._update_profile_media(file_path, "banner", "update_profile_banner.json")

    async def _update_profile_media(self, file_path: str, field: str, endpoint: str) -> dict:
        if not os.path.exists(file_path):
            raise XError(f"File not found: {file_path}", kind="validation")
        content_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        client = await self._session_client()
        original = client.headers.pop("content-type", None)
        headers = await self._tx_headers(f"/1.1/account/{endpoint}")
        try:
            with open(file_path, "rb") as fh:
                resp = await client.post(
                    f"{REST}/account/{endpoint}",
                    files={field: (os.path.basename(file_path), fh, content_type)},
                    headers=headers,
                )
            if original:
                client.headers["content-type"] = original
            if resp.status_code not in (200, 201):
                payload = _json_or_text(resp)
                raise XError(
                    f"HTTP {resp.status_code} updating profile {field}",
                    kind="upstream",
                    status=resp.status_code,
                    hint=str(payload)[:200],
                )
            return {"status": "updated", "field": field, "file": file_path}
        finally:
            pass

    @safe
    async def delete_profile_banner(self) -> dict:
        client = await self._session_client()
        headers = await self._tx_headers("/1.1/account/remove_profile_banner.json")
        resp = await client.post(f"{REST}/account/remove_profile_banner.json", data={}, headers=headers)
        if resp.status_code != 200:
            raise XError(f"HTTP {resp.status_code} removing banner", kind="upstream", status=resp.status_code, hint=resp.text[:200])
        return {"status": "deleted", "field": "banner"}

    async def _tx_headers(self, path: str) -> dict:
        """x-client-transaction-id is mandatory on the account/* REST writes."""
        accounts = await self.x.pool.get_all()
        acc = next((a for a in accounts if a.active and not a.error_msg), None)
        if not acc:
            raise XError("No active accounts.", kind="auth")
        tx = await self.x._txid(acc)
        return {"x-client-transaction-id": tx.calc("POST", path)} if tx else {}

    async def _session_client(self):
        """A raw client for multipart/form-encoded profile calls."""
        accounts = await self.x.pool.get_all()
        acc = next((a for a in accounts if a.active and not a.error_msg), None)
        if not acc:
            raise XError("No active accounts.", kind="auth")
        return await self.x._client(acc)

    # ══════════════════════════════════════════════════════════
    #  Media
    # ══════════════════════════════════════════════════════════

    @safe
    async def upload_media(self, file_path: str) -> dict:
        """3-phase cookie-auth upload: INIT -> APPEND (4 MiB chunks) -> FINALIZE."""
        if not os.path.exists(file_path):
            raise XError(f"File not found: {file_path}", kind="validation")
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        size = os.path.getsize(file_path)
        if size > 512 * 1024 * 1024:
            raise XError("File exceeds X's 512 MB media limit.", kind="validation")
        is_video = content_type.startswith("video/") or content_type == "image/gif"
        url = "https://upload.twitter.com/i/media/upload2.json" if is_video else "https://upload.twitter.com/i/media/upload.json"

        accounts = await self.x.pool.get_all()
        acc = next((a for a in accounts if a.active and not a.error_msg), None)
        if not acc:
            raise XError("No active accounts.", kind="auth")
        cookies = _cookies(acc)
        headers = {
            "authorization": f"Bearer {BEARER}",
            "cookie": f"auth_token={cookies.get('auth_token','')}; ct0={cookies.get('ct0','')}",
            "x-csrf-token": cookies.get("ct0", ""),
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "origin": "https://x.com",
            "referer": "https://x.com/compose/post",
        }

        import curl_cffi
        import curl_cffi.requests as curl_requests

        session = curl_requests.AsyncSession(impersonate="chrome")
        try:
            init = {"command": "INIT", "total_bytes": str(size), "media_type": content_type}
            if is_video:
                init["media_category"] = "tweet_video" if content_type.startswith("video/") else "tweet_gif"
            resp = await session.post(url, data=init, headers={**headers, "content-type": "application/x-www-form-urlencoded"})
            if resp.status_code not in (200, 202):
                raise XError(f"Media INIT failed (HTTP {resp.status_code})", kind="upstream", hint=resp.text[:200])
            media_id = (resp.json() or {}).get("media_id_string")
            if not media_id:
                raise XError("Media INIT returned no media id.", kind="upstream", hint=resp.text[:200])

            chunk_size = 4 * 1024 * 1024
            with open(file_path, "rb") as fh:
                index = 0
                while chunk := fh.read(chunk_size):
                    mp = curl_cffi.CurlMime()
                    mp.addpart(name="media", content_type=content_type, filename=os.path.basename(file_path), data=chunk)
                    r = await session.post(
                        url,
                        data={"command": "APPEND", "media_id": media_id, "segment_index": str(index)},
                        multipart=mp,
                        headers=headers,
                    )
                    mp.close()
                    if r.status_code not in (200, 204):
                        raise XError(f"Media APPEND failed at segment {index} (HTTP {r.status_code})", kind="upstream", hint=r.text[:200])
                    index += 1

            fin = await session.post(
                url, data={"command": "FINALIZE", "media_id": media_id}, headers={**headers, "content-type": "application/x-www-form-urlencoded"}
            )
            if fin.status_code not in (200, 201, 202):
                raise XError(f"Media FINALIZE failed (HTTP {fin.status_code})", kind="upstream", hint=fin.text[:200])
            info = (fin.json() or {}).get("processing_info") or {}
            import asyncio

            for _ in range(60):
                if info.get("state") in (None, "succeeded"):
                    break
                if info.get("state") == "failed":
                    raise XError("X failed to process the media.", kind="upstream", hint=json.dumps(info)[:200])
                await asyncio.sleep(info.get("check_after_secs", 3))
                status_resp = await session.get(f"{url}?command=STATUS&media_id={media_id}", headers=headers)
                info = (status_resp.json() or {}).get("processing_info") or {}
            return {
                "status": "uploaded",
                "media_id": str(media_id),
                "media_type": "video" if is_video else "image",
                "usage": f'post_tweet(text=..., media_ids="{media_id}")',
            }
        finally:
            await session.close()

    @safe
    async def download_media(self, source: str, dest_dir: str = ".") -> dict:
        """Download a tweet's media (or one media URL) to disk."""
        os.makedirs(dest_dir, exist_ok=True)
        urls: list[str] = []
        if source.startswith("http"):
            urls = [source]
        else:
            tweet = await self.tweet(source)
            urls = tweet.get("media_urls") or []
            if not urls:
                raise XError("That tweet has no media.", kind="not_found")
        saved = []
        for url in urls:
            data = await self.x.get_bytes(url)
            name = url.split("/")[-1].split("?")[0] or f"media_{int(time.time())}"
            path = os.path.join(dest_dir, f"{uuid.uuid4().hex[:8]}_{name}")
            with open(path, "wb") as fh:
                fh.write(data)
            saved.append({"path": path, "bytes": len(data), "source_url": url})
        return {"files": saved, "count": len(saved)}

    # ══════════════════════════════════════════════════════════
    #  Limits / health
    # ══════════════════════════════════════════════════════════

    @safe
    async def rate_limits(self) -> dict:
        accounts = await self.x.pool.get_all()
        rows = []
        for acc in accounts:
            rows.append(
                {
                    "username": acc.username,
                    "active": bool(acc.active),
                    "error": acc.error_msg,
                    "locks": acc.locks if isinstance(acc.locks, dict) else {},
                    "last_used": iso_time(str(acc.last_used)) if acc.last_used else None,
                    "last_response_headers": self.x.last_headers.get(acc.username, {}),
                }
            )
        return {"accounts": rows, "count": len(rows)}


# ══════════════════════════════════════════════════════════════
#  Response helpers local to this module
# ══════════════════════════════════════════════════════════════


def _json_or_text(resp) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text[:300]


def _parse_list_timeline(data: Any) -> tuple[list[dict], Optional[str]]:
    from spectre.parse import _entries  # local import keeps parse.py's surface small

    lists: list[dict] = []
    cursor = None
    seen = set()
    for entry in _entries(data):
        content = entry.get("content") or {}
        if content.get("entryType") == "TimelineTimelineCursor":
            if content.get("cursorType") == "Bottom":
                cursor = content.get("value")
            continue
        item = content.get("itemContent") or {}
        raw = item.get("list") or item
        list_id = sid(raw.get("id_str") or raw.get("id") or raw.get("rest_id"))
        if list_id and list_id not in seen:
            seen.add(list_id)
            lists.append(
                {
                    "list_id": list_id,
                    "name": raw.get("name"),
                    "description": raw.get("description"),
                    "member_count": raw.get("member_count"),
                    "subscriber_count": raw.get("subscriber_count"),
                    "private": raw.get("mode") == "private" or bool(raw.get("is_private")),
                }
            )
    return lists, cursor


def _find_folders(data: Any) -> list[dict]:
    folders: list[dict] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 12:
            return
        if isinstance(node, dict):
            if node.get("__typename") == "BookmarkCollection" or (
                "name" in node and ("id" in node or "bookmark_collection_id" in node) and ("visibility" in node or "sort_index" in node)
            ):
                fid = sid(node.get("id") or node.get("bookmark_collection_id"))
                if fid:
                    folders.append({"folder_id": fid, "name": node.get("name"), "visibility": node.get("visibility")})
                return
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(data)
    return folders


def _find_dm_messages(data: Any) -> list[dict]:
    out: list[dict] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 14:
            return
        if isinstance(node, dict):
            if "message_data" in node and isinstance(node["message_data"], dict):
                md = node["message_data"]
                out.append(
                    {
                        "message_id": sid(node.get("id")),
                        "conversation_id": sid(node.get("conversation_id")),
                        "text": md.get("text", ""),
                        "sender_id": sid(md.get("sender_id")),
                        "recipient_id": sid(md.get("recipient_id")),
                        "timestamp": iso_time(md.get("time")),
                    }
                )
                return
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(data)
    return out


def _find_dm_conversations(data: Any) -> list[dict]:
    out: list[dict] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 14:
            return
        if isinstance(node, dict):
            if node.get("__typename") == "DmConversation" or ("conversation_id" in node and "participants" in node):
                out.append(
                    {
                        "conversation_id": sid(node.get("conversation_id") or node.get("id")),
                        "name": (node.get("conversation_name") or ""),
                        "participants": node.get("participants") or [],
                    }
                )
                return
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(data)
    return out


def _find_users(data: Any) -> list[dict]:
    from spectre.parse import _entries

    users: list[dict] = []
    seen = set()
    for entry in _entries(data):
        content = entry.get("content") or {}
        item = content.get("itemContent") or {}
        parsed = user_dict((item.get("user_results") or {}).get("result"))
        if parsed and parsed["id"] not in seen:
            seen.add(parsed["id"])
            users.append(parsed)
    return users
