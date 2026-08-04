import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import {
  LucideArrowRight,
  LucideEye,
  LucideEyeOff,
  LucideLoaderCircle,
  LucideNetwork,
} from '@lucide/angular';
import { AutenticacionService } from '../../servicios/autenticacion.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    LucideArrowRight,
    LucideEye,
    LucideEyeOff,
    LucideLoaderCircle,
    LucideNetwork,
  ],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login {
  private autenticacionService = inject(AutenticacionService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  correo = '';
  contrasena = '';
  mostrarContrasena = false;
  cargando = false;
  error = '';

  async login() {
    if (this.cargando) {
      return;
    }

    this.error = '';
    this.cargando = true;

    try {
      await this.autenticacionService.login({
        correo: this.correo,
        contrasena: this.contrasena,
      });

      const redirectTo =
        this.route.snapshot.queryParamMap.get('redirectTo') || '/dashboard';

      await this.router.navigateByUrl(redirectTo);
    } catch (error) {
      this.error = this.autenticacionService.obtenerMensajeError(
        error,
        'No se pudo iniciar sesión'
      );
    } finally {
      this.cargando = false;
    }
  }
}
