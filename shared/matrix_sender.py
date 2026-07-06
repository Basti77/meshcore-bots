"""Tiny Matrix client wrapper for bots — login + send to a room.

Deliberately minimal: bots post into Matrix rooms, and the meshcore-matrix-bridge
forwards the message onto the mesh. No meshcore-lib dependency here.
"""
from __future__ import annotations

import logging
from typing import Optional

from nio import AsyncClient, AsyncClientConfig, RoomSendResponse, WhoamiResponse


log = logging.getLogger(__name__)


class SimpleMatrixSender:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        access_token: str,
        device_id: str,
    ) -> None:
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.device_id = device_id
        self.client: Optional[AsyncClient] = None

    async def connect(self) -> None:
        cfg = AsyncClientConfig(encryption_enabled=False, store_sync_tokens=False)
        self.client = AsyncClient(self.homeserver, self.user_id, config=cfg)
        self.client.access_token = self.access_token
        self.client.user_id = self.user_id
        self.client.device_id = self.device_id
        # Validate the token up front. An expired/revoked token must be a hard
        # startup failure (systemd restarts + it shows in the journal) — not a
        # per-send warning that leaves the bot looking alive for weeks.
        resp = await self.client.whoami()
        if not isinstance(resp, WhoamiResponse):
            await self.client.close()
            raise RuntimeError(f"matrix token check failed for {self.user_id}: {resp!r}")
        # quick sync to warm caches (best effort — transient failures are fine)
        await self.client.sync(timeout=3000, full_state=False)
        log.info("matrix: connected as %s (token ok)", self.user_id)

    async def send_text(self, room_id: str, body: str) -> bool:
        """Send a plain text message. Returns True on success — callers decide
        whether a failure is worth escalating (nio reports errors as
        ErrorResponse objects, it does not raise)."""
        assert self.client is not None, "call connect() first"
        resp = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": body},
            ignore_unverified_devices=True,
        )
        if not isinstance(resp, RoomSendResponse):
            log.warning("matrix: send failed: %r", resp)
            return False
        return True

    async def join(self, room_id_or_alias: str) -> Optional[str]:
        assert self.client is not None
        resp = await self.client.join(room_id_or_alias)
        rid = getattr(resp, "room_id", None)
        if rid:
            log.info("matrix: joined %s (%s)", room_id_or_alias, rid)
        return rid

    async def resolve_alias(self, alias: str) -> Optional[str]:
        assert self.client is not None
        resp = await self.client.room_resolve_alias(alias)
        rid = getattr(resp, "room_id", None)
        if rid:
            return rid
        # nio's room_resolve_alias has been failing to validate this Synapse's
        # directory response (observed since 2026-05). Fall back to a raw CS-API
        # GET, which returns a clean {"room_id": ...}. Without this the caller
        # would silently keep the alias and post to it -> 403 "not in room".
        log.warning("matrix: nio alias resolve failed for %s, trying raw HTTP", alias)
        return await self._resolve_alias_http(alias)

    async def _resolve_alias_http(self, alias: str) -> Optional[str]:
        import urllib.parse

        import aiohttp

        url = (
            f"{self.homeserver}/_matrix/client/v3/directory/room/"
            f"{urllib.parse.quote(alias)}"
        )
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as r:
                    if r.status == 200:
                        return (await r.json()).get("room_id")
                    log.warning("matrix: raw alias resolve %s -> HTTP %s", alias, r.status)
        except Exception as e:  # noqa: BLE001
            log.warning("matrix: raw alias resolve error: %s", e)
        return None

    async def close(self) -> None:
        if self.client:
            await self.client.close()
