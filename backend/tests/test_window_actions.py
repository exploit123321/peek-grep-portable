import pytest
from fastapi.testclient import TestClient
from app.main import (
    app,
    set_resize_window_callback,
    set_toggle_maximize_callback,
    set_get_window_size_callback,
)

client = TestClient(app)

def test_window_size_default():
    response = client.get("/api/actions/window-size")
    assert response.status_code == 200
    data = response.json()
    assert "width" in data
    assert "height" in data
    assert "is_maximized" in data

def test_window_size_with_custom_callback():
    state = {"width": 1280, "height": 820, "is_maximized": False}
    set_get_window_size_callback(lambda: state)

    response = client.get("/api/actions/window-size")
    assert response.status_code == 200
    assert response.json() == state

def test_resize_window_endpoint():
    resized = {}
    def dummy_resize(w, h):
        resized["width"] = w
        resized["height"] = h

    set_resize_window_callback(dummy_resize)

    response = client.post("/api/actions/resize-window", json={"width": 1024, "height": 680})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert resized["width"] == 1024
    assert resized["height"] == 680

def test_toggle_maximize_endpoint():
    toggle_state = [False]
    def dummy_toggle():
        toggle_state[0] = not toggle_state[0]
        return toggle_state[0]

    set_toggle_maximize_callback(dummy_toggle)

    response = client.post("/api/actions/toggle-maximize")
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert toggle_state[0] is True

    response2 = client.post("/api/actions/toggle-maximize")
    assert response2.status_code == 200
    assert toggle_state[0] is False
