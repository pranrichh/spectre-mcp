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


UPSTREAM = "https://raw.githubusercontent.com/fa0311/TwitterInternalAPIDocument/master/docs/json/GraphQL.json"


def load_dump(path: str | None):
    if path:
        with open(path) as fh:
            return json.load(fh)
    import urllib.request

    print(f"fetching {UPSTREAM}")
    with urllib.request.urlopen(UPSTREAM, timeout=60) as resp:
        return json.load(resp)


def build(dump) -> tuple[list[str], dict[str, dict], list[str]]:
    """Turn a bundle dump into (ops.py lines, per-op specs, missing names)."""
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

    sets: dict[str, dict] = {}
    order: list[str] = []
    for name in OPS_USED:
        spec = bundle.get(name)
        feats = spec["features"] if spec else {}
        key = json.dumps(feats, sort_keys=True)
        if key not in sets:
            sets[key] = feats
            order.append(key)
    set_name = {k: (None if not sets[k] else f"FEATURES_{i}") for i, k in enumerate(order)}

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
    body: list[str] = []
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

    missing: list[str] = []
    specs: dict[str, dict] = {}
    for name, method in OPS_USED.items():
        spec = bundle.get(name)
        qid = spec["query_id"] if spec else None
        if not qid and name in resolved and resolved[name].get("chosen"):
            qid = resolved[name]["chosen"]["qid"]
        if not qid:
            qid = FALLBACK.get(name)
        if not qid:
            missing.append(name)
            continue
        feats = spec["features"] if spec else {}
        toggles = spec["field_toggles"] if spec else []
        specs[name] = {"query_id": qid, "features": feats, "field_toggles": toggles}
        fname = set_name.get(json.dumps(feats, sort_keys=True)) or "{}"
        body.append(f'    "{name}": ("{qid}", "{method.lower()}", {fname}, {toggles!r}),')
    body.append("}")
    body.append("")
    return header + body, specs, missing


def main():
    check_only = "--check" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dump = load_dump(args[0] if args else None)
    lines, specs, missing = build(dump)

    out = os.path.join(REPO, "src", "spectre", "ops.py")
    if check_only:
        sys.path.insert(0, os.path.join(REPO, "src"))
        from spectre.ops import OPS

        stale = [n for n, s in specs.items() if n in OPS and OPS[n][0] != s["query_id"]]
        absent = [n for n in specs if n not in OPS]
        if stale or absent:
            print(f"ops.py is stale: {len(stale)} changed, {len(absent)} missing")
            for n in stale[:10]:
                print(f"  {n}: {OPS[n][0]} -> {specs[n]['query_id']}")
            raise SystemExit(1)
        print(f"ops.py is current ({len(OPS)} operations)")
        return

    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {out}: {len(specs)} ops")
    if missing:
        print("MISSING (add a FALLBACK id):", missing)


if __name__ == "__main__":
    main()
