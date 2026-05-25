import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, inject, OnInit } from '@angular/core';
import { RepositoriosService } from '../../servicios/repositorios.service';
import { RouterLink } from '@angular/router';
import { API_BASE_URL } from '../../servicios/api.config';

@Component({
  selector: 'app-historial-proyectos',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './historial-proyectos.html',
  styleUrl: './historial-proyectos.scss',
})
export class HistorialProyectos implements OnInit {
  private repositoriosService = inject(RepositoriosService);
  private detectorCambios = inject(ChangeDetectorRef);

  apiBaseUrl = API_BASE_URL;
  proyectos: any[] = [];
  cargando = true;

  ngOnInit() {
    this.obtenerHistorial();
  }

  obtenerHistorial() {
    this.repositoriosService.obtenerHistorial().subscribe({
      next: (respuesta: any) => {
        console.log('Historial de proyectos:', respuesta);

        this.proyectos = respuesta.proyectos || [];
        this.cargando = false;

        this.detectorCambios.detectChanges();
      },
      error: (error) => {
        console.error('Error historial:', error);

        this.proyectos = [];
        this.cargando = false;

        this.detectorCambios.detectChanges();
      },
    });
  }

  generarDocumentacion(idRepositorio: string) {
  this.repositoriosService.generarDocumentacion(idRepositorio).subscribe({
    next: (respuesta: any) => {
      console.log('Documentación generada:', respuesta);
      alert('Documentación generada correctamente');
    },
    error: (error) => {
      console.error(error);
      alert(error.error.detail || 'Error al generar documentación');
    },
  });
}
}