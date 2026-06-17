import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AutenticacionService } from '../../servicios/autenticacion.service';

@Component({
  selector: 'app-registro',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './registro.html',
  styleUrl: './registro.scss',
})
export class Registro {
  private autenticacionService = inject(AutenticacionService);
  private router = inject(Router);

  nombre = '';
  correo = '';
  contrasena = '';
  cargando = false;
  error = '';
  mensaje = '';

  async registrar() {
    if (this.cargando) {
      return;
    }

    this.error = '';
    this.mensaje = '';
    this.cargando = true;

    try {
      const respuesta = await this.autenticacionService.registrar({
        nombre: this.nombre,
        correo: this.correo,
        contrasena: this.contrasena,
      });

      if (respuesta.session) {
        await this.router.navigate(['/dashboard']);
        return;
      }

      this.mensaje =
        'Cuenta creada. Revisa tu correo para confirmar el registro antes de iniciar sesión.';
    } catch (error) {
      this.error = this.autenticacionService.obtenerMensajeError(
        error,
        'No se pudo crear la cuenta'
      );
    } finally {
      this.cargando = false;
    }
  }
}
