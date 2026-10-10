"""GoXLR's documented WebSocket protocol, using Home Assistant's session."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import jsonpatch
from aiohttp import ClientSession, WSMsgType

from .const import attribute_key

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 10


def as_model(value: Any) -> Any:
    """Keep entity attribute access while preserving raw JSON patch keys."""
    if isinstance(value, dict):
        return SimpleNamespace(
            **{attribute_key(k): as_model(v) for k, v in value.items()}
        )
    if isinstance(value, list):
        return [as_model(v) for v in value]
    return value


class GoXLRClient:
    """Correlate replies and apply complete JSON Patch batches in order."""

    def __init__(
        self, session: ClientSession, host: str, port: int, serial: str | None = None
    ):
        self.session = session
        self.host = host
        self.port = port
        self.serial = serial
        self.socket = None
        self.status: dict[str, Any] | None = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self.on_update: Callable[[], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None

    @property
    def connected(self) -> bool:
        return (
            self.socket is not None
            and not self.socket.closed
            and self._reader is not None
            and not self._reader.done()
        )

    async def connect(self) -> None:
        """Start one reader before requesting the initial snapshot."""
        self.socket = await self.session.ws_connect(
            f"http://{self.host}:{self.port}/api/websocket", heartbeat=30
        )
        self._reader = asyncio.create_task(self._listen(), name="GoXLR WebSocket")

    async def disconnect(self) -> None:
        """Close only our socket; the shared HTTP session belongs to HA."""
        if self.socket is not None:
            await self.socket.close()
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
            self._reader = None
        self.socket = None

    async def request(self, data: Any) -> Any:
        """Send a request with a bounded wait and no leaked futures."""
        if not self.connected:
            raise ConnectionError("GoXLR is disconnected")
        self._id += 1
        request_id = self._id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                await self.socket.send_json({"id": request_id, "data": data})
                result = await future
            if isinstance(result, dict) and "Error" in result:
                raise ValueError(result["Error"])
            return result
        finally:
            self._pending.pop(request_id, None)

    async def get_status(self) -> dict[str, Any]:
        """Fetch status; the reader stores it before processing more patches."""
        response = await self.request("GetStatus")
        if not isinstance(response, dict) or "Status" not in response:
            raise ValueError("Expected GoXLR Status response")
        return self.status

    @property
    def mixer(self) -> SimpleNamespace | None:
        """Select the configured serial, never silently switch devices."""
        mixers = (self.status or {}).get("mixers", {})
        if self.serial is None and mixers:
            self.serial = next(iter(mixers))
        raw = mixers.get(self.serial)
        return as_model(raw) if raw else None

    async def command(self, name: str, *args: Any) -> None:
        """Send a device-scoped Rust enum command."""
        if self.serial is None:
            raise ConnectionError("No GoXLR mixer selected")
        response = await self.request({"Command": [self.serial, {name: list(args)}]})
        if response != "Ok":
            raise ValueError(f"Unexpected GoXLR command response: {response}")

    async def set_volume(self, channel: str, volume: int) -> None:
        await self.command("SetVolume", channel, max(0, min(255, round(volume))))

    async def set_muted(self, fader: str, muted: bool) -> None:
        await self.command(
            "SetFaderMuteState", fader, "MutedToX" if muted else "Unmuted"
        )

    async def set_accent_color(self, color: str) -> None:
        await self.command("SetSimpleColour", "Accent", color)

    async def set_button_color(self, key: str, one: str, two: str) -> None:
        await self.command("SetButtonColours", key, one, two)

    async def set_fader_color(self, key: str, one: str, two: str) -> None:
        await self.command("SetFaderColours", key, one, two)

    async def _listen(self) -> None:
        try:
            async for message in self.socket:
                if message.type == WSMsgType.ERROR:
                    raise ConnectionError("GoXLR WebSocket error")
                if message.type != WSMsgType.TEXT:
                    continue
                payload = message.json()
                data = payload.get("data")
                if isinstance(data, dict) and "Status" in data:
                    self.status = data["Status"]
                elif (
                    isinstance(data, dict)
                    and "Patch" in data
                    and self.status is not None
                ):
                    self.status = jsonpatch.apply_patch(
                        deepcopy(self.status), data["Patch"]
                    )
                    if self.on_update:
                        self.on_update()
                future = self._pending.get(payload.get("id"))
                if future is not None and not future.done():
                    future.set_result(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Recovery fetches a full snapshot rather than keeping stale state.
            _LOGGER.debug("GoXLR WebSocket reader stopped", exc_info=True)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("GoXLR WebSocket closed"))
            if self.on_disconnect:
                self.on_disconnect()
