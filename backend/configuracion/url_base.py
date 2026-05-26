import os


def obtener_url_publica_backend() -> str:
    return os.getenv("PUBLIC_BACKEND_URL", "").rstrip("/")


def construir_url_publica(ruta: str) -> str:
    base = obtener_url_publica_backend()
    ruta_normalizada = f"/{ruta.lstrip('/')}"

    if not base:
        return ruta_normalizada

    return f"{base}{ruta_normalizada}"
