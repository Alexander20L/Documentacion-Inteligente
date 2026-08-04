import { Component, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import {
  LucideHistory,
  LucideLayoutDashboard,
  LucideLogOut,
  LucideMenu,
  LucideNetwork,
  LucideScanSearch,
  LucideX,
} from '@lucide/angular';
import { AutenticacionService } from '../../servicios/autenticacion.service';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    LucideHistory,
    LucideLayoutDashboard,
    LucideLogOut,
    LucideMenu,
    LucideNetwork,
    LucideScanSearch,
    LucideX,
  ],
  templateUrl: './app-shell.html',
  styleUrl: './app-shell.scss',
})
export class AppShell {
  private readonly auth = inject(AutenticacionService);
  private readonly router = inject(Router);

  readonly usuario = this.auth.usuarioActual;
  readonly menuAbierto = signal(false);

  cerrarMenu() {
    this.menuAbierto.set(false);
  }

  async cerrarSesion() {
    await this.auth.logout();
    await this.router.navigate(['/login']);
  }
}
