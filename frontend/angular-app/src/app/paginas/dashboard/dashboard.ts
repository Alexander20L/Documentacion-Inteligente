import { Component } from '@angular/core';
import { inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { AutenticacionService } from '../../servicios/autenticacion.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class Dashboard {
  private authService = inject(AutenticacionService);
  private router = inject(Router);

  usuario = this.authService.usuarioActual;

  async cerrarSesion() {
    await this.authService.logout();
    await this.router.navigate(['/login']);
  }
}
