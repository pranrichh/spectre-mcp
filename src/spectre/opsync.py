"""Keep X's GraphQL operation table current.

X rotates query ids every few weeks. `spectre doctor --update` downloads the
current bundle map, writes the overrides to `~/.spectre/ops.json`, and every
later process picks them up at startup — no code edit, no reinstall.

Source: fa0311/TwitterInternalAPIDocument, which extracts the ids from X's live
JavaScript bundles.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

import httpx

from spectre.ops import OPS

UPSTREAM = "https://raw.githubusercontent.com/fa0311/TwitterInternalAPIDocument/master/docs/json/GraphQL.json"

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".spectre", "ops.json")


def overrides_path() -> str:
    return os.environ.get("SPECTRE_OPS_FILE", DEFAULT_PATH)


def load_overrides() -> dict[str, dict]:
    """Read the local override table. Missing or broken file -> no overrides."""
    path = overrides_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            data = json.load(fh)
        ops = data.get("ops") if isinstance(data, dict) else None
        return ops if isinstance(ops, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def apply_overrides() -> dict[str, tuple]:
    """OPS merged with the local override table."""
    merged: dict[str, tuple] = dict(OPS)
    for name, spec in load_overrides().items():
        if name not in OPS or not isinstance(spec, dict):
            continue
        base = OPS[name]
        merged[name] = (
            spec.get("query_id") or base[0],
            spec.get("method") or base[1],
            spec.get("features") or base[2],
            spec.get("field_toggles") or base[3],
        )
    return merged


def _parse_bundle(payload: Any) -> dict[str, dict]:
    bundle: dict[str, dict] = {}
    if not isinstance(payload, list):
        raise ValueError("unexpected bundle shape")
    for item in payload:
        exports = item.get("exports") if isinstance(item, dict) else None
        if not isinstance(exports, dict):
            continue
        name = exports.get("operationName")
        query_id = exports.get("queryId")
        if not name or not query_id:
            continue
        meta = exports.get("metadata") or {}
        features = {
            key: str(value.get("value", "true")).lower() != "false"
            for key, value in (meta.get("featureSwitch") or {}).items()
        }
        bundle[name] = {
            "query_id": query_id,
            "method": "post" if exports.get("operationType") == "mutation" else "get",
            "features": features,
            "field_toggles": meta.get("fieldToggles") or [],
        }
    return bundle


async def fetch_bundle(timeout: float = 30.0) -> dict[str, dict]:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(UPSTREAM)
        resp.raise_for_status()
        return _parse_bundle(resp.json())


def diff(bundle: dict[str, dict]) -> dict[str, list[str]]:
    """What would change if the bundle were applied."""
    current = apply_overrides()
    changed, missing = [], []
    for name, spec in current.items():
        remote = bundle.get(name)
        if not remote:
            missing.append(name)
        elif remote["query_id"] != spec[0]:
            changed.append(name)
    return {"changed": sorted(changed), "missing": sorted(missing)}


async def update(write: bool = True) -> dict:
    """Refresh query ids from upstream and persist them locally."""
    bundle = await fetch_bundle()
    current = apply_overrides()
    ops: dict[str, dict] = {}
    changed: list[str] = []
    for name, spec in current.items():
        remote = bundle.get(name)
        if not remote:
            continue
        ops[name] = remote
        if remote["query_id"] != spec[0]:
            changed.append(name)
    missing = sorted(set(current) - set(bundle))
    result = {
        "source": UPSTREAM,
        "checked": len(current),
        "refreshed": len(ops),
        "changed": sorted(changed),
        "missing": missing,
        "path": overrides_path(),
    }
    if write and ops:
        path = overrides_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": UPSTREAM, "ops": ops}
        with open(path, "w") as fh:
            json.dump(payload, fh, indent=1)
    return result


def status() -> Optional[dict]:
    """Timestamp/source of the local override table, if any."""
    path = overrides_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            data = json.load(fh)
        return {"path": path, "generated_at": data.get("generated_at"), "source": data.get("source"), "ops": len(data.get("ops") or {})}
    except (OSError, json.JSONDecodeError):
        return None
