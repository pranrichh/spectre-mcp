"""Error normalisation for X's API.

Every failure path in Spectre ends up here so that tools return one consistent
shape instead of leaking httpx exceptions or, worse, reporting success:

    {"error": "<human readable>", "code": <x error code or null>,
     "kind": "auth|rate_limit|not_found|permission|validation|upstream|network",
     "hint": "<what the caller should do next>"}

The `kind` field is the contract agents branch on; `error` is for humans.
"""

from __future__ import annotations

from typing import Any, Optional

# X's public error codes worth translating. Everything else falls back to the
# server-supplied message.
CODE_HINTS: dict[int, tuple[str, str]] = {
    32: ("auth", "Cookies are no longer valid. Run: spectre add <username> \"auth_token=...; ct0=...\""),
    34: ("not_found", "X rejected the object or the path. If other tools work, the post/user is gone; if many fail, refresh query ids with `spectre doctor`."),
    37: ("permission", "This account is not authorised for that action (often X Premium only)."),
    50: ("not_found", "User does not exist."),
    63: ("not_found", "User has been suspended."),
    64: ("auth", "The authenticated account is suspended."),
    88: ("rate_limit", "Rate limited. Wait for the reset or switch accounts."),
    89: ("auth", "Token expired or invalid — re-add the account cookies."),
    120: ("validation", "The profile description contains characters X rejects (< > &). Reword it."),
    139: ("not_found", "Tweet already liked."),
    144: ("not_found", "No tweet with that id (deleted or wrong id)."),
    160: ("validation", "Follow request already sent."),
    161: ("permission", "Follow limit reached for this account."),
    179: ("permission", "Not authorised to view this tweet (protected account)."),
    186: ("validation", "Tweet too long for this account tier (280 chars standard, 25000 Premium)."),
    187: ("validation", "Duplicate tweet — X rejects identical text."),
    205: ("permission", "This user does not accept DMs from you."),
    214: ("permission", "Not authorised — this account cannot perform that action."),
    226: ("permission", "X flagged this as automated behaviour. Slow down or change account."),
    261: ("permission", "This application/account cannot perform write actions."),
    272: ("permission", "You are blocked by the target account."),
    326: ("auth", "Account temporarily locked by X."),
    349: ("permission", "You can only DM users who follow you."),
    353: ("permission", "Recipient is not accepting messages."),
    385: ("not_found", "The tweet being replied to is unavailable."),
    386: ("validation", "Duplicate tweet."),
}

RETRYABLE = {"upstream", "network", "rate_limit"}


class XError(Exception):
    """A failed X API call with a structured, agent-readable payload."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "upstream",
        code: Optional[int] = None,
        hint: Optional[str] = None,
        status: Optional[int] = None,
        retry_after: Optional[int] = None,
        operation: Optional[str] = None,
        account: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.code = code
        self.hint = hint
        self.status = status
        self.retry_after = retry_after
        self.operation = operation
        self.account = account

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.message, "kind": self.kind}
        if self.code is not None:
            out["code"] = self.code
        if self.hint:
            out["hint"] = self.hint
        if self.status:
            out["status"] = self.status
        if self.retry_after:
            out["retry_after_seconds"] = self.retry_after
        if self.operation:
            out["operation"] = self.operation
        if self.account:
            out["account"] = self.account
        return out


def from_x_error(err: dict, *, operation: str | None = None, account: str | None = None) -> XError:
    """Build an XError from one entry of a GraphQL `errors` array."""
    code = err.get("code")
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    msg = err.get("message") or str(err)
    ext = err.get("extensions") or {}
    name = ext.get("name") or ""

    kind, hint = CODE_HINTS.get(code, (None, None)) if code is not None else (None, None)
    if kind is None:
        if name in ("AuthorizationError", "Forbidden"):
            kind, hint = "permission", "Not authorised for this action."
        elif name == "DecodeException":
            kind, hint = "upstream", "X failed to serialise the response (server-side). Retry, then report if persistent."
        elif "not found" in msg.lower() or "_Missing" in msg:
            kind = "not_found"
        elif "rate limit" in msg.lower():
            kind, hint = "rate_limit", "Wait for the reset or switch accounts."
        elif "authenticate" in msg.lower() or "token" in msg.lower():
            kind = "auth"
        else:
            kind = "upstream"
    # The first line of X's message is the useful part; the rest is noise.
    clean = msg.split(": ", 1)[-1] if msg.startswith("BadRequest") else msg
    return XError(clean, kind=kind, code=code, hint=hint, operation=operation, account=account)


def rate_limit_error(operation: str, reset_at: int | None, account: str | None = None) -> XError:
    hint = "Wait for the window to reset, or add/switch accounts (list_accounts → set_active_account)."
    return XError(
        f"Rate limited on {operation}",
        kind="rate_limit",
        hint=hint,
        retry_after=reset_at,
        operation=operation,
        account=account,
    )
