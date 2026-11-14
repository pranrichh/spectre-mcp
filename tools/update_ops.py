"""Generate src/spectre/ops.py from X's current GraphQL bundle dump.

Source of truth: https://github.com/fa0311/TwitterInternalAPIDocument
(docs/json/GraphQL.json — extracted from X's live JS bundles), cross-checked
against twscrape's shipped operation IDs and verified live against api.x.com.

Run:  python tools/update_ops.py /path/to/GraphQL.json
"""
from __future__ import annotations
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
resolved_path = os.path.join(REPO, ".work", "ops_resolved.json")

# op name -> (method, tier)  tier: "verified" = confirmed live in this repo's test run
OPS_USED = {
    # ── reads ──
    "TweetDetail": "GET",
    "TweetResultByRestId": "GET",
    "TweetResultsByRestIds": "GET",
    "Viewer": "GET",
    "UserByScreenName": "GET",
    "UserByRestId": "GET",
    "UserTweets": "GET",
    "UserTweetsAndReplies": "GET",
    "UserMedia": "GET",
    "UserArticlesTweets": "GET",
    "UserHighlightsTweets": "GET",
    "Likes": "GET",
    "Followers": "GET",
    "Following": "GET",
    "BlueVerifiedFollowers": "GET",
    "FollowersYouKnow": "GET",
    "SearchTimeline": "GET",
    "HomeTimeline": "GET",
    "HomeLatestTimeline": "GET",
    "Bookmarks": "GET",
    "BookmarkSearchTimeline": "GET",
    "BookmarkFolderTimeline": "GET",
    "BookmarkFoldersSlice": "POST",
    "ListByRestId": "GET",
    "ListLatestTweetsTimeline": "GET",
    "ListMembers": "GET",
    "ListMemberships": "GET",
    "ListOwnerships": "GET",
    "ListSubscribers": "GET",
    "CommunityByRestId": "GET",
    "CommunityQuery": "GET",
    "CommunityTweetsTimeline": "GET",
    "CommunitiesMembershipsTimeline": "GET",
    "TopicByRestId": "GET",
    "MutedAccounts": "GET",
    "BlockedAccountsAll": "GET",
    "NotificationsTimeline": "GET",
    "Favoriters": "GET",
    "Retweeters": "GET",
    "SimilarPosts": "GET",
    "TweetEditHistory": "GET",
    "BirdwatchFetchNotes": "GET",
    "DmAllSearchSlice": "GET",
    "DmGroupSearchSlice": "GET",
    "DmPeopleSearchSlice": "GET",
    "DmMutedTimeline": "GET",
    # ── writes ──
    "CreateTweet": "POST",
    "DeleteTweet": "POST",
    "FavoriteTweet": "POST",
    "UnfavoriteTweet": "POST",
    "CreateRetweet": "POST",
    "DeleteRetweet": "POST",
    "BookmarkAdd": "POST",
    "BookmarkDelete": "POST",
    "BookmarksAllDelete": "POST",
    "CreateScheduledTweet": "POST",
    "FetchScheduledTweets": "POST",
    "DeleteScheduledTweet": "POST",
    "EditScheduledTweet": "POST",
    "CreateDraftTweet": "POST",
    "FetchDraftTweets": "POST",
    "DeleteDraftTweet": "POST",
    "EditDraftTweet": "POST",
    "CreateList": "POST",
    "UpdateList": "POST",
    "DeleteList": "POST",
    "ListAddMember": "POST",
    "ListRemoveMember": "POST",
    "ListSubscribe": "POST",
    "ListUnsubscribe": "POST",
    "JoinCommunity": "POST",
    "LeaveCommunity": "POST",
    "PinTweet": "POST",
    "UnpinTweet": "POST",
    "PinReply": "POST",
    "UnpinReply": "POST",
    "RemoveFollower": "POST",
    "CreateHighlight": "POST",
    "DeleteHighlight": "POST",
    "TopicFollow": "POST",
    "TopicUnfollow": "POST",
    "createBookmarkFolder": "POST",
    "DeleteBookmarkFolder": "POST",
    "EditBookmarkFolder": "POST",
    "bookmarkTweetToFolder": "POST",
    "RemoveTweetFromBookmarkFolder": "POST",
    "dmBlockUser": "POST",
    "dmUnblockUser": "POST",
    "BirdwatchCreateRating": "POST",
    "useSendMessageMutation": "POST",
    # ── not in the public bundle but confirmed live (DM + misc) ──
}

