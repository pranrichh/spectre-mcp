"""Response parsing: X's GraphQL REST JSON -> Spectre's stable output shapes.

Every read tool speaks the same two shapes no matter whether the data came from
GraphQL, REST v1.1 or twscrape. IDs are always strings.

Tweet:
    id, url, text, author_id, author_username, author_name, created_at, lang,
    reply_count, retweet_count, like_count, quote_count, view_count,
    bookmark_count, is_retweet, is_quote, is_reply, in_reply_to_id,
    conversation_id, media_urls, media_types, hashtags, urls, mentioned_users,
    quoted_tweet_id, quoted_tweet, retweeted_tweet_id

User:
    id, username, display_name, bio, location, website, followers, following,
    tweets, likes, media_count, verified, blue_verified, profile_image_url,
    banner_url, created_at, protected
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Optional

TWEET_URL = "https://x.com/{user}/status/{id}"


# ── primitive helpers ──────────────────────────────────────────────


def sid(value: Any) -> Optional[str]:
    """Normalise an id to a string (X mixes str/int across endpoints)."""
    if value is None or value == "":
        return None
    return str(value)


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def iso_time(value: Any, fallback: str = "") -> str:
    """Parse X's 'Fri Nov 13 23:43:30 +0000 2026' or ISO into ISO-8601."""
    if not value:
        return fallback
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    text = str(value)
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return fallback


def unwrap(res: Any) -> Optional[dict]:
    """Peel TweetWithVisibilityResults / TweetUnavailable wrappers."""
    if not isinstance(res, dict):
        return None
    if res.get("__typename") == "TweetWithVisibilityResults":
        res = res.get("tweet") or {}
    if res.get("__typename") == "TweetTombstone":
        return None
    if not res.get("rest_id") and not res.get("legacy"):
        return None
    return res


