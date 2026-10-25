"""Dragging files out of the window: only existing files in the working folders go."""

import os

from app.state import allowed_files, settings_store


def test_allowed_files(tmp_path):
    inside = tmp_path / "work"
    inside.mkdir()
    (inside / "photo.jpg").write_bytes(b"x")
    outside = tmp_path / "secret.txt"
    outside.write_text("no")
    settings_store.set_folders([str(inside)])

    ok = str(inside / "photo.jpg")
    assert allowed_files([ok]) == [os.path.normpath(ok)]
    # Outside the working folders, missing, a folder, not text: left out
    assert allowed_files([str(outside), str(inside / "gone.jpg"), str(inside), 5, None, ""]) == []
    assert allowed_files("not a list") == []
    assert allowed_files([str(inside / ".." / "work" / "photo.jpg")]) == [os.path.normpath(ok)]
