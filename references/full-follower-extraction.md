# Full follower extraction

## First: use the tool

`get_followers(handle, limit=N)` no longer caps at 100. It walks X's cursor
internally and stops at whichever comes first: `N` items, or a time budget.

```python
page = get_followers("somehandle", limit=1000)
# {"users": [...], "count": 1000, "truncated": False, "total_available": 48211}
```

- `count == limit` and `truncated == False` → you got what you asked for.
- `truncated == True` → the budget ran out; call again or lower the ambition.
- `total_available` is the profile's own follower count, so you can report
  coverage honestly ("1,000 of 48,211") instead of implying a full scan.

Same contract for `get_following`. `get_verified_followers` is the cheap
shortcut when "who matters here" beats "everyone here".

## When the tool is not enough

Only reach for a script when you need **every** follower of a large account
(tens of thousands), or a resumable scan across sessions. Then drive twscrape
directly against the same account DB.

Rules that save an hour of debugging:

- Run inside Spectre's environment: `uvx --from spectre-mcp python collect.py`.
  System python's twscrape fails its transaction-id bootstrap and
  `user_by_login()` silently returns `None`.
- `AccountsPool("~/.spectre/accounts.db")` → `API(pool, proxy=None)`; cookies
  come from the pool, nothing to pass.
- `api.followers(user.id, limit=N)` is an async generator that paginates
  internally.
- `AccountsPool` has no `close()` — don't call it.
- Write each page to disk as you go. A 40k-follower walk will outlive one
  process.

```python
import asyncio, json, os
from twscrape import API, AccountsPool

DB = os.path.expanduser("~/.spectre/accounts.db")

async def collect(handle: str, out_path: str, cap: int = 100_000):
    api = API(AccountsPool(DB))
    user = await api.user_by_login(handle)
    if not user:
        raise SystemExit(f"could not resolve @{handle}")
    print(f"@{user.username}: {user.followersCount} followers on record", flush=True)
    seen, rows = set(), []
    with open(out_path, "w") as fh:
        async for u in api.followers(user.id, limit=min(cap, user.followersCount or cap)):
            if u.id in seen:
                continue
            seen.add(u.id)
            row = {
                "id": u.id,
                "username": u.username,
                "display_name": u.displayname,
                "bio": getattr(u, "rawDescription", None) or "",
                "followers": u.followersCount or 0,
                "following": u.friendsCount or 0,
                "tweets": u.statusesCount or 0,
                "blue": getattr(u, "blue", False),
            }
            rows.append(row)
            fh.write(json.dumps(row) + "\n")
            if len(rows) % 200 == 0:
                fh.flush()
                print(f"  {len(rows)}…", flush=True)
    print(f"done: {len(rows)} of {user.followersCount}")

asyncio.run(collect("somehandle", "followers.jsonl"))
```

## Accuracy caveat

Full pulls land slightly under `followersCount`: suspended accounts vanish
mid-pagination, and people follow/unfollow while you walk. A 1% shortfall is
normal. Report it — "collected 39,412 of 39,600" — rather than claiming 100%.

## Sorting and filtering

- Top-N by audience: `sorted(rows, key=lambda r: r["followers"], reverse=True)[:50]`
- Keyword match on `username + display_name + bio`, case-folded.
- Short tokens (`ai`, `ml`, `x`) need word boundaries (`\b`), or they match
  "again", "email", "said". Longer terms (`llm`, `gpt`, `openai`, `agent`,
  `neural`) are safe as substrings. `re.escape` anything user-supplied.
