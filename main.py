import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, Response
from modules.camiones import router as camiones_router, init_module, shutdown_module

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando aplicación principal...")
    await init_module()
    yield
    await shutdown_module()
    logger.info("Aplicación principal detenida.")

app = FastAPI(
    title="Nacional Huevo - Sistema Integrado",
    description="Plataforma modular de gestión",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(camiones_router)

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/sw.js")
async def service_worker():
    sw_path = os.path.join("static", "sw.js")
    with open(sw_path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache"
        }
    )

@app.get("/manifest.json")
async def manifest_route():
    manifest_path = os.path.join("static", "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="application/manifest+json",
        headers={"Access-Control-Allow-Origin": "*"}
    )

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/icons/favicon.svg")

@app.get("/camiones")
async def camiones_dashboard():
    return FileResponse("static/camiones/index.html")

@app.get("/camiones/login")
async def camiones_login():
    return FileResponse("static/camiones/login.html")
