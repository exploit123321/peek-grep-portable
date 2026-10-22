"""Keyboard shortcuts in settings.json: in-app keys and the global show/hide key."""

from fastapi.testclient import TestClient

from app.main import app, set_hotkey_callback
from app.routers.settings import valid_hotkey
from app.state import desktop_hooks, settings_store

client = TestClient(app)


def test_valid_hotkey_names():
    assert valid_hotkey("alt+space") and valid_hotkey("ctrl+shift+f") and valid_hotkey("f9")
    assert not valid_hotkey("a") and not valid_hotkey("ctrl+") and not valid_hotkey("ctrl+ctrl+a")


def test_save_shortcuts_and_hotkey():
    old_hotkey = settings_store.hotkey
    registered = []
    set_hotkey_callback(registered.append)
    try:
        res = client.put("/api/settings/shortcuts", json={"shortcuts": {"move_down": ["ArrowDown", "J"]}, "hotkey": "Ctrl+Shift+F"})
        assert res.status_code == 200
        body = res.json()
        assert body["shortcuts"] == {"move_down": ["ArrowDown", "J"]}
        assert body["hotkey"] == "ctrl+shift+f" and registered == ["ctrl+shift+f"]
        assert client.get("/api/settings").json()["shortcuts"]["move_down"] == ["ArrowDown", "J"]

        assert client.put("/api/settings/shortcuts", json={"hotkey": "q"}).status_code == 400
        assert client.put("/api/settings/shortcuts", json={"shortcuts": {"Bad Name": ["K"]}}).status_code == 400
        assert settings_store.hotkey == "ctrl+shift+f"
    finally:
        desktop_hooks["set_hotkey"] = None
        client.put("/api/settings/shortcuts", json={"shortcuts": {}, "hotkey": old_hotkey})
    assert settings_store.shortcuts == {} and settings_store.hotkey == old_hotkey


def test_refused_hotkey_keeps_the_old_one():
    def refuse(_):
        raise ValueError("in use")
    set_hotkey_callback(refuse)
    try:
        before = settings_store.hotkey
        res = client.put("/api/settings/shortcuts", json={"hotkey": "ctrl+alt+k"})
        assert res.status_code == 400 and settings_store.hotkey == before
    finally:
        desktop_hooks["set_hotkey"] = None
