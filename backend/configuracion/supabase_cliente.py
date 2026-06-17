import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def _obtener_env_requerida(nombre: str, *, fallback: str | None = None) -> str:
    valor = os.getenv(nombre)

    if not valor and fallback:
        valor = os.getenv(fallback)

    if not valor:
        sufijo = f" o {fallback}" if fallback else ""
        raise RuntimeError(f"Falta configurar la variable de entorno {nombre}{sufijo}")

    return valor


@dataclass(frozen=True)
class ConfiguracionSupabase:
    url: str
    service_role_key: str
    anon_key: str
    jwt_audience: str
    jwt_secret: str | None

    @property
    def jwt_issuer(self) -> str:
        return f"{self.url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.jwt_issuer}/.well-known/jwks.json"


@lru_cache(maxsize=1)
def obtener_configuracion_supabase() -> ConfiguracionSupabase:
    return ConfiguracionSupabase(
        url=_obtener_env_requerida("SUPABASE_URL"),
        service_role_key=_obtener_env_requerida(
            "SUPABASE_SERVICE_ROLE_KEY",
            fallback="SUPABASE_KEY",
        ),
        anon_key=_obtener_env_requerida("SUPABASE_ANON_KEY"),
        jwt_audience=os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated"),
        jwt_secret=os.getenv("SUPABASE_JWT_SECRET") or None,
    )


@lru_cache(maxsize=1)
def obtener_cliente_supabase_admin() -> Client:
    configuracion = obtener_configuracion_supabase()
    return create_client(configuracion.url, configuracion.service_role_key)


def crear_cliente_supabase_usuario(access_token: str) -> Client:
    configuracion = obtener_configuracion_supabase()
    cliente = create_client(configuracion.url, configuracion.anon_key)
    cliente.postgrest.auth(access_token)
    return cliente


supabase_admin = obtener_cliente_supabase_admin()
