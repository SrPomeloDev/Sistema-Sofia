import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
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

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/icons/favicon.svg")

@app.get("/camiones")
async def camiones_dashboard():
    return FileResponse("static/camiones/index.html")
