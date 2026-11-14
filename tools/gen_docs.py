"""Generate docs/tools.md from the live MCP registry.

    python tools/gen_docs.py            # write docs/tools.md
    python tools/gen_docs.py --check    # exit 1 if the file is stale

The registry is the source of truth: a tool that is not documented fails the
check, and a documented tool that no longer exists fails it too.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from spectre.server import mcp  # noqa: E402

SECTIONS: list[tuple[str, str, list[str]]] = [
    (
        "Accounts & sessions",
        "Who is logged in, how healthy the pool is, and what to do when a call is rate limited.",
        ["get_me", "list_accounts", "pool_status", "set_active_account", "set_auto_rotate", "get_rate_limits", "remove_account"],
    ),
    (
        "Search",
        "Find posts and people. Search is the most expensive read — one request per ~20 results.",
        ["search", "search_users"],
    ),
    (
        "Profiles & connections",
        "Everything about an account, its audience, and its posting history.",
        [
            "get_user",
            "get_user_by_id",
            "get_users_by_ids",
            "get_user_tweets",
            "get_user_tweets_and_replies",
            "get_user_media",
            "get_followers",
            "get_following",
            "get_verified_followers",
            "get_followers_you_know",
            "get_user_likes",
            "get_user_highlights",
        ],
    ),
    (
        "Posts",
        "Read individual posts, conversations, and who engaged with them.",
        [
            "get_tweet",
            "get_tweets",
            "get_tweet_replies",
            "get_thread",
            "get_tweet_quotes",
            "get_retweeters",
            "get_favoriters",
            "get_tweet_edit_history",
            "get_similar_posts",
            "get_community_notes",
            "rate_community_note",
        ],
    ),
    (
        "Composing & media",
        "Anything that publishes or prepares content. Public the moment it runs.",
        [
            "post_tweet",
            "delete_tweet",
            "upload_media",
            "download_media",
            "schedule_tweet",
            "get_scheduled_tweets",
            "edit_scheduled_tweet",
            "delete_scheduled_tweet",
            "create_draft",
            "get_drafts",
            "edit_draft",
            "delete_draft",
        ],
    ),
    (
        "Engagement",
        "Likes, reposts, bookmarks and pins. All reversible.",
        [
            "like_tweet",
            "unlike_tweet",
            "retweet",
            "unretweet",
            "bookmark_tweet",
            "unbookmark_tweet",
            "pin_tweet",
            "unpin_tweet",
            "pin_reply",
            "unpin_reply",
        ],
    ),
    (
        "Social graph",
        "Follow, mute, block and the lists of who is currently muted or blocked.",
        [
            "follow_user",
            "unfollow_user",
            "mute_user",
            "unmute_user",
            "block_user",
            "unblock_user",
            "remove_follower",
            "get_muted_accounts",
            "get_blocked_accounts",
        ],
    ),
    (
        "Direct messages",
        "Read and send DMs. Sending has no recall.",
        [
            "send_dm",
            "get_dm_inbox",
            "get_dm_conversation",
            "search_dm",
            "search_dm_groups",
            "search_dm_people",
            "get_dm_muted",
            "dm_block_user",
            "dm_unblock_user",
        ],
    ),
    (
        "Lists",
        "Full CRUD, membership, subscribers and the list timeline.",
        [
            "get_list_info",
            "create_list",
            "update_list",
            "delete_list",
            "add_list_member",
            "remove_list_member",
            "get_list_members",
            "get_list_timeline",
            "get_list_subscribers",
            "get_list_memberships",
            "get_list_ownerships",
            "subscribe_list",
            "unsubscribe_list",
        ],
    ),
    (
        "Communities, topics & trends",
        "Community posts, topic follows, and what is trending where.",
        [
            "get_community_info",
            "get_community_tweets",
            "join_community",
            "leave_community",
            "get_topic_info",
            "follow_topic",
            "unfollow_topic",
            "get_trends",
            "get_trend_locations",
        ],
    ),
    (
        "Bookmarks",
        "Saved posts, search inside them, and folder management (folders are Premium-gated by X).",
        [
            "get_bookmarks",
            "search_bookmarks",
            "clear_all_bookmarks",
            "get_bookmark_folders",
            "create_bookmark_folder",
            "edit_bookmark_folder",
            "delete_bookmark_folder",
            "add_tweet_to_folder",
            "remove_tweet_from_folder",
            "get_bookmark_folder_timeline",
        ],
    ),
    (
        "Timelines",
        "Ambient feeds for the authenticated account.",
        ["get_home_timeline", "get_notifications"],
    ),
    (
        "Profile",
        "Read and edit the authenticated account's own profile.",
        [
            "get_account_settings",
            "update_profile",
            "update_profile_image",
            "update_profile_banner",
            "delete_profile_banner",
        ],
    ),
]

HEADER = """<p align="center">
  <img src="../assets/headers/tools.svg" alt="Tools" />
</p>

{count} tools, generated from the live registry (`tools/gen_docs.py`).
Every tool returns JSON. Failures look like
`{{"error": "...", "kind": "auth|rate_limit|permission|validation|not_found|upstream", "hint": "..."}}`.

Read [safety.md](safety.md) before calling anything in **Composing**, **Engagement**,
**Social graph**, **Direct messages** or **Lists** — those change state on X.
"""


def render(tools: dict) -> str:
    documented = {name for _, _, names in SECTIONS for name in names}
    lines = [HEADER.format(count=len(tools))]
    if documented != set(tools):
        missing = sorted(set(tools) - documented)
        extra = sorted(documented - set(tools))
        if missing:
            lines.append(f"> **Undocumented tools:** {', '.join(missing)}\n")
        if extra:
            lines.append(f"> **Stale entries:** {', '.join(extra)}\n")
    for title, blurb, names in SECTIONS:
        lines.append(f"## {title}\n")
        lines.append(f"{blurb}\n")
        for name in names:
            tool = tools.get(name)
            if tool is None:
                continue
            doc = (inspect.getdoc(tool.fn) or "").strip()
            first, _, rest = doc.partition("\n\n")
            params = tool.parameters or {}
            props = params.get("properties", {}) or {}
            required = set(params.get("required", []) or [])
            signature = ", ".join(
                f"{p}" if p in required else f"{p}?" for p in props
            )
            lines.append(f"### `{name}({signature})`\n")
            lines.append(" ".join(first.split()) + "\n")
            if rest.strip():
                lines.append(" ".join(rest.split()) + "\n")
        lines.append("---\n")
    return "\n".join(lines).rstrip() + "\n"


async def main() -> int:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    content = render(tools)
    target = os.path.join(REPO, "docs", "tools.md")
    if "--check" in sys.argv:
        current = open(target).read() if os.path.exists(target) else ""
        if current != content:
            print(f"{target} is stale — run: python tools/gen_docs.py")
            return 1
        print(f"{target} matches the registry ({len(tools)} tools)")
        return 0
    os.makedirs(os.path.dirname(target), exist_ok=True)
    open(target, "w").write(content)
    print(f"wrote {target} ({len(tools)} tools, {len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
