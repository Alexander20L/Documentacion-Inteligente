import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AutenticacionService } from '../../servicios/autenticacion.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login {
  private autenticacionService = inject(AutenticacionService);
  private router = inject(Router);

  correo = '';
  contrasena = '';

  login() {
    const datos = {
      correo: this.correo,
      contrasena: this.contrasena,
    };

    this.autenticacionService.login(datos).subscribe({
      next: (respuesta: any) => {
        localStorage.setItem('usuario', JSON.stringify(respuesta.usuario));
        this.router.navigate(['/dashboard']);
      },
      error: (error) => {
        console.error(error);
        alert(error.error.detail);
      },
    });
  }
}