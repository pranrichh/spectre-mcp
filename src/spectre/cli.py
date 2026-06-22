"""Spectre CLI — account management and server startup.

Usage:
    spectre add <username> <cookies>     Add account via browser cookies
    spectre remove <username>            Remove an account
    spectre list                         List all accounts
    spectre status                       Pool health check
    spectre serve                        Start MCP server (default)
    spectre help                         Show this help
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import sys

# Silence twscrape's noisy INFO logs (migrations, account pool internals)
logging.getLogger("twscrape").setLevel(logging.WARNING)


def _get_db_path() -> str:
    return os.environ.get("SPECTRE_DB", os.path.join(os.path.expanduser("~"), ".spectre", "accounts.db"))


def _ensure_dir():
    os.makedirs(os.path.dirname(_get_db_path()), exist_ok=True)


async def _add(username: str, cookies: str) -> None:
    """Add an account using browser cookies."""
    _ensure_dir()
    from twscrape.accounts_pool import AccountsPool
    pool = AccountsPool(_get_db_path())
    await pool.add_account_cookies(username, cookies)
    print(f"✓ Account @{username} added to pool.")


async def _remove(username: str) -> None:
    """Remove an account."""
    from twscrape.accounts_pool import AccountsPool
    pool = AccountsPool(_get_db_path())
    try:
        await pool.delete_accounts([username])
        print(f"✓ Account @{username} removed.")
    except Exception as e:
        print(f"✗ Failed to remove @{username}: {e}")
        sys.exit(1)


async def _list() -> None:
    """List all accounts."""
    from twscrape.accounts_pool import AccountsPool
    pool = AccountsPool(_get_db_path())
    accounts = await pool.get_all()
    if not accounts:
        print("No accounts in pool. Add one with: spectre add <username> \"auth_token=xxx; ct0=yyy\"")
        return
    print(f"{'Username':<20} {'State':<10} {'Error'}")
    print("-" * 60)
    for acc in accounts:
        if acc.active and not acc.error_msg:
            state = "active"
        elif acc.error_msg:
            state = "error"
        else:
            state = "locked"
        error = acc.error_msg or ""
        print(f"@{acc.username:<19} {state:<10} {error}")


async def _status() -> None:
    """Pool health check."""
    from twscrape.accounts_pool import AccountsPool
    pool = AccountsPool(_get_db_path())
    accounts = await pool.get_all()
    active = sum(1 for a in accounts if a.active and not a.error_msg)
    error = sum(1 for a in accounts if a.error_msg)
    locked = len(accounts) - active - error
    print(f"Pool: {len(accounts)} total, {active} active, {locked} locked, {error} error")
    if not accounts:
        print("Add an account: spectre add <username> \"auth_token=xxx; ct0=yyy\"")


def main():
    """Spectre CLI entry point."""
    args = sys.argv[1:]

    if not args or args[0] in ("serve", "mcp"):
        # Default: start MCP server
        from spectre.server import mcp
        mcp.run()
        return

    cmd = args[0]

    if cmd == "help" or cmd == "--help" or cmd == "-h":
        print(__doc__.strip())
        return

    if cmd == "add":
        if len(args) < 3:
            print("Usage: spectre add <username> \"auth_token=xxx; ct0=yyy\"")
            print("\nGet cookies from: Browser DevTools → Application → Cookies → x.com")
            print("  1. Log into x.com in your browser")
            print("  2. Open DevTools (F12) → Application → Cookies → https://x.com")
            print("  3. Copy auth_token and ct0 values")
            print("  4. Run: spectre add myaccount \"auth_token=YOUR_TOKEN; ct0=YOUR_CT0\"")
            sys.exit(1)
        asyncio.run(_add(args[1], args[2]))
        return

    if cmd == "remove":
        if len(args) < 2:
            print("Usage: spectre remove <username>")
            sys.exit(1)
        asyncio.run(_remove(args[1]))
        return

    if cmd == "list":
        asyncio.run(_list())
        return

    if cmd == "status":
        asyncio.run(_status())
        return

    print(f"Unknown command: {cmd}")
    print("Run 'spectre help' for usage.")
    sys.exit(1)


if __name__ == "__main__":
    main()
