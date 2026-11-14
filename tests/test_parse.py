"""Parser tests against response shapes captured from live X.

These exist because the shapes are inconsistent: the same Tweet arrives under
`tweet_results.result`, `tweetResult.result` or wrapped in
`TweetWithVisibilityResults`, and users arrive with either a `legacy` node or a
flattened `profile_bio` / `relationship_counts` shape. Fixtures keep the parser
honest without spending rate limit.

Run: .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spectre.parse import dm_messages, notifications, timeline, tweet_dict, user_dict


def td(raw) -> dict:
    """tweet_dict that asserts the result is not None (keeps pyright happy)."""
    result = tweet_dict(raw)
    assert result is not None
    return result


def ud(raw) -> dict:
    result = user_dict(raw)
    assert result is not None
    return result


def test_tweet_uses_note_tweet_for_long_form():
    raw = {
        "rest_id": "1",
        "legacy": {"full_text": "truncated…", "created_at": "Fri Nov 13 23:43:30 +0000 2026", "favorite_count": 5},
        "note_tweet": {"note_tweet_results": {"result": {"text": "the whole long post"}}},
        "core": {"user_results": {"result": {"rest_id": "9", "core": {"screen_name": "a", "name": "A"}}}},
    }
    tweet = td(raw)
    assert tweet["text"] == "the whole long post"
    assert tweet["created_at"].startswith("2026-11-13T23:43:30")
    assert tweet["like_count"] == 5


def test_tweet_unwraps_visibility_wrapper():
    inner = {
        "rest_id": "2",
        "legacy": {"full_text": "hello"},
        "core": {"user_results": {"result": {"core": {"screen_name": "b", "name": "B"}}}},
    }
    tweet = td({"__typename": "TweetWithVisibilityResults", "tweet": inner})
    assert tweet["id"] == "2"
    assert tweet["author_username"] == "b"


def test_tweet_nested_user_exposes_author():
    raw = {
        "rest_id": "3",
        "legacy": {"full_text": "x"},
        "core": {"user_results": {"result": {"legacy": {"screen_name": "c", "name": "C"}}}},
    }
    assert td(raw)["author_name"] == "C"


def test_retweet_marks_and_surfaces_original():
    original = {
        "rest_id": "4",
        "legacy": {"full_text": "original text", "entities": {"hashtags": [{"text": "tag"}]}},
        "core": {"user_results": {"result": {"core": {"screen_name": "orig", "name": "Orig"}}}},
    }
    wrapper = {
        "rest_id": "5",
        "legacy": {"full_text": "RT @orig: original text", "retweeted_status_result": {"result": original}},
        "core": {"user_results": {"result": {"core": {"screen_name": "rt", "name": "RT"}}}},
    }
    tweet = td(wrapper)
    assert tweet["is_retweet"] is True
    assert tweet["retweeted_tweet_id"] == "4"
    assert tweet["hashtags"] == ["tag"]


def test_user_flattened_shape():
    raw = {
        "rest_id": "7",
        "core": {"screen_name": "flat", "name": "Flat", "created_at": "Tue Jun 02 20:12:29 +0000 2009"},
        "profile_bio": {"description": "bio here"},
        "location": {"location": "Earth"},
        "website": {"url": "https://t.co/x"},
        "relationship_counts": {"followers": 10, "following": 20},
        "tweet_counts": {"tweets": 30, "media_tweets": 2},
        "action_counts": {"favorites_count": 4},
        "verification": {"verified": True},
        "privacy": {"protected": False},
    }
    user = ud(raw)
    assert user["bio"] == "bio here"
    assert user["followers"] == 10
    assert user["tweets"] == 30
    assert user["verified"] is True


def test_user_legacy_shape():
    raw = {
        "rest_id": "8",
        "legacy": {
            "screen_name": "old",
            "name": "Old",
            "description": "legacy bio",
            "followers_count": 1,
            "friends_count": 2,
            "statuses_count": 3,
            "favourites_count": 4,
            "profile_image_url_https": "https://img",
        },
    }
    user = ud(raw)
    assert user["username"] == "old"
    assert user["followers"] == 1
    assert user["profile_image_url"] == "https://img"


def test_timeline_returns_next_cursor_and_skips_duplicates():
    payload = {
        "data": {
            "x": {
                "timeline": {
                    "instructions": [
                        {
                            "entries": [
                                {"entryId": "tweet-1", "content": {"itemContent": {"tweet_results": {"result": {
                                    "rest_id": "1", "legacy": {"full_text": "a"},
                                    "core": {"user_results": {"result": {"core": {"screen_name": "u"}}}}}}}}},
                                {"entryId": "tweet-1-dup", "content": {"itemContent": {"tweet_results": {"result": {
                                    "rest_id": "1", "legacy": {"full_text": "a"},
                                    "core": {"user_results": {"result": {"core": {"screen_name": "u"}}}}}}}}},
                                {"entryId": "cursor-bottom", "content": {
                                    "entryType": "TimelineTimelineCursor", "cursorType": "Bottom", "value": "CUR"}},
                            ]
                        }
                    ]
                }
            }
        }
    }
    tweets, users, cursor = timeline(payload)
    assert [t["id"] for t in tweets] == ["1"]
    assert cursor == "CUR"


def test_notifications_parse_type_and_actor():
    payload = {
        "instructions": [
            {
                "entries": [
                    {
                        "entryId": "notif-1",
                        "content": {
                            "itemContent": {
                                "notificationType": "Like",
                                "user_results": {"result": {"rest_id": "5", "core": {"screen_name": "fan", "name": "Fan"}}},
                                "tweet_results": {"result": {
                                    "rest_id": "6", "legacy": {"full_text": "liked post"},
                                    "core": {"user_results": {"result": {"core": {"screen_name": "me"}}}}}},
                            }
                        },
                    }
                ]
            }
        ]
    }
    items = notifications(payload)
    assert len(items) == 1
    assert items[0]["type"] == "Like"
    assert items[0]["user"]["username"] == "fan"
    assert items[0]["tweet"]["id"] == "6"


def test_dm_messages_resolves_sender_from_users_map():
    payload = {
        "conversation_timeline": {
            "entries": [
                {
                    "message": {
                        "id": "11",
                        "conversation_id": "1-2",
                        "message_data": {"sender_id": "1", "recipient_id": "2", "text": "hi", "time": "1785672239229"},
                    }
                }
            ],
            "users": {"1": {"screen_name": "sender"}},
            "conversations": {"1-2": {"conversation_name": "chat"}},
        }
    }
    messages = dm_messages(payload)
    assert messages[0]["sender_username"] == "sender"
    assert messages[0]["conversation_name"] == "chat"
    assert messages[0]["timestamp"].startswith("2026-")


def test_notifications_current_shape():
    """Current bundle: payload flattened on itemContent, kind in template."""
    payload = {
        "instructions": [
            {
                "entries": [
                    {
                        "entryId": "notif-42",
                        "content": {
                            "entryType": "TimelineTimelineItem",
                            "itemContent": {
                                "__typename": "TimelineNotification",
                                "id": "42",
                                "notification_icon": "heart_icon",
                                "timestamp_ms": "2025-05-05T01:18:21.657Z",
                                "rich_message": {
                                    "text": "Ada liked your post",
                                    "entities": [
                                        {
                                            "fromIndex": 0,
                                            "toIndex": 3,
                                            "ref": {
                                                "type": "TimelineRichTextUser",
                                                "user_results": {"result": {"rest_id": "9", "core": {"screen_name": "ada", "name": "Ada"}}},
                                            },
                                        }
                                    ],
                                },
                                "notification_url": {"url": "https://x.com/ada/status/777"},
                                "template": {"__typename": "TimelineNotificationAggregateUserActions", "from_users": []},
                            },
                        },
                    }
                ]
            }
        ]
    }
    items = notifications(payload)
    assert len(items) == 1
    item = items[0]
    assert item["type"] == "TimelineNotificationAggregateUserActions"
    assert item["text"] == "Ada liked your post"
    assert item["tweet_id"] == "777"
    assert item["timestamp"].startswith("2025-05-05")
    assert item["actors"][0]["username"] == "ada"


def test_dm_messages_skips_cursor_rows():
    payload = {
        "conversation_timeline": {
            "entries": [
                {"entryId": "cursor-top-1", "content": {"entryType": "TimelineTimelineCursor"}},
                {"entryId": "cursor-bottom-1", "content": {"entryType": "TimelineTimelineCursor"}},
                {"message": {"id": "77", "conversation_id": "1-2", "message_data": {"sender_id": "2", "recipient_id": "1", "text": "yo"}}},
            ],
            "users": {"2": {"screen_name": "them"}},
        }
    }
    messages = dm_messages(payload)
    assert len(messages) == 1
    assert messages[0]["text"] == "yo"
    assert messages[0]["sender_username"] == "them"
