import os
import shutil
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import repositorios
from routers import autenticacion
from routers import c4
from servicios.servicio_graphify import obtener_graphify_bin

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
app.include_router(c4.router)


@app.get("/")
def home():
    return {"message": "Backend funcionando"}


@app.get("/health")
def health_check():
    graphify = obtener_graphify_bin()
    structurizr = os.getenv("STRUCTURIZR_CLI_PATH")
    plantuml = os.getenv("PLANTUML_JAR")
    mermaid = os.getenv("MERMAID_CLI_BIN") or shutil.which("mmdc")
    java = os.getenv("JAVA_BIN", "java")
    return {
        "status": "ok",
        "service": "documentacion-inteligente-backend",
        "c4_capabilities": {
            "llm_provider": os.getenv("C4_LLM_PROVIDER", "ollama"),
            "ollama_configured": bool(os.getenv("C4_OLLAMA_BASE_URL", "http://127.0.0.1:11434")),
            "gemini": bool(os.getenv("GEMINI_API_KEY")),
            "graphify": bool(graphify and graphify.is_file()),
            "java": bool(shutil.which(java) or Path(java).is_file()),
            "structurizr": bool(structurizr and Path(structurizr).is_file()),
            "plantuml": bool(plantuml and Path(plantuml).is_file()),
            "mermaid_optional": bool(mermaid and Path(mermaid).is_file()),
            "typescript_ast": bool(
                importlib.util.find_spec("tree_sitter")
                and importlib.util.find_spec("tree_sitter_typescript")
            ),
            "dify_configured": bool(os.getenv("DIFY_BASE_URL") and os.getenv("DIFY_API_KEY")),
        },
    }
