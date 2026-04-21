from fastapi.testclient import TestClient

from app import db as _db
from app.main import app

client = TestClient(app)


def seed_version(client, slug, version):
    _db.upsert_board(client.app.state.db, slug, "Test Board")
    _db.upsert_version(client.app.state.db, slug, version)


def test_index_returns_200() -> None:
    response = client.get("/")
    assert response.status_code == 200


def test_board_fuzz_face_returns_200_with_svg() -> None:
    """Hit the hard-coded fuzz-face fixture and verify the composited SVG is present."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    body = response.text
    assert 'viewBox="0 0 60.96 76.2"' in body
    assert 'id="board-svg"' in body


def test_board_unknown_slug_returns_404() -> None:
    response = client.get("/board/does-not-exist/9.9.9")
    assert response.status_code == 404


def test_board_fuzz_face_bom_table_present() -> None:
    """BOM table element is present in the left panel."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert 'id="bom-table"' in response.text


def test_board_fuzz_face_bom_has_resistor_ref() -> None:
    """At least one resistor row with data-ref attribute is rendered."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    # The fuzz-face manifest has resistors; any R-prefixed ref should appear.
    assert 'data-ref="R1"' in response.text or 'data-ref="R2"' in response.text


def test_board_fuzz_face_bom_group_headers() -> None:
    """Group header tbody elements are present for expected component types."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert 'data-group="RESISTORS"' in response.text


def test_board_fuzz_face_has_fp_overlay_layer() -> None:
    """Footprint overlay group is present in the composited SVG."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert 'id="fp-overlay-layer"' in response.text


def test_board_fuzz_face_overlay_has_data_ref() -> None:
    """Overlay rects carry data-ref attributes matching component refs."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    # fuzz-face manifest has resistors R1, R2, etc.
    assert 'data-ref="R1"' in response.text or 'data-ref="R2"' in response.text


def test_board_fuzz_face_overlay_rects() -> None:
    """Overlay rects have the fp-overlay CSS class."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert 'class="fp-overlay"' in response.text


def test_board_fuzz_face_has_checkboxes() -> None:
    """Each BOM row has a checkbox with class comp-check."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert 'class="comp-check"' in response.text


def test_board_fuzz_face_has_reset_button() -> None:
    """Reset all button is present in the BOM controls."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert 'id="reset-completed"' in response.text


def test_board_fuzz_face_has_selection_sync_script() -> None:
    """Bidirectional selection sync script listens for fp:select custom event."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert "fp:select" in response.text


def test_board_fuzz_face_bom_row_selected_css() -> None:
    """CSS for .bom-row.selected is present in the page."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert "bom-row.selected" in response.text


def test_board_fuzz_face_has_hide_completed_toggle() -> None:
    """Hide-completed checkbox toggle is present in the BOM controls."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert 'id="hide-completed"' in response.text


def test_board_fuzz_face_hide_completed_filter_script() -> None:
    """Hide-completed filter JS is present and uses completion:changed event."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert "completion:changed" in response.text
    assert "hide-completed" in response.text


def test_board_fuzz_face_dblclick_script_present() -> None:
    """Double-click handler script is present on the board SVG."""
    response = client.get("/board/fuzz-face/1.0.0")
    assert response.status_code == 200
    assert "dblclick" in response.text


def test_board_slug_redirect_no_versions_returns_404(monkeypatch) -> None:
    monkeypatch.setenv("BUILDER_DB_PATH", ":memory:")
    with TestClient(app) as c:
        response = c.get("/board/fuzz-face", follow_redirects=False)
        assert response.status_code == 404


def test_board_slug_redirect_with_version_returns_302(monkeypatch) -> None:
    monkeypatch.setenv("BUILDER_DB_PATH", ":memory:")
    with TestClient(app) as c:
        seed_version(c, "fuzz-face", "1.0.0")
        response = c.get("/board/fuzz-face", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/board/fuzz-face/1.0.0"
