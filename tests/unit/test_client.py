"""Protocol regression tests using a real local aiohttp WebSocket server."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession, web


@pytest.fixture
def snapshot():
    return {
        "config": {"daemon_version": "1.2.0"},
        "mixers": {
            "SERIAL": {
                "hardware": {"serial_number": "SERIAL"},
                "fader_status": {"A": {"channel": "Music", "mute_state": "Unmuted"}},
                "levels": {"volumes": {"Music": 100, "Chat": 90}},
                "profile_name": "Default",
            },
            "OTHER": {"levels": {"volumes": {"Music": 200}}},
        },
    }


async def start_server(handler):
    app = web.Application()
    app.router.add_get("/api/websocket", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]


async def test_command_and_patch_batch(modules, snapshot):
    requests = []
    patched = asyncio.Event()

    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            payload = message.json()
            requests.append(payload)
            if payload["data"] == "GetStatus":
                await socket.send_json(
                    {"id": payload["id"], "data": {"Status": snapshot}}
                )
            else:
                await socket.send_json(
                    {
                        "id": 0,
                        "data": {
                            "Patch": [
                                {
                                    "op": "replace",
                                    "path": "/mixers/SERIAL/levels/volumes/Music",
                                    "value": 255,
                                },
                                {
                                    "op": "replace",
                                    "path": "/mixers/SERIAL/fader_status/A/channel",
                                    "value": "Chat",
                                },
                                {
                                    "op": "add",
                                    "path": "/config/new_setting",
                                    "value": True,
                                },
                                {"op": "remove", "path": "/mixers/OTHER"},
                            ]
                        },
                    }
                )
                await socket.send_json({"id": payload["id"], "data": "Ok"})
        return socket

    runner, port = await start_server(handler)
    try:
        async with ClientSession() as session:
            client = modules.client.GoXLRClient(session, "127.0.0.1", port, "SERIAL")
            client.on_update = patched.set
            await client.connect()
            await client.get_status()
            assert client.mixer.levels.volumes.music == 100
            await client.set_volume("Music", 255)
            await asyncio.wait_for(patched.wait(), 1)
            assert requests[-1]["data"] == {
                "Command": ["SERIAL", {"SetVolume": ["Music", 255]}]
            }
            assert client.mixer.levels.volumes.music == 255
            assert client.mixer.fader_status.a.channel == "Chat"
            assert client.status["config"]["new_setting"] is True
            assert "OTHER" not in client.status["mixers"]
            await client.disconnect()
            assert not session.closed
            assert not client._pending
    finally:
        await runner.cleanup()


async def test_out_of_order_responses(modules):
    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        first = await socket.receive_json()
        second = await socket.receive_json()
        await socket.send_json({"id": second["id"], "data": "second"})
        await socket.send_json({"id": first["id"], "data": "first"})
        async for _ in socket:
            pass
        return socket

    runner, port = await start_server(handler)
    try:
        async with ClientSession() as session:
            client = modules.client.GoXLRClient(session, "127.0.0.1", port)
            await client.connect()
            assert await asyncio.gather(
                client.request("one"), client.request("two")
            ) == ["first", "second"]
            await client.disconnect()
    finally:
        await runner.cleanup()


async def test_disconnect_fails_pending_request(modules):
    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.receive_json()
        await socket.close()
        return socket

    runner, port = await start_server(handler)
    try:
        async with ClientSession() as session:
            client = modules.client.GoXLRClient(session, "127.0.0.1", port)
            await client.connect()
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(client.request("GetStatus"), 1)
            assert not client._pending
            await client.disconnect()
    finally:
        await runner.cleanup()


def test_selected_mixer_not_replaced(modules, snapshot):
    client = modules.client.GoXLRClient(None, "localhost", 14564, "SERIAL")
    client.status = deepcopy(snapshot)
    del client.status["mixers"]["SERIAL"]
    assert client.mixer is None


async def test_write_command_formats_and_clamping(modules):
    client = modules.client.GoXLRClient(None, "localhost", 14564, "SERIAL")
    client.request = AsyncMock(return_value="Ok")
    await client.set_volume("Music", -100)
    client.request.assert_awaited_with(
        {"Command": ["SERIAL", {"SetVolume": ["Music", 0]}]}
    )
    await client.set_volume("Music", 300)
    client.request.assert_awaited_with(
        {"Command": ["SERIAL", {"SetVolume": ["Music", 255]}]}
    )
    await client.set_muted("A", True)
    client.request.assert_awaited_with(
        {"Command": ["SERIAL", {"SetFaderMuteState": ["A", "MutedToX"]}]}
    )
    await client.set_fader_color("A", "ffffff", "000000")
    client.request.assert_awaited_with(
        {"Command": ["SERIAL", {"SetFaderColours": ["A", "ffffff", "000000"]}]}
    )


async def test_cancel_removes_pending_request(modules):
    client = modules.client.GoXLRClient(None, "localhost", 14564)
    client.socket = SimpleNamespace(closed=False, send_json=AsyncMock())
    client._reader = asyncio.create_task(asyncio.Event().wait())
    task = asyncio.create_task(client.request("GetStatus"))
    await asyncio.sleep(0)
    assert len(client._pending) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client._pending
    client._reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await client._reader


async def test_request_timeout_does_not_leak_futures(modules, monkeypatch):
    monkeypatch.setattr(modules.client, "REQUEST_TIMEOUT_SECONDS", 0.01)
    client = modules.client.GoXLRClient(None, "localhost", 14564)
    client.socket = SimpleNamespace(closed=False, send_json=AsyncMock())
    client._reader = asyncio.create_task(asyncio.Event().wait())
    try:
        with pytest.raises(TimeoutError):
            await client.request("GetStatus")
        assert not client._pending
    finally:
        client._reader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await client._reader
