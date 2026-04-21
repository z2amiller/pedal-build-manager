import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates  # noqa: F401 — used via routes

from . import db
from .routes import admin, board


@asynccontextmanager
async def lifespan(application: FastAPI):  # type: ignore[type-arg]
    db_path = os.environ.get("BUILDER_DB_PATH", "./data/builder.db")
    application.state.db = db.init_db(db_path)
    yield


app = FastAPI(title="Pedal Build Manager", lifespan=lifespan)
app.include_router(board.router)
app.include_router(admin.router)
