from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from configuracion.supabase_cliente import (
    crear_cliente_supabase_usuario,
    obtener_configuracion_supabase,
)

bearer_scheme = HTTPBearer(auto_error=False)
ALGORITMOS_JWT_PERMITIDOS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}


@dataclass(frozen=True)
class UsuarioAutenticado:
    id: str
    correo: str | None
    metadata: dict[str, Any]
    token: str


def _obtener_campo(objeto: Any, campo: str, default: Any = None) -> Any:
    if isinstance(objeto, dict):
        return objeto.get(campo, default)

    return getattr(objeto, campo, default)


@lru_cache(maxsize=1)
def obtener_cliente_jwks() -> jwt.PyJWKClient:
    configuracion = obtener_configuracion_supabase()
    return jwt.PyJWKClient(configuracion.jwks_url)


def decodificar_token_supabase(token: str) -> dict[str, Any]:
    configuracion = obtener_configuracion_supabase()

    if configuracion.jwt_secret:
        try:
            return jwt.decode(
                token,
                configuracion.jwt_secret,
                algorithms=["HS256"],
                audience=configuracion.jwt_audience,
                issuer=configuracion.jwt_issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="La sesión es inválida o expiró",
            ) from error

    try:
        signing_key = obtener_cliente_jwks().get_signing_key_from_jwt(token)
        header = jwt.get_unverified_header(token)
        algoritmo = header.get("alg", "RS256")

        if algoritmo not in ALGORITMOS_JWT_PERMITIDOS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="La sesión usa un algoritmo no soportado",
            )

        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[algoritmo],
            audience=configuracion.jwt_audience,
            issuer=configuracion.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión es inválida o expiró",
        ) from error


def obtener_usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UsuarioAutenticado:
    if credenciales is None or credenciales.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Debes iniciar sesión para continuar",
        )

    claims = decodificar_token_supabase(credenciales.credentials)
    usuario_id = claims.get("sub")

    if not usuario_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión no contiene un identificador de usuario válido",
        )

    metadata = claims.get("user_metadata", {}) or {}

    return UsuarioAutenticado(
        id=usuario_id,
        correo=claims.get("email"),
        metadata=metadata,
        token=credenciales.credentials,
    )


def obtener_cliente_usuario(usuario: UsuarioAutenticado):
    return crear_cliente_supabase_usuario(usuario.token)


def obtener_proyecto_del_usuario(id_repositorio: str, usuario: UsuarioAutenticado) -> dict[str, Any]:
    try:
        resultado = (
            obtener_cliente_usuario(usuario)
            .table("proyectos")
            .select("*")
            .eq("id_repositorio", id_repositorio)
            .execute()
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo validar el acceso al proyecto",
        ) from error

    if not resultado.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El proyecto no existe o no te pertenece",
        )

    return dict(resultado.data[0])
