"""API-key authenticated account controls for the `ecc` command.

These endpoints mirror the signed-in dashboard: list keys and runs, create and
revoke keys, read a run's verification detail and choose the leaderboard
listing. A worker key can call them, so contributors can manage an account from
a terminal without a browser session. No endpoint returns another key's secret.
"""

from __future__ import annotations

from datetime import datetime
import json
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .service import Rejected

BODY_LIMIT = 4096


def _bearer(request: Request) -> str:
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer ") or len(value) > 160:
        raise Rejected(401, "API key required")
    return value[7:]


async def _body(request: Request, limit: int = BODY_LIMIT) -> bytes:
    declared = request.headers.get("content-length")
    length = None
    if declared is not None:
        try:
            length = int(declared)
        except ValueError:
            raise Rejected(400, "invalid Content-Length") from None
        if length < 0:
            raise Rejected(400, "invalid Content-Length")
        if length > limit:
            raise Rejected(413, "request body too large")
    result = bytearray()
    async for chunk in request.stream():
        if len(result) + len(chunk) > limit:
            raise Rejected(413, "request body too large")
        result.extend(chunk)
    if length is not None and len(result) != length:
        raise Rejected(400, "body length differs from Content-Length")
    return bytes(result)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _constant(_value):
    raise ValueError("nonfinite JSON number")


async def _json(request: Request, fields: set[str], optional: frozenset = frozenset()) -> dict:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise Rejected(415, "JSON content type required")
    raw = await _body(request)
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise Rejected(400, "invalid JSON body") from None
    if type(value) is not dict or not fields <= set(value) <= fields | optional:
        raise Rejected(400, "body contains missing or unexpected fields")
    return value


def _jsonable(value):
    """Dates and UUIDs as the strings the CLI prints and parses."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    return value


def _response(value, status: int = 200) -> JSONResponse:
    return JSONResponse(_jsonable(value), status_code=status,
                        headers={"Cache-Control": "no-store"})


def create_router(service, leaderboard_reader, *, multicurve_enabled: bool) -> APIRouter:
    router = APIRouter(prefix="/v1/account")

    async def key_for(request: Request) -> dict:
        return await run_in_threadpool(service.authenticate, _bearer(request))

    @router.get("")
    async def account(request: Request):
        key = await key_for(request)
        identity = await run_in_threadpool(service.account_identity, key["account_id"])
        keys = await run_in_threadpool(service.account_keys, key["account_id"])
        runs = await run_in_threadpool(service.account_runs, key["account_id"],
                                       include_generic=multicurve_enabled)
        return _response({"account": identity, "keys": keys, "runs": runs})

    @router.get("/keys")
    async def keys(request: Request):
        key = await key_for(request)
        return _response({"keys": await run_in_threadpool(service.account_keys,
                                                          key["account_id"])})

    @router.post("/keys")
    async def create_key(request: Request):
        key = await key_for(request)
        value = await _json(request, {"label"})
        if not isinstance(value["label"], str):
            raise Rejected(400, "label must be a string")
        secret = await run_in_threadpool(service.create_key, key["account_id"], value["label"])
        return _response({"key": secret}, 201)

    @router.post("/keys/{key_id}/revoke")
    async def revoke_key(request: Request, key_id: str):
        key = await key_for(request)
        await _body(request, 0)
        await run_in_threadpool(service.revoke_key, key["account_id"], key_id)
        return _response({"revoked": key_id})

    @router.get("/leaderboard")
    async def leaderboard_setting(request: Request):
        key = await key_for(request)
        identity = await run_in_threadpool(service.account_identity, key["account_id"])
        return _response(identity)

    @router.post("/leaderboard")
    async def set_leaderboard(request: Request):
        key = await key_for(request)
        value = await _json(request, {"visible"})
        if type(value["visible"]) is not bool:
            raise Rejected(400, "visible must be true or false")
        await run_in_threadpool(service.set_leaderboard_visible, key["account_id"],
                                value["visible"])
        leaderboard_reader.invalidate()
        return _response({"leaderboard_visible": value["visible"]})

    @router.get("/runs")
    async def runs(request: Request, protocol: str | None = None, run_id: str | None = None):
        key = await key_for(request)
        if protocol not in (None, "v1", "v2"):
            raise Rejected(400, "protocol must be v1 or v2")
        result = await run_in_threadpool(
            service.account_runs, key["account_id"], include_generic=multicurve_enabled,
            run_id=run_id, protocol=protocol)
        return _response(result)

    @router.get("/runs/{protocol}/{run_id}")
    async def run_detail(request: Request, protocol: str, run_id: str):
        key = await key_for(request)
        result = await run_in_threadpool(service.worker_detail, key["account_id"], protocol,
                                         run_id, include_generic=multicurve_enabled)
        return _response(result)

    return router
