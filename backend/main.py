import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import repositorios
from routers import autenticacion
from routers import documentacion

app = FastAPI(
    title="Documentación Inteligente",
    version="1.0.0",
)

cors_origins = [
    origen.strip()
    for origen in os.getenv(
        "CORS_ORIGINS",
        "http://84.247.191.38,http://localhost:4200,http://localhost:3000,http://127.0.0.1:4200,http://127.0.0.1:3000",
    ).split(",")
    if origen.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(repositorios.router)
app.include_router(autenticacion.router)
app.include_router(documentacion.router)


@app.get("/")
def home():
    return {"message": "Backend funcionando"}


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "documentacion-inteligente-backend",
    }