# Fallback ids for operations that no longer appear in the bundle dump.
FALLBACK = {
    "useSendMessageMutation": "MaxK2PKX1F9Z-9SwqwavTw",
}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/gql.json"
    dump = json.load(open(src))
    bundle = {}
    for item in dump:
        e = item.get("exports", {})
        name = e.get("operationName")
        if not name:
            continue
        md = e.get("metadata") or {}
        fs = md.get("featureSwitch") or {}
        bundle[name] = {
            "query_id": e.get("queryId"),
            "features": {k: (str(v.get("value", "true")).lower() == "true") for k, v in fs.items()},
            "field_toggles": md.get("fieldToggles") or [],
        }

    resolved = json.load(open(resolved_path)) if os.path.exists(resolved_path) else {}

    # Deduplicate feature sets: X ships 3-4 distinct bundles (timeline, tweet, mutation...)
    sets: dict[str, dict] = {}
    order: list[str] = []
    for name, method in OPS_USED.items():
        spec = bundle.get(name)
        feats = spec["features"] if spec else {}
        key = json.dumps(feats, sort_keys=True)
        if key not in sets:
            sets[key] = feats
            order.append(key)
    set_name = {}
    for i, key in enumerate(order):
        if not sets[key]:
            set_name[key] = None
            continue
        set_name[key] = f"FEATURES_{i}"

    header = [
        '"""X/Twitter internal GraphQL operations — query IDs, features, field toggles.',
        "",
        "GENERATED FILE. Do not edit by hand; refresh it with `spectre doctor --update`.",
        "",
        "Source: fa0311/TwitterInternalAPIDocument (GraphQL.json), extracted from X's live",
        "JS bundles, then verified against api.x.com. Query IDs rotate every few weeks;",
        "`spectre doctor --update` refreshes them, and SPECTRE_OP_<NAME> overrides one entry.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    body = []
    for key in order:
        nm = set_name[key]
        if not nm:
            continue
        body.append(f"{nm}: dict[str, bool] = {{")
        for k, v in sets[key].items():
            body.append(f'    "{k}": {v},')
        body.append("}")
        body.append("")
    body.append("# name -> (query_id, http_method, features, field_toggles)")
    body.append("OPS: dict[str, tuple[str, str, dict[str, bool], list[str]]] = {")
    missing = []
    for name, method in OPS_USED.items():
        spec = bundle.get(name)
        qid = None
        if name in resolved and resolved[name].get("chosen"):
            qid = resolved[name]["chosen"]["qid"]
        if not qid and spec:
            qid = spec["query_id"]
        if not qid:
            qid = FALLBACK.get(name)
        if not qid:
            missing.append(name)
            continue
        feats = spec["features"] if spec else {}
        toggles = spec["field_toggles"] if spec else []
        fname = set_name.get(json.dumps(feats, sort_keys=True)) or "{}"
        body.append(f'    "{name}": ("{qid}", "{method.lower()}", {fname}, {toggles!r}),')
    body.append("}")
    body.append("")
    lines = header + body
    out = os.path.join(REPO, "src", "spectre", "ops.py")
    open(out, "w").write("\n".join(lines) + "\n")
    print(f"wrote {out}: {len(OPS_USED) - len(missing)} ops")
    if missing:
        print("MISSING (add a FALLBACK id):", missing)


if __name__ == "__main__":
    main()
