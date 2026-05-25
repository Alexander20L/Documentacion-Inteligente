from fastapi import FastAPI
import os
from routers import repositorios
from routers import autenticacion
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers import graphify
from routers import documentacion

app = FastAPI(title="Documentación Inteligente")

cors_origins = [
    origen.strip()
    for origen in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:4200,http://localhost:3000,http://127.0.0.1:4200,http://127.0.0.1:3000"
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
app.include_router(graphify.router)
app.include_router(documentacion.router)

app.mount(
    "/graphify",
    StaticFiles(directory="graphify-out"),
    name="graphify"
)

@app.get("/")
def home():
    return {"message": "Backend funcionando"}