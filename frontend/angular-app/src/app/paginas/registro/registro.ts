import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AutenticacionService } from '../../servicios/autenticacion.service';

@Component({
  selector: 'app-registro',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './registro.html',
  styleUrl: './registro.scss',
})
export class Registro {
  private autenticacionService = inject(AutenticacionService);

  nombre = '';
  correo = '';
  contrasena = '';

  registrar() {
    const datos = {
      nombre: this.nombre,
      correo: this.correo,
      contrasena: this.contrasena,
    };

    this.autenticacionService.registrar(datos).subscribe({
      next: (respuesta) => {
        console.log(respuesta);
        alert('Usuario registrado correctamente');
      },
      error: (error) => {
        console.error(error);
        alert(error.error.detail);
      },
    });
  }
}