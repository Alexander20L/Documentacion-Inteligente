from fastapi import APIRouter, Depends

from seguridad import UsuarioAutenticado, obtener_usuario_actual

router = APIRouter(
    prefix="/autenticacion",
    tags=["Autenticación"]
)


@router.get("/perfil")
def obtener_perfil(usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    nombre = (
        usuario.metadata.get("nombre")
        or usuario.metadata.get("full_name")
        or usuario.correo
    )

    return {
        "mensaje": "Perfil obtenido correctamente",
        "usuario": {
            "id": usuario.id,
            "nombre": nombre,
            "correo": usuario.correo,
        },
    }
