import os
import secrets
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app import db
from app.manifest import load_manifest
from app.storage import BoardStore

router = APIRouter(prefix="/admin")
security = HTTPBasic()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    password = os.environ.get("ADMIN_PASSWORD")
    if password is None:
        raise HTTPException(status_code=503, detail="Admin authentication is not configured")
    if not secrets.compare_digest(credentials.password.encode(), password.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
def admin_page(request: Request):
    boards = db.list_boards(request.app.state.db)
    for board in boards:
        board["versions"] = db.list_versions(request.app.state.db, board["slug"])
    return templates.TemplateResponse(request=request, name="admin.html", context={"boards": boards})


@router.get("/ping", dependencies=[Depends(verify_admin)])
def ping():
    return {"status": "ok"}


@router.post("/set-default/{slug}/{version}", dependencies=[Depends(verify_admin)])
def set_default(slug: str, version: str, request: Request):
    db.set_default_version(request.app.state.db, slug, version)
    return {"slug": slug, "default_version": version}


@router.post("/upload-pdf", dependencies=[Depends(verify_admin)])
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    """Accept a PDF build document for an already-uploaded board version."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="File must be a .pdf")

    content = await file.read()

    # Expect filename like "fx-bloodyg-1.0.0.pdf" → slug + version embedded,
    # but we just need the user to tell us slug+version via query params or
    # we sniff from the manifest store.  Simplest: require slug + version fields.
    slug = request.query_params.get("slug")
    version = request.query_params.get("version")
    if not slug or not version:
        raise HTTPException(status_code=422, detail="slug and version query params required")

    store = BoardStore()
    try:
        board_dir = store.board_path(slug, version)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not board_dir.exists():
        raise HTTPException(status_code=404, detail=f"Board {slug!r} v{version!r} not found — upload the manifest first")

    pdf_path = store.pdf_path(slug, version)
    pdf_path.write_bytes(content)

    return {"slug": slug, "version": version, "url": f"/board/{slug}/{version}/build-doc.pdf"}


@router.post("/upload", dependencies=[Depends(verify_admin)])
async def upload_manifest(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        try:
            manifest = load_manifest(tmp_path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        slug = manifest.board_name.lower().replace(" ", "-")
        version = manifest.version
        store = BoardStore()
        try:
            dest_dir = store.board_path(slug, version)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        updated = dest_dir.exists()
        dest_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(dest_dir)
        # Keep original zip so board_view can load SVGs directly from it
        shutil.copy2(tmp_path, store.zip_path(slug, version))

        db.upsert_board(request.app.state.db, slug, manifest.display_name or manifest.board_name)
        db.upsert_version(request.app.state.db, slug, version)

        return {
            "slug": slug,
            "version": version,
            "url": f"/board/{slug}/{version}",
            "updated": updated,
        }
    finally:
        os.unlink(tmp_path)
