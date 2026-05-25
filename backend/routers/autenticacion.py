from fastapi import APIRouter, HTTPException
from modelos.usuario import UsuarioRegistro, UsuarioLogin
from configuracion.supabase_cliente import supabase
import hashlib

router = APIRouter(
    prefix="/autenticacion",
    tags=["Autenticación"]
)


def encriptar_contrasena(contrasena: str):
    return hashlib.sha256(contrasena.encode()).hexdigest()


@router.post("/registro")
def registrar_usuario(usuario: UsuarioRegistro):
    usuario_existente = (
        supabase.table("usuarios")
        .select("*")
        .eq("correo", usuario.correo)
        .execute()
    )

    if len(usuario_existente.data) > 0:
        raise HTTPException(status_code=400, detail="El correo ya está registrado")

    nuevo_usuario = {
        "nombre": usuario.nombre,
        "correo": usuario.correo,
        "contrasena": encriptar_contrasena(usuario.contrasena)
    }

    resultado = (
        supabase.table("usuarios")
        .insert(nuevo_usuario)
        .execute()
    )

    usuario_creado = resultado.data[0]

    return {
        "mensaje": "Usuario registrado correctamente",
        "usuario": {
            "id": usuario_creado["id"],
            "nombre": usuario_creado["nombre"],
            "correo": usuario_creado["correo"]
        }
    }


@router.post("/login")
def iniciar_sesion(usuario: UsuarioLogin):
    resultado = (
        supabase.table("usuarios")
        .select("*")
        .eq("correo", usuario.correo)
        .execute()
    )

    if len(resultado.data) == 0:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")

    usuario_encontrado = resultado.data[0]

    if usuario_encontrado["contrasena"] != encriptar_contrasena(usuario.contrasena):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")

    return {
        "mensaje": "Inicio de sesión correcto",
        "usuario": {
            "id": usuario_encontrado["id"],
            "nombre": usuario_encontrado["nombre"],
            "correo": usuario_encontrado["correo"]
        }
    }