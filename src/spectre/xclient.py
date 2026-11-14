"""Authenticated HTTP transport for X.

One place that knows how to: pick an account, build cookie/header state, mint
`x-client-transaction-id`, retry a stale query id, fail over to another account
on a rate limit or dead cookie, and turn every failure into an `XError`.

Accounts are tried in this order: explicitly preferred -> least recently used.
A 429 or an auth error parks that account (twscrape's own lock table) and moves
to the next one, so "automatic rotation" is real rather than advertised.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

import httpx
from loguru import logger

from spectre.errors import XError, from_x_error, rate_limit_error
from spectre.ops import OPS

# X's public web bearer token — embedded in every browser session, not a secret.
BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
GQL = "https://x.com/i/api/graphql"
REST = "https://x.com/i/api/1.1"
UA_DEFAULT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _cookies(acc) -> dict[str, str]:
    cookies = acc.cookies
    if isinstance(cookies, str):
        try:
            cookies = json.loads(cookies)
        except json.JSONDecodeError:
            cookies = {}
    return cookies or {}


class XClient:
    """Shared authenticated transport with pool-wide account rotation."""

    def __init__(self, pool, proxy: Optional[str] = None):
        self.pool = pool
        self.proxy = proxy
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._preferred: Optional[str] = None
        self._auto_rotate = True
        self.last_headers: dict[str, dict] = {}

    # ── configuration ──

    def set_preferred_account(self, username: Optional[str]) -> None:
        self._preferred = username

    def set_auto_rotate(self, enabled: bool) -> None:
        self._auto_rotate = enabled

    @property
    def preferred_account(self) -> Optional[str]:
        return self._preferred

    # ── account selection ──

    async def _accounts(self) -> list:
        accounts = await self.pool.get_all()
        if not accounts:
            raise XError(
                "No accounts in the pool.",
                kind="auth",
                hint='Add one: spectre add <name> "auth_token=...; ct0=..."',
            )
        usable = [a for a in accounts if a.active and not a.error_msg]
        if not usable:
            detail = "; ".join(f"@{a.username}: {a.error_msg or 'inactive'}" for a in accounts)
            raise XError(
                f"No usable accounts ({detail}).",
                kind="auth",
                hint='Re-add cookies: spectre add <name> "auth_token=...; ct0=..."',
            )

        def rank(acc) -> tuple[int, str]:
            # preferred first, then least-recently-used (twscrape keeps last_used as str/None)
            return (0 if acc.username == self._preferred else 1, str(acc.last_used or ""))

        return sorted(usable, key=rank)

    async def _client(self, acc) -> httpx.AsyncClient:
        cached = self._clients.get(acc.username)
        if cached is not None and not cached.is_closed:
            return cached
        cookies = _cookies(acc)
        jar = httpx.Cookies()
        for domain in (".x.com", ".twitter.com", "api.twitter.com"):
            jar.set("auth_token", cookies.get("auth_token", ""), domain=domain)
            jar.set("ct0", cookies.get("ct0", ""), domain=domain)
        headers = {
            "authorization": f"Bearer {BEARER}",
            "x-csrf-token": cookies.get("ct0", ""),
            "content-type": "application/json",
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "referer": "https://x.com/",
            "user-agent": acc.user_agent or UA_DEFAULT,
        }
        proxy = self.proxy or acc.proxy or None
        client = httpx.AsyncClient(
            headers=headers, cookies=jar, proxy=proxy, timeout=30, follow_redirects=True
        )
        self._clients[acc.username] = client
        return client

    async def _txid(self, acc, fresh: bool = False):
        """Mint x-client-transaction-id the same way the web app does.

        Best-effort: X accepts most reads without it, so a failure logs and moves
        on rather than breaking the call.
        """
        try:
            from twscrape.queue_client import XClIdGenStore

            gen = await asyncio.wait_for(
                XClIdGenStore.get(acc.username, proxy=self.proxy or acc.proxy, cookies=_cookies(acc), fresh=fresh),
                timeout=10,
            )
            return gen
        except Exception as exc:  # noqa: BLE001 - never fail a request over this
            logger.debug(f"tx-id unavailable for @{acc.username}: {exc}")
            return None

    async def aclose(self) -> None:
        for client in self._clients.values():
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()

    # ── core request ──

    def _url(self, name: str) -> tuple[str, dict]:
        spec = OPS.get(name)
        if not spec:
            raise XError(
                f"Unknown GraphQL operation {name!r}.",
                kind="upstream",
                hint="Run `spectre doctor`; if a new operation is needed, update ops.py.",
            )
        query_id, method, features, toggles = spec
        override = os.environ.get(f"SPECTRE_OP_{name.upper()}")
        if override:
            query_id = override
        return f"{GQL}/{query_id}/{name}", {"method": method, "features": features, "toggles": toggles, "query_id": query_id}

    async def graphql(self, name: str, variables: dict[str, Any]) -> dict:
        """Call one GraphQL operation, rotating accounts on recoverable failures."""
        url, spec = self._url(name)
        accounts = await self._accounts()
        errors: list[XError] = []

        for attempt, acc in enumerate(accounts):
            client = await self._client(acc)
            tx = await self._txid(acc)
            headers = {"x-client-transaction-id": tx.calc(spec["method"].upper(), f"/i/api/graphql/{spec['query_id']}/{name}")} if tx else {}

            body = {
                "variables": variables,
                "features": spec["features"],
                "fieldToggles": {t: False for t in spec["toggles"]},
            }
            if spec["method"] == "post":
                body["queryId"] = spec["query_id"]

            try:
                if spec["method"] == "post":
                    resp = await client.post(url, json=body, headers=headers)
                else:
                    resp = await client.get(
                        url,
                        params={
                            "variables": json.dumps(variables),
                            "features": json.dumps(spec["features"]),
                            "fieldToggles": json.dumps(body["fieldToggles"]),
                        },
                        headers=headers,
                    )
            except httpx.HTTPError:
                # One quiet retry: these are usually a dropped keep-alive, not an outage.
                try:
                    await asyncio.sleep(0.4)
                    if spec["method"] == "post":
                        resp = await client.post(url, json=body, headers=headers)
                    else:
                        resp = await client.get(
                            url,
                            params={
                                "variables": json.dumps(variables),
                                "features": json.dumps(spec["features"]),
                                "fieldToggles": json.dumps(body["fieldToggles"]),
                            },
                            headers=headers,
                        )
                except httpx.HTTPError as retry_exc:
                    detail = str(retry_exc) or type(retry_exc).__name__
                    errors.append(XError(f"Network error talking to X: {detail}", kind="network", operation=name, account=acc.username))
                    continue

            self.last_headers[acc.username] = {
                k: v for k, v in resp.headers.items() if k.lower().startswith("x-rate-limit")
            }

            if resp.status_code == 429:
                reset = _int(resp.headers.get("x-rate-limit-reset"))
                await self._park(acc, "rate limit", reset)
                errors.append(rate_limit_error(name, reset, acc.username))
                continue

            try:
                data = resp.json()
            except ValueError:
                errors.append(
                    XError(
                        f"X returned a non-JSON response (HTTP {resp.status_code}).",
                        kind="upstream",
                        status=resp.status_code,
                        operation=name,
                        account=acc.username,
                    )
                )
                continue

            # A stale query id answers 404 {"message": "Query not found"}. Retry once
            # with a freshly mined transaction id before blaming the id itself.
            if resp.status_code == 404 and isinstance(data, dict) and "Query not found" in str(data.get("message", "")):
                tx = await self._txid(acc, fresh=True)
                if tx:
                    headers["x-client-transaction-id"] = tx.calc(spec["method"].upper(), f"/i/api/graphql/{spec['query_id']}/{name}")
                    try:
                        if spec["method"] == "post":
                            resp = await client.post(url, json=body, headers=headers)
                        else:
                            resp = await client.get(
                                url,
                                params={
                                    "variables": json.dumps(variables),
                                    "features": json.dumps(spec["features"]),
                                    "fieldToggles": json.dumps(body["fieldToggles"]),
                                },
                                headers=headers,
                            )
                        data = resp.json()
                    except (httpx.HTTPError, ValueError):
                        pass
                if resp.status_code == 404 and "Query not found" in str(data.get("message", "")):
                    raise XError(
                        f"X no longer serves the GraphQL operation {name!r}.",
                        kind="not_found",
                        status=404,
                        operation=name,
                        hint="Run `spectre doctor` to refresh query ids.",
                    )

            if resp.status_code in (401, 403):
                await self._park(acc, f"HTTP {resp.status_code}")
                errors.append(
                    XError(
                        f"X rejected the request (HTTP {resp.status_code}).",
                        kind="auth" if resp.status_code == 401 else "permission",
                        status=resp.status_code,
                        operation=name,
                        account=acc.username,
                        hint="If this persists the cookies are stale: spectre add <name> ...",
                    )
                )
                continue

            if resp.status_code >= 500:
                errors.append(
                    XError(
                        f"X server error (HTTP {resp.status_code}).",
                        kind="upstream",
                        status=resp.status_code,
                        operation=name,
                        account=acc.username,
                    )
                )
                continue

            if isinstance(data, dict) and data.get("errors"):
                xerr = from_x_error(data["errors"][0], operation=name, account=acc.username)
                payload = data.get("data")
                if not payload:  # error with no data at all -> real failure
                    if xerr.kind in ("auth", "rate_limit"):
                        await self._park(acc, xerr.message)
                    if xerr.kind in ("auth", "rate_limit") and attempt + 1 < len(accounts):
                        errors.append(xerr)
                        continue
                    raise xerr
                # Partial success: keep the data, surface the warning separately.
                data["_warnings"] = [e.get("message", "") for e in data["errors"]]
                data.pop("errors", None)
                return data

            if resp.status_code != 200:
                raise XError(
                    f"HTTP {resp.status_code} from {name}",
                    kind="upstream",
                    status=resp.status_code,
                    operation=name,
                    account=acc.username,
                )
            if isinstance(data, dict):
                data.pop("errors", None)
            return data

        # Every account failed: report the most informative error.
        if errors:
            first = next((e for e in errors if e.kind != "rate_limit"), errors[0])
            if all(e.kind == "rate_limit" for e in errors):
                first = rate_limit_error(name, errors[0].retry_after)
            first.hint = first.hint or "All accounts failed. Check `pool_status` / re-add cookies."
            raise first
        raise XError("Request failed with no response.", kind="network", operation=name)

    async def _park(self, acc, reason: str, reset: int | None = None) -> None:
        """Temporarily bench an account so the next request picks another one."""
        try:
            until = time.time() + (min(reset, 900) if reset else 60)
            await self.pool.lock_until(acc.username, "spectre:cooldown", until, reset)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"could not park @{acc.username}: {exc}")

    # ── REST v1.1 ──

    REST_HOSTS = ("https://x.com/i/api/1.1", "https://api.twitter.com/1.1", "https://api.x.com/1.1")

    async def rest(self, method: str, path: str, *, params: dict | None = None, data: dict | None = None) -> dict:
        """Call X's v1.1 REST surface, trying the hosts X still serves in turn."""
        accounts = await self._accounts()
        errors: list[XError] = []
        for acc in accounts:
            client = await self._client(acc)
            headers = {}
            tx = await self._txid(acc)
            if tx:
                headers["x-client-transaction-id"] = tx.calc(method.upper(), f"/i/api/1.1/{path.lstrip('/')}")
            resp = None
            try:
                for host in self.REST_HOSTS:
                    url = f"{host}/{path.lstrip('/')}"
                    if method.lower() == "get":
                        resp = await client.get(url, params=params, headers=headers)
                    else:
                        headers["content-type"] = "application/x-www-form-urlencoded"
                        resp = await client.post(url, data=data, headers=headers)
                    if resp.status_code != 404:
                        break
            except httpx.HTTPError as exc:
                errors.append(XError(f"Network error: {exc}", kind="network", account=acc.username))
                continue
            if resp.status_code == 429:
                reset = _int(resp.headers.get("x-rate-limit-reset"))
                await self._park(acc, "rate limit", reset)
                errors.append(rate_limit_error(path, reset, acc.username))
                continue
            try:
                payload = resp.json()
            except ValueError:
                raise XError(f"Non-JSON response from {path} (HTTP {resp.status_code})", kind="upstream", status=resp.status_code)
            if resp.status_code == 200:
                return payload
            if isinstance(payload, dict) and payload.get("errors"):
                xerr = from_x_error(payload["errors"][0], operation=path, account=acc.username)
                if xerr.kind in ("auth", "rate_limit"):
                    await self._park(acc, xerr.message)
                    errors.append(xerr)
                    continue
                raise xerr
            raise XError(f"HTTP {resp.status_code} from {path}", kind="upstream", status=resp.status_code, account=acc.username)
        if errors:
            raise errors[0]
        raise XError("REST request failed.", kind="network")

    async def get_bytes(self, url: str) -> bytes:
        """Fetch a public asset (pbs.twimg.com / video.twimg.com)."""
        async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers={"user-agent": UA_DEFAULT}) as c:
            resp = await c.get(url)
            resp.raise_for_status()
            return resp.content


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
