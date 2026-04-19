"""Tiny Matrix client wrapper for bots — login + send to a room.

Deliberately minimal: bots post into Matrix rooms, and the meshcore-matrix-bridge
forwards the message onto the mesh. No meshcore-lib dependency here.
"""
from __future__ import annotations

import logging
from typing import Optional

from nio import AsyncClient, AsyncClientConfig, LoginResponse, RoomSendResponse


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
        # quick sync to warm caches / validate token
        await self.client.sync(timeout=3000, full_state=False)
        log.info("matrix: connected as %s", self.user_id)

    async def send_text(self, room_id: str, body: str) -> None:
        assert self.client is not None, "call connect() first"
        resp = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": body},
            ignore_unverified_devices=True,
        )
        if not isinstance(resp, RoomSendResponse):
            log.warning("matrix: send failed: %r", resp)

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
        return getattr(resp, "room_id", None)

    async def close(self) -> None:
        if self.client:
            await self.client.close()
