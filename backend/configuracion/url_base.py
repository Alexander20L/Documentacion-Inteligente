import os


def obtener_url_publica_backend() -> str:
    return os.getenv("PUBLIC_BACKEND_URL", "http://127.0.0.1:8001")


def construir_url_publica(ruta: str) -> str:
    base = obtener_url_publica_backend().rstrip("/")
    ruta_normalizada = ruta.lstrip("/")
    return f"{base}/{ruta_normalizada}"