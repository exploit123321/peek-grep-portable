"""App settings: start with Windows (through the desktop hook), the tray start, and window options."""

from fastapi.testclient import TestClient

from app.main import app, set_autostart_callback
from app.state import desktop_hooks, settings_store

client = TestClient(app)


def test_start_with_windows_uses_the_desktop_hook():
    calls = []
    set_autostart_callback(lambda enabled, hidden: calls.append((enabled, hidden)))
    try:
        body = client.get("/api/settings").json()
        assert body["app"]["start_with_windows"] is False and body["autostart_available"] is True
        res = client.put("/api/settings/app", json={"start_with_windows": True})
        assert res.status_code == 200 and res.json()["app"]["start_with_windows"] is True
        assert calls == [(True, True)]
        client.put("/api/settings/app", json={"start_hidden": False})
        assert calls[-1] == (True, False)
        # Settings that do not touch the startup entry do not call the hook
        client.put("/api/settings/app", json={"open_on_mouse_monitor": False})
        assert len(calls) == 2 and settings_store.open_on_mouse_monitor is False
        assert client.put("/api/settings/app", json={"start_with_windows": "yes"}).status_code == 400
        assert client.put("/api/settings/app", json={"bogus": True}).status_code == 400
    finally:
        client.put("/api/settings/app", json={"start_with_windows": False, "start_hidden": True, "open_on_mouse_monitor": True})
        desktop_hooks["set_autostart"] = None
    assert calls[-1] == (False, True)


def test_refused_entry_keeps_the_setting():
    def refuse(enabled, hidden):
        raise PermissionError("access denied")
    set_autostart_callback(refuse)
    try:
        res = client.put("/api/settings/app", json={"start_with_windows": True})
        assert res.status_code == 400 and settings_store.start_with_windows is False
    finally:
        desktop_hooks["set_autostart"] = None


def test_without_desktop_window():
    res = client.put("/api/settings/app", json={"start_with_windows": True})
    assert res.status_code == 400 and settings_store.start_with_windows is False


def test_freeze_rows():
    try:
        res = client.put("/api/settings/app", json={"freeze_rows": " 7 , 1-3 2;9-8 "})
        assert res.status_code == 200 and res.json()["app"]["freeze_rows"] == "1-3, 7-9"
        assert client.put("/api/settings/app", json={"freeze_rows": "a-b"}).status_code == 400
        assert client.put("/api/settings/app", json={"freeze_rows": "0"}).status_code == 400
        assert client.put("/api/settings/app", json={"freeze_rows": "1-500"}).status_code == 400
        assert client.put("/api/settings/app", json={"freeze_rows": 3}).status_code == 400
        assert settings_store.freeze_rows == "1-3, 7-9"
        assert client.put("/api/settings/app", json={"freeze_rows": ""}).json()["app"]["freeze_rows"] == ""
    finally:
        client.put("/api/settings/app", json={"freeze_rows": ""})


def test_freeze_columns():
    try:
        res = client.put("/api/settings/app", json={"freeze_columns": " c  a-b 5, e "})
        assert res.status_code == 200 and res.json()["app"]["freeze_columns"] == "A-C, E"
        assert client.put("/api/settings/app", json={"freeze_columns": "27-28"}).json()["app"]["freeze_columns"] == "AA-AB"
        assert client.put("/api/settings/app", json={"freeze_columns": "A1"}).status_code == 400
        assert client.put("/api/settings/app", json={"freeze_columns": "XFE"}).status_code == 400
        assert client.put("/api/settings/app", json={"freeze_columns": "A-ZZ"}).status_code == 400
        assert settings_store.freeze_columns == "AA-AB"
    finally:
        client.put("/api/settings/app", json={"freeze_columns": ""})
    assert settings_store.freeze_columns == ""
