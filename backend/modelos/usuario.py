from pydantic import BaseModel, EmailStr


class UsuarioRegistro(BaseModel):
    nombre: str
    correo: EmailStr
    contrasena: str


class UsuarioLogin(BaseModel):
    correo: EmailStr
    contrasena: str