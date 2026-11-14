"""Spectre CLI — account management, health checks, server startup.

    spectre add <name> "<auth_token=...; ct0=...>"   verify + add an account
    spectre remove <name>                            drop an account
    spectre list                                     list accounts
    spectre status                                   pool health
    spectre rename <old> <new>                       change an account's local label
    spectre doctor                                   check query ids + auth
    spectre serve                                    start the MCP server (default)
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys

from spectre import __version__

RESET, DIM, BOLD = "\033[0m", "\033[2m", "\033[1m"
GREEN, RED, YELLOW = "\033[32m", "\033[31m", "\033[33m"


def _db_path() -> str:
    return os.environ.get("SPECTRE_DB", os.path.join(os.path.expanduser("~"), ".spectre", "accounts.db"))


def _ensure_dir() -> None:
    directory = os.path.dirname(_db_path())
    if directory:
        os.makedirs(directory, exist_ok=True)


def _ok(message: str) -> str:
    return f"{GREEN}✓{RESET} {message}"


def _err(message: str) -> str:
    return f"{RED}✗{RESET} {message}"


def _warn(message: str) -> str:
    return f"{YELLOW}!{RESET} {message}"


def _parse_cookies(raw: str) -> dict[str, str]:
    """Parse 'a=1; b=2' (or a JSON object) into a cookie dict."""
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            return {k: str(v) for k, v in json.loads(raw).items()}
        except json.JSONDecodeError:
            pass
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            name, _, value = part.partition("=")
            cookies[name.strip()] = value.strip()
    return cookies


def _validate_cookies(cookies: dict[str, str]) -> list[str]:
    problems = []
    if not cookies.get("auth_token"):
        problems.append("auth_token is missing")
    elif len(cookies["auth_token"]) < 20:
        problems.append("auth_token looks truncated")
    ct0 = cookies.get("ct0", "")
    if not ct0:
        problems.append("ct0 is missing")
    elif len(ct0) != 160:
        problems.append(f"ct0 is {len(ct0)} chars, expected 160 — copy the full value")
    return problems


async def _verify(cookies: dict[str, str]) -> tuple[str | None, str | None]:
    """Ask X who these cookies belong to. -> (handle, error)."""
    import httpx

    from spectre.ops import OPS
    from spectre.xclient import BEARER, GQL

    query_id, _method, features, toggles = OPS["Viewer"]
    headers = {
        "authorization": f"Bearer {BEARER}",
        "x-csrf-token": cookies.get("ct0", ""),
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "content-type": "application/json",
    }
    jar = httpx.Cookies()
    for domain in (".x.com", ".twitter.com"):
        jar.set("auth_token", cookies.get("auth_token", ""), domain=domain)
        jar.set("ct0", cookies.get("ct0", ""), domain=domain)
    try:
        async with httpx.AsyncClient(headers=headers, cookies=jar, timeout=25, follow_redirects=True) as client:
            resp = await client.get(
                f"{GQL}/{query_id}/Viewer",
                params={"variables": "{}", "features": json.dumps(features), "fieldToggles": json.dumps({t: False for t in toggles})},
            )
        if resp.status_code in (401, 403):
            return None, f"X rejected these cookies (HTTP {resp.status_code}) — sign in again and recopy them"
        payload = resp.json()
        result = (((payload.get("data") or {}).get("viewer") or {}).get("user_results") or {}).get("result") or {}
        handle = ((result.get("core") or {}).get("screen_name")) or ((result.get("legacy") or {}).get("screen_name"))
        if handle:
            return handle, None
        errors = payload.get("errors") or []
        return None, errors[0].get("message") if errors else "X returned no account for these cookies"
    except httpx.HTTPError as exc:
        return None, f"network error: {exc}"


async def _add(raw_name: str, raw_cookies: str) -> int:
    _ensure_dir()
    cookies = _parse_cookies(raw_cookies)
    problems = _validate_cookies(cookies)
    if problems:
        print(_err("These cookies will not work:"))
        for problem in problems:
            print(f"   · {problem}")
        print(f"\n{DIM}Open x.com → DevTools (F12) → Application → Cookies → https://x.com{RESET}")
        return 1

    handle, error = await _verify(cookies)
    if error or not handle:
        print(_err(error or "X did not return an account for these cookies"))
        print(f"{DIM}Not added. Fix the cookies and try again.{RESET}")
        return 1

    from twscrape.accounts_pool import AccountsPool

    pool = AccountsPool(_db_path())
    existing = {a.username.lower() for a in await pool.get_all()}
    if handle.lower() in existing:
        print(_warn(f"@{handle} is already in the pool — replacing its cookies."))
        await pool.delete_accounts([handle])
    cookie_string = "; ".join(f"{k}={v}" for k, v in cookies.items())
    await pool.add_account_cookies(handle, cookie_string)
    await pool.set_active(handle, True)

    print(_ok(f"@{handle} added and verified."))
    if raw_name.lstrip("@").lower() != handle.lower():
        print(f"   {DIM}Saved under the handle (@{handle}).{RESET}")
    print(f"   {DIM}Pool: {len(existing) + (0 if handle.lower() in existing else 1)} account(s) · {_db_path()}{RESET}")
    return 0


async def _remove(username: str) -> int:
    from twscrape.accounts_pool import AccountsPool

    pool = AccountsPool(_db_path())
    accounts = await pool.get_all()
    match = next((a for a in accounts if a.username.lower() == username.lstrip("@").lower()), None)
    if not match:
        print(_err(f"@{username} is not in the pool."))
        if accounts:
            print(f"   {DIM}Known accounts: {', '.join('@' + a.username for a in accounts)}{RESET}")
        return 1
    await pool.delete_accounts([match.username])
    print(_ok(f"@{match.username} removed."))
    return 0


async def _rename(old: str, new: str) -> int:
    """Change the label the pool uses for an account. Local only."""
    from twscrape.accounts_pool import AccountsPool

    pool = AccountsPool(_db_path())
    accounts = await pool.get_all()
    old = old.lstrip("@")
    match = next((a for a in accounts if a.username.lower() == old.lower()), None)
    if not match:
        print(_err(f"@{old} is not in the pool."))
        return 1
    new = new.lstrip("@")
    if any(a.username.lower() == new.lower() for a in accounts):
        print(_err(f"@{new} is already in the pool."))
        return 1
    try:
        conn = sqlite3.connect(_db_path())
        conn.execute("UPDATE accounts SET username = ? WHERE username = ?", (new, match.username))
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        print(_err(f"Could not rename @{match.username}: {exc}"))
        return 1
    print(_ok(f"@{match.username} is now labelled @{new}."))
    print(f"   {DIM}Local label only — the X account and its cookies are untouched.{RESET}")
    return 0


async def _list() -> int:
    from twscrape.accounts_pool import AccountsPool

    pool = AccountsPool(_db_path())
    accounts = await pool.get_all()
    if not accounts:
        print("No accounts yet.\n  " + DIM + 'spectre add <name> "auth_token=...; ct0=..."' + RESET)
        return 0
    width = max(len(a.username) for a in accounts) + 2
    print(f"\n{BOLD}{'ACCOUNT':<{width}}{'STATE':<10}LAST USED{RESET}")
    for account in accounts:
        state = "active" if (account.active and not account.error_msg) else ("error" if account.error_msg else "locked")
        colour = GREEN if state == "active" else (RED if state == "error" else YELLOW)
        last = str(account.last_used or "-")[:19]
        print(f"{'@' + account.username:<{width}}{colour}{state:<10}{RESET}{last}", end="")
        if account.error_msg:
            print(f"  {DIM}{account.error_msg}{RESET}")
        else:
            print()
    print()
    return 0


async def _status() -> int:
    from twscrape.accounts_pool import AccountsPool

    pool = AccountsPool(_db_path())
    accounts = await pool.get_all()
    active = sum(1 for a in accounts if a.active and not a.error_msg)
    errored = sum(1 for a in accounts if a.error_msg)
    locked = len(accounts) - active - errored
    print(f"{BOLD}Pool{RESET}  {len(accounts)} total · {GREEN}{active} active{RESET} · {YELLOW}{locked} locked{RESET} · {RED}{errored} error{RESET}")
    if not accounts:
        print('  add one: spectre add <name> "auth_token=...; ct0=..."')
    return 0 if active else 1


async def _doctor() -> int:
    """Check auth, the read paths and the operation table this build depends on."""
    from twscrape.accounts_pool import AccountsPool

    from spectre import opsync
    from spectre.scraper import Scraper
    from spectre.writer import Writer
    from spectre.xclient import XClient

    _ensure_dir()
    pool = AccountsPool(_db_path())
    accounts = await pool.get_all()
    print(f"{BOLD}spectre doctor{RESET}  v{__version__}")
    print(f"{DIM}db      {_db_path()}{RESET}")
    if not accounts:
        print(_err('no accounts - run: spectre add <name> "auth_token=...; ct0=..."'))
        return 1
    print(f"{DIM}pool    {len(accounts)} account(s): {', '.join('@' + a.username for a in accounts)}{RESET}")

    # Refresh X's GraphQL query ids before testing anything that depends on them.
    if "--no-update" not in sys.argv:
        try:
            result = await opsync.update()
            if result["changed"]:
                print(_ok(f"ops     {result['refreshed']} operations checked, {len(result['changed'])} ids updated"))
            else:
                print(_ok(f"ops     {result['refreshed']} operations up to date"))
            if result["missing"]:
                known = {"useSendMessageMutation"}
                unexplained = [n for n in result["missing"] if n not in known]
                if unexplained:
                    print(_warn(f"ops     {len(unexplained)} operation(s) missing upstream: {', '.join(unexplained[:3])}"))
                else:
                    print(f"{DIM}ops     DM send uses a built-in id (not published in X's bundles){RESET}")
        except Exception as exc:  # noqa: BLE001 - offline is not a failure
            print(_warn(f"ops     could not refresh query ids ({type(exc).__name__}); using the built-in table"))
    else:
        saved = opsync.status()
        detail = f" (refreshed {saved['generated_at']})" if saved and saved.get("generated_at") else ""
        print(_ok(f"ops     built-in table{detail}"))

    client = XClient(pool, proxy=os.environ.get("SPECTRE_PROXY"))
    writer = Writer(client)
    scraper = Scraper(pool, default_budget=15)

    # Verify every account against its own cookies: comparing them all to one
    # identity would flag perfectly good secondary accounts as stale.
    healthy = 0
    for acc in accounts:
        identity = await writer.me(account=acc.username)
        if not isinstance(identity, dict) or identity.get("error"):
            print(_err(f"auth    @{acc.username}: {identity.get('error') if isinstance(identity, dict) else identity}"))
            continue
        healthy += 1
        if identity["username"].lower() == acc.username.lower():
            print(_ok(f"auth    @{acc.username} ({identity['id']})"))
        else:
            # The pool label is local; a difference is fine and nothing to fix.
            print(_ok(f"auth    @{acc.username} ({identity['id']}) -> @{identity['username']} on X"))
    if not healthy:
        return 1
    me = await writer.me()

    profile = await scraper.user(me["username"])
    if isinstance(profile, dict) and profile.get("error"):
        print(_err(f"profile {profile['error']}"))
    else:
        print(_ok("profile ok"))

    timeline = await client.graphql(
        "HomeTimeline", {"count": 1, "includePromotedContent": True, "latestControlAvailable": True, "requestContext": "launch"}
    )
    if isinstance(timeline, dict) and timeline.get("error"):
        print(_err(f"timeline {timeline['error']}"))
    else:
        print(_ok("timeline ok"))

    try:
        results = await scraper.search("x", limit=1)
        print(_ok("search  ok") if results else _warn("search  returned no results"))
    except Exception as exc:  # noqa: BLE001 - doctor reports, never raises
        print(_warn(f"search  {exc}"))

    print(f"{DIM}ops     {len(client.ops)} operations loaded - override any with SPECTRE_OP_<NAME>{RESET}")
    await client.aclose()
    print(_ok("done"))
    return 0


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("--version", "-v", "version"):
        print(f"spectre-mcp {__version__}")
        return

    command = args[0] if args else "serve"

    if command in ("serve", "mcp"):
        from spectre.server import mcp

        mcp.run()
        return

    if command in ("help", "--help", "-h"):
        print(__doc__.strip())
        return

    handlers = {
        "add": lambda: _add(args[1], " ".join(args[2:])) if len(args) >= 3 else _usage("spectre add <name> \"auth_token=...; ct0=...\""),
        "remove": lambda: _remove(args[1]) if len(args) >= 2 else _usage("spectre remove <name>"),
        "rename": lambda: _rename(args[1], args[2]) if len(args) >= 3 else _usage("spectre rename <old> <new>"),
        "list": _list,
        "status": _status,
        "doctor": _doctor,
    }
    if command not in handlers:
        print(_err(f"unknown command: {command}"))
        print(__doc__.strip())
        sys.exit(1)
    sys.exit(asyncio.run(handlers[command]()) or 0)


def _usage(line: str) -> int:
    print(f"usage: {line}")
    return 1


if __name__ == "__main__":
    main()
