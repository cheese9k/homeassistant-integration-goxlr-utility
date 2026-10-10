"""Ensure both sync directions, motor suppression, debounce and lifecycle work."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def state(brightness=100, value="on", context_id="external"):
    return SimpleNamespace(
        state=value,
        attributes={"brightness": brightness},
        context=SimpleNamespace(id=context_id),
    )


@pytest.fixture
async def sync(modules):
    hass = SimpleNamespace(
        loop=asyncio.get_running_loop(),
        states=SimpleNamespace(get=Mock(return_value=state())),
        services=SimpleNamespace(async_call=AsyncMock()),
        async_create_background_task=lambda coro, name: asyncio.create_task(
            coro, name=name
        ),
    )
    coordinator = SimpleNamespace(
        last_update_success=True,
        fader_channel=Mock(return_value="Music"),
        channel_volume=Mock(return_value=100),
        async_set_volume=AsyncMock(),
        async_add_listener=Mock(return_value=lambda: None),
    )
    obj = modules.sync.FaderLightSync(
        hass, coordinator, {"fader_lights": {"a": "light.desk"}}
    )
    yield obj
    obj.stop()


async def test_light_to_fader_and_motor_echo(sync):
    sync.coordinator.channel_volume.return_value = 40
    await sync._sync("a", "light_to_fader")
    sync.coordinator.async_set_volume.assert_awaited_once_with("Music", 100)
    sync.coordinator.channel_volume.return_value = 60
    await sync._sync("a", "fader_to_light")
    sync.hass.services.async_call.assert_not_awaited()


async def test_fader_to_light_and_echo(sync):
    sync.coordinator.channel_volume.return_value = 180
    await sync._sync("a", "fader_to_light")
    call = sync.hass.services.async_call.call_args
    assert call.args[:2] == ("light", "turn_on")
    assert call.args[2] == {
        "entity_id": "light.desk",
        "brightness": 180,
        "transition": 0,
    }
    sync._schedule = Mock()
    sync._light_updated(
        SimpleNamespace(
            data={
                "entity_id": "light.desk",
                "old_state": state(),
                "new_state": state(180, context_id=call.kwargs["context"].id),
            }
        )
    )
    sync._schedule.assert_not_called()
    sync._light_updated(
        SimpleNamespace(
            data={
                "entity_id": "light.desk",
                "old_state": state(180),
                "new_state": state(200),
            }
        )
    )
    sync._schedule.assert_called_once_with("a", "light_to_fader")


async def test_off_both_directions(sync):
    sync.coordinator.channel_volume.return_value = 0
    await sync._sync("a", "fader_to_light")
    assert sync.hass.services.async_call.call_args.args == (
        "light",
        "turn_off",
        {"entity_id": "light.desk"},
    )
    sync.hass.states.get.return_value = state(100, "off")
    sync.coordinator.channel_volume.return_value = 90
    await sync._sync("a", "light_to_fader")
    sync.coordinator.async_set_volume.assert_awaited_once_with("Music", 0)


async def test_unavailable_and_non_dimmable(sync):
    sync.hass.states.get.return_value = state(value="unavailable")
    await sync._sync("a", "light_to_fader")
    await sync._sync("a", "fader_to_light")
    sync.coordinator.async_set_volume.assert_not_awaited()
    sync.hass.services.async_call.assert_not_awaited()
    sync.hass.states.get.return_value = SimpleNamespace(state="on", attributes={})
    await sync._sync("a", "fader_to_light")
    sync.hass.services.async_call.assert_not_awaited()


async def test_start_reconnect_and_reassignment_light_wins(sync):
    sync._schedule = Mock()
    sync._mixer_updated()
    sync._schedule.assert_called_with("a", "light_to_fader")
    sync._schedule.reset_mock()
    sync.coordinator.channel_volume.return_value = 150
    sync._mixer_updated()
    sync._schedule.assert_called_once_with("a", "fader_to_light")
    sync.coordinator.fader_channel.return_value = "Chat"
    sync._mixer_updated()
    sync._schedule.assert_called_with("a", "light_to_fader")
    sync.coordinator.last_update_success = False
    sync._mixer_updated()
    sync.coordinator.last_update_success = True
    sync._mixer_updated()
    sync._schedule.assert_called_with("a", "light_to_fader")


async def test_debounce_latest_value_and_stop(sync, modules, monkeypatch):
    monkeypatch.setattr(modules.sync, "DEBOUNCE_SECONDS", 0.01)
    sync.coordinator.channel_volume.return_value = 110
    sync._schedule("a", "fader_to_light")
    sync.coordinator.channel_volume.return_value = 190
    sync._schedule("a", "fader_to_light")
    await asyncio.sleep(0.04)
    sync.hass.services.async_call.assert_awaited_once()
    assert sync.hass.services.async_call.call_args.args[2]["brightness"] == 190
    sync._schedule("a", "fader_to_light")
    sync.stop()
    await asyncio.sleep(0.02)
    assert not sync._timers
    assert sync.hass.services.async_call.await_count == 1


async def test_final_motor_position_reconciles(sync, modules, monkeypatch):
    monkeypatch.setattr(modules.sync, "MOTOR_SETTLE_SECONDS", 0.01)
    monkeypatch.setattr(modules.sync, "DEBOUNCE_SECONDS", 0.01)
    sync.coordinator.channel_volume.return_value = 30
    await sync._sync("a", "light_to_fader")
    sync.coordinator.channel_volume.return_value = 96
    await asyncio.sleep(0.05)
    assert sync.hass.services.async_call.call_args.args[2]["brightness"] == 96


async def test_new_light_change_not_overwritten_by_motor_settle(
    sync, modules, monkeypatch
):
    monkeypatch.setattr(modules.sync, "DEBOUNCE_SECONDS", 0.01)
    sync.coordinator.channel_volume.return_value = 30

    async def remote_change_during_write(channel, brightness):
        sync.hass.states.get.return_value = state(200)
        sync._schedule("a", "light_to_fader")

    sync.coordinator.async_set_volume.side_effect = remote_change_during_write
    await sync._sync("a", "light_to_fader")
    sync.coordinator.async_set_volume.side_effect = None
    await asyncio.sleep(0.04)
    assert sync.coordinator.async_set_volume.call_args.args == ("Music", 200)


async def test_continuous_fader_motion_updates_without_waiting_for_release(
    sync, modules, monkeypatch
):
    monkeypatch.setattr(modules.sync, "DEBOUNCE_SECONDS", 0.02)
    for value in range(120, 200, 10):
        sync.coordinator.channel_volume.return_value = value
        sync._schedule("a", "fader_to_light")
        await asyncio.sleep(0.01)
    assert sync.hass.services.async_call.await_count >= 2
