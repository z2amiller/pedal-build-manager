from __future__ import annotations

import pathlib

import pytest

from app.storage import BoardStore


def test_board_path_returns_correct_path(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path))
    result = store.board_path("fuzz-face", "1.0.0")
    assert result == tmp_path / "fuzz-face" / "1.0.0"


def test_manifest_path_returns_manifest_json(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path))
    result = store.manifest_path("fuzz-face", "1.0.0")
    assert result == tmp_path / "fuzz-face" / "1.0.0" / "manifest.json"


def test_board_path_no_existence_check(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path))
    result = store.board_path("nonexistent", "0.1.0")
    assert not result.exists()


def test_invalid_slug_raises(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path))
    with pytest.raises(ValueError, match="slug"):
        store.board_path("Bad_Slug", "1.0.0")


def test_invalid_slug_uppercase_raises(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path))
    with pytest.raises(ValueError, match="slug"):
        store.board_path("FuzzFace", "1.0.0")


def test_invalid_version_raises(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path))
    with pytest.raises(ValueError, match="version"):
        store.board_path("fuzz-face", "1.0_0")


def test_list_boards_empty_when_no_dir(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path / "nonexistent"))
    assert store.list_boards() == []


def test_list_boards_returns_slugs(tmp_path: pathlib.Path) -> None:
    (tmp_path / "fuzz-face").mkdir()
    (tmp_path / "tube-screamer").mkdir()
    store = BoardStore(data_dir=str(tmp_path))
    assert store.list_boards() == ["fuzz-face", "tube-screamer"]


def test_list_boards_ignores_files(tmp_path: pathlib.Path) -> None:
    (tmp_path / "fuzz-face").mkdir()
    (tmp_path / "readme.txt").write_text("hello")
    store = BoardStore(data_dir=str(tmp_path))
    assert store.list_boards() == ["fuzz-face"]


def test_list_versions_empty_when_no_slug(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path))
    assert store.list_versions("fuzz-face") == []


def test_list_versions_returns_versions(tmp_path: pathlib.Path) -> None:
    board_dir = tmp_path / "fuzz-face"
    (board_dir / "1.0.0").mkdir(parents=True)
    (board_dir / "1.1.0").mkdir()
    store = BoardStore(data_dir=str(tmp_path))
    assert store.list_versions("fuzz-face") == ["1.0.0", "1.1.0"]


def test_list_versions_invalid_slug_raises(tmp_path: pathlib.Path) -> None:
    store = BoardStore(data_dir=str(tmp_path))
    with pytest.raises(ValueError, match="slug"):
        store.list_versions("Bad Slug")


def test_uses_env_var(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUILDER_DATA_DIR", str(tmp_path))
    store = BoardStore()
    result = store.board_path("fuzz-face", "1.0.0")
    assert result == tmp_path / "fuzz-face" / "1.0.0"


def test_explicit_data_dir_overrides_env(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUILDER_DATA_DIR", "/should/not/be/used")
    store = BoardStore(data_dir=str(tmp_path))
    result = store.board_path("fuzz-face", "1.0.0")
    assert result == tmp_path / "fuzz-face" / "1.0.0"