def _dig(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


# ── tweets ────────────────────────────────────────────────────────


def _media(tweet: dict) -> tuple[list[str], list[str]]:
    legacy = tweet.get("legacy") or {}
    entities = legacy.get("extended_entities") or legacy.get("entities") or {}
    urls: list[str] = []
    types: list[str] = []
    for m in entities.get("media") or []:
        kind = m.get("type") or "photo"
        if kind == "photo":
            url = m.get("media_url_https") or m.get("media_url")
            if url:
                urls.append(url)
                types.append("photo")
        elif kind in ("video", "animated_gif"):
            variants = (m.get("video_info") or {}).get("variants") or []
            mp4 = [v for v in variants if (v.get("content_type") or "").startswith("video/")]
            if mp4:
                best = max(mp4, key=lambda v: as_int(v.get("bitrate")))
                urls.append(best.get("url", ""))
                types.append("video" if kind == "video" else "animated_gif")
    return urls, types


def _entities(tweet: dict) -> tuple[list[str], list[str], list[str]]:
    legacy = tweet.get("legacy") or {}
    entities = legacy.get("entities") or {}
    hashtags = [h.get("text", "") for h in entities.get("hashtags") or [] if h.get("text")]
    urls = [u.get("expanded_url") or u.get("url") for u in entities.get("urls") or []]
    mentions = [m.get("screen_name", "") for m in entities.get("user_mentions") or [] if m.get("screen_name")]
    return hashtags, [u for u in urls if u], mentions


def tweet_dict(res: Any) -> Optional[dict]:
    """Convert one GraphQL tweet result object into Spectre's tweet shape."""
    t = unwrap(res)
    if not t:
        return None
    legacy = t.get("legacy") or {}
    rest_id = sid(t.get("rest_id"))

    user_res = _dig(t, "core", "user_results", "result") or {}
    author = user_dict(user_res) or {}
    username = author.get("username") or "i"

    # Long posts keep the full body in note_tweet; legacy.full_text is truncated.
    note = _dig(t, "note_tweet", "note_tweet_results", "result", "text")
    text = note or legacy.get("full_text") or ""

    quoted_res = _dig(legacy, "quoted_status_result", "result") or _dig(t, "quoted_status_result", "result")
    quoted = tweet_dict(quoted_res) if quoted_res else None
    retweet_res = _dig(legacy, "retweeted_status_result", "result")
    retweeted = tweet_dict(retweet_res) if retweet_res else None

    media_urls, media_types = _media(t)
    hashtags, urls, mentions = _entities(t)

    if retweeted:
        # Surface the original post's content, keep the wrapper's own id, like X's UI.
        media_urls = media_urls or retweeted["media_urls"]
        media_types = media_types or retweeted["media_types"]
        hashtags = hashtags or retweeted["hashtags"]
        urls = urls or retweeted["urls"]
        mentions = mentions or retweeted["mentioned_users"]

    return {
        "id": rest_id,
        "url": TWEET_URL.format(user=username, id=rest_id),
        "text": text,
        "author_id": author.get("id"),
        "author_username": author.get("username"),
        "author_name": author.get("display_name"),
        "created_at": iso_time(legacy.get("created_at")),
        "lang": legacy.get("lang") or t.get("lang"),
        "reply_count": as_int(legacy.get("reply_count")),
        "retweet_count": as_int(legacy.get("retweet_count")),
        "like_count": as_int(legacy.get("favorite_count")),
        "quote_count": as_int(legacy.get("quote_count")),
        "view_count": as_int(_dig(t, "views", "count")),
        "bookmark_count": as_int(legacy.get("bookmark_count")),
        "is_retweet": bool(retweeted),
        "is_quote": bool(legacy.get("is_quote_status")),
        "is_reply": bool(legacy.get("in_reply_to_status_id_str")),
        "in_reply_to_id": sid(legacy.get("in_reply_to_status_id_str")),
        "conversation_id": sid(legacy.get("conversation_id_str")),
        "media_urls": media_urls,
        "media_types": media_types,
        "hashtags": hashtags,
        "urls": urls,
        "mentioned_users": mentions,
        "quoted_tweet_id": quoted["id"] if quoted else None,
        "quoted_tweet": quoted["text"] if quoted else None,
        "retweeted_tweet_id": retweeted["id"] if retweeted else None,
    }


# ── users ─────────────────────────────────────────────────────────


def user_dict(res: Any) -> Optional[dict]:
    """Convert one GraphQL user result object into Spectre's user shape."""
    if not isinstance(res, dict):
        return None
    if res.get("__typename") in ("UserUnavailable", "UserTombstone"):
        return None
    u = res
    legacy = u.get("legacy") or {}
    core = u.get("core") or {}

    username = core.get("screen_name") or legacy.get("screen_name")
    if not username:
        return None

    def count(*paths: str) -> int:
        for path in paths:
            value = _dig(u, *path.split("."))
            if value is not None:
                return as_int(value)
        return 0

    avatar = _dig(u, "avatar", "image_url") or legacy.get("profile_image_url_https")
    banner = _dig(u, "banner", "image_url") or legacy.get("profile_banner_url")

    # X ships two user shapes depending on the feature flags: the classic
    # `legacy{...}` node and a flattened one (profile_bio / relationship_counts).
    bio = legacy.get("description") or _dig(u, "profile_bio", "description")
    location = legacy.get("location") or _dig(u, "location", "location") or None
    website = legacy.get("url") or _dig(u, "website", "url")
    if website and "t.co/" in website:
        expanded = next(
            (
                e.get("expanded_url")
                for source in (_dig(legacy, "entities", "url", "urls"), _dig(u, "profile_bio", "entities", "description", "urls"))
                for e in (source or [])
                if e.get("expanded_url")
            ),
            None,
        )
        website = expanded or website

    return {
        "id": sid(u.get("rest_id")),
        "username": username,
        "display_name": core.get("name") or legacy.get("name") or username,
        "bio": bio,
        "location": location,
        "website": website,
        "followers": count("legacy.followers_count", "relationship_counts.followers"),
        "following": count("legacy.friends_count", "relationship_counts.following"),
        "tweets": count("legacy.statuses_count", "tweet_counts.tweets"),
        "likes": count("legacy.favourites_count", "action_counts.favorites_count"),
        "media_count": count("legacy.media_count", "tweet_counts.media_tweets"),
        "verified": bool(_dig(u, "verification", "verified") or legacy.get("verified")),
        "blue_verified": bool(u.get("is_blue_verified")),
        "profile_image_url": avatar,
        "banner_url": banner,
        "created_at": iso_time(core.get("created_at") or legacy.get("created_at"), fallback="") or None,
        "protected": bool(_dig(u, "privacy", "protected") or legacy.get("protected")),
    }


# ── timelines ─────────────────────────────────────────────────────


def _entries(data: Any) -> Iterable[dict]:
    """Yield every timeline entry in a GraphQL response, at any nesting depth."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "entries" and isinstance(value, list):
                yield from (e for e in value if isinstance(e, dict))
            elif key == "moduleItems" and isinstance(value, list):
                yield from (e for e in value if isinstance(e, dict))
            else:
                yield from _entries(value)
    elif isinstance(data, list):
        for item in data:
            yield from _entries(item)


def _entry_results(entry: dict) -> tuple[list[dict], list[dict]]:
    """Pull tweet and user results out of one entry (handles modules)."""
    tweets: list[dict] = []
    users: list[dict] = []
    content = entry.get("content") or {}

    def from_item(item_content: dict) -> None:
        tr = _dig(item_content, "tweet_results", "result")
        if tr:
            tweets.append(tr)
        ur = _dig(item_content, "user_results", "result")
        if ur:
            users.append(ur)

    if "itemContent" in content:
        from_item(content["itemContent"])
    for item in content.get("items") or []:
        inner = _dig(item, "item", "itemContent") or {}
        if inner:
            from_item(inner)
        # Community/module entries nest one level deeper
        for sub in _dig(item, "item", "content", "items") or []:
            sub_inner = _dig(sub, "item", "itemContent") or {}
            if sub_inner:
                from_item(sub_inner)
    return tweets, users


def timeline(data: Any) -> tuple[list[dict], list[dict], Optional[str]]:
    """Parse a timeline response -> (tweets, users, next_cursor)."""
    tweets: list[dict] = []
    users: list[dict] = []
    cursor: Optional[str] = None
    seen_t: set[str] = set()
    seen_u: set[str] = set()

    for entry in _entries(data):
        content = entry.get("content") or {}
        if content.get("entryType") == "TimelineTimelineCursor" or "cursor" in str(entry.get("entryId", "")):
            if content.get("cursorType") == "Bottom":
                cursor = content.get("value")
            continue
        raw_tweets, raw_users = _entry_results(entry)
        for tr in raw_tweets:
            parsed = tweet_dict(tr)
            if parsed and parsed["id"] and parsed["id"] not in seen_t:
                seen_t.add(parsed["id"])
                tweets.append(parsed)
        for ur in raw_users:
            parsed = user_dict(ur)
            if parsed and parsed["id"] and parsed["id"] not in seen_u:
                seen_u.add(parsed["id"])
                users.append(parsed)
    return tweets, users, cursor


def instructions(data: Any) -> list[dict]:
    """All instruction objects in a GraphQL response (order preserved)."""
    out: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("instructions"), list):
                out.extend(i for i in node["instructions"] if isinstance(i, dict))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out


# ── notifications ─────────────────────────────────────────────────


def notifications(data: Any) -> list[dict]:
    """Flatten a notification timeline into one record per notification."""
    out: list[dict] = []
    for entry in _entries(data):
        content = entry.get("content") or {}
        if content.get("entryType") == "TimelineTimelineCursor":
            continue
        item_contexts: list[dict] = [content.get("itemContent") or {}]
        for item in content.get("items") or []:
            inner = _dig(item, "item", "itemContent") or {}
            if inner:
                item_contexts.append(inner)
        for ctx in item_contexts:
            ntype = ctx.get("notificationType") or ctx.get("notification_type") or ""
            tweet = tweet_dict(_dig(ctx, "tweet_results", "result")) if ctx.get("tweet_results") else None
            user = user_dict(_dig(ctx, "user_results", "result")) if ctx.get("user_results") else None
            tweets = [tweet] if tweet else []
            users = [user] if user else []
            for item in _dig(ctx, "message", "message_results") or []:
                pass
            if not (ntype or tweets or users):
                continue
            out.append(
                {
                    "id": entry.get("entryId"),
                    "type": ntype,
                    "user": user,
                    "tweet": tweet,
                    "users": users if len(users) > 1 else [],
                    "tweets": tweets if len(tweets) > 1 else [],
                }
            )
    return out


# ── direct messages ───────────────────────────────────────────────


def dm_messages(payload: dict) -> list[dict]:
    """Parse a v1.1 DM timeline (inbox or conversation) into messages."""
    timeline_obj = payload.get("conversation_timeline") or payload.get("inbox_initial_state") or payload
    entries = timeline_obj.get("entries") or []
    users = timeline_obj.get("users") or {}
    conversations = timeline_obj.get("conversations") or {}
    out: list[dict] = []
    for entry in entries:
        msg = entry.get("message") or {}
        data = msg.get("message_data") or {}
        sender_id = sid(data.get("sender_id"))
        recipient_id = sid(data.get("recipient_id"))
        sender = users.get(sender_id or "", {}) or {}
        conversation_id = sid(msg.get("conversation_id"))
        meta = conversations.get(conversation_id, {}) if isinstance(conversations, dict) else {}
        out.append(
            {
                "message_id": sid(msg.get("id")),
                "conversation_id": conversation_id,
                "text": data.get("text", ""),
                "sender_id": sender_id,
                "sender_username": sender.get("screen_name"),
                "recipient_id": recipient_id,
                "timestamp": iso_time(as_int(data.get("time"))),
                "conversation_name": _dig(meta, "conversation_name"),
            }
        )
    return out


def dm_conversations(payload: dict) -> list[dict]:
    """Summarise DM conversations (one row per conversation)."""
    timeline_obj = payload.get("inbox_initial_state") or payload.get("conversation_timeline") or payload
    conversations = timeline_obj.get("conversations") or {}
    users = timeline_obj.get("users") or {}
    out: list[dict] = []
    for cid, meta in conversations.items():
        participants = []
        for pid in meta.get("participants") or []:
            user = users.get(sid(pid), {}) or {}
            participants.append(
                {"id": sid(pid), "username": user.get("screen_name"), "name": user.get("name")}
            )
        out.append(
            {
                "conversation_id": cid,
                "name": meta.get("conversation_name"),
                "type": meta.get("type"),
                "participants": participants,
                "last_read_event_id": sid(meta.get("last_read_event_id")),
            }
        )
    return out
