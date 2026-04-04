import logging
import os
from contextlib import asynccontextmanager

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routes import router
from app import demo_data

# Load .env before anything else
load_dotenv(encoding="utf-8-sig")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle handler."""
    logger.info("Initialising database…")
    init_db()
    logger.info("Database ready.")

    # Demo mode: load or unload sample data based on config.yaml
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if config.get("demo", {}).get("enabled", False):
            logger.info("Demo mode ON — loading sample emails…")
            demo_data.load_demo_data()
        else:
            demo_data.unload_demo_data()
    except Exception as exc:
        logger.warning("Demo mode setup failed: %s", exc)

    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Asistente de Bandeja de Entrada",
    description="Email inbox assistant for real estate agencies.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow all origins in development; tighten in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router)


# Serve the frontend SPA
@app.get("/", response_class=FileResponse)
async def serve_frontend():
    frontend_path = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    return FileResponse(frontend_path)


# Catch-all so that refreshing the SPA doesn't 404
@app.get("/{full_path:path}", response_class=FileResponse, include_in_schema=False)
async def catch_all(full_path: str):
    # Don't intercept API routes
    if full_path.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    frontend_path = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    return FileResponse(frontend_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
