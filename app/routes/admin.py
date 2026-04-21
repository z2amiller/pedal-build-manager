import os
import secrets
import shutil
import tempfile
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import db
from app.manifest import load_manifest
from app.storage import BoardStore

router = APIRouter(prefix="/admin")
security = HTTPBasic()


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


@router.get("/ping", dependencies=[Depends(verify_admin)])
def ping():
    return {"status": "ok"}


@router.post("/set-default/{slug}/{version}", dependencies=[Depends(verify_admin)])
def set_default(slug: str, version: str, request: Request):
    db.set_default_version(request.app.state.db, slug, version)
    return {"slug": slug, "default_version": version}


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
