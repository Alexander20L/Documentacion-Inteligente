import { CommonModule } from '@angular/common';
import { Component, inject, OnDestroy, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  NombreArchivoGraphify,
  ProyectoHistorial,
  RepositoriosService,
} from '../../servicios/repositorios.service';

@Component({
  selector: 'app-historial-proyectos',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './historial-proyectos.html',
  styleUrl: './historial-proyectos.scss',
})
export class HistorialProyectos implements OnInit, OnDestroy {
  private repositoriosService = inject(RepositoriosService);
  private pollingId: ReturnType<typeof setInterval> | null = null;

  proyectos: ProyectoHistorial[] = [];
  cargando = true;
  mensaje = '';
  proyectoProcesando = '';

  ngOnInit() {
    this.obtenerHistorial();
  }

  ngOnDestroy() {
    this.detenerPolling();
  }

  obtenerHistorial() {
    this.cargando = true;
    this.repositoriosService.obtenerHistorial().subscribe({
      next: (respuesta) => {
        this.proyectos = respuesta.proyectos || [];
        this.cargando = false;
        this.configurarPollingHistorial();
      },
      error: (error) => {
        this.mensaje = error?.error?.detail || 'No se pudo cargar el historial.';
        this.proyectos = [];
        this.cargando = false;
        this.detenerPolling();
      },
    });
  }

  generarDocumentacion(idRepositorio: string) {
    this.proyectoProcesando = idRepositorio;
    this.mensaje = '';

    this.repositoriosService.generarDocumentacion(idRepositorio).subscribe({
      next: () => {
        this.proyectoProcesando = idRepositorio;
        this.mensaje = 'La documentación fue encolada correctamente.';
        this.iniciarPolling();
        this.obtenerHistorial();
      },
      error: (error) => {
        this.proyectoProcesando = '';
        this.mensaje = error?.error?.detail || 'Error al generar documentación.';
      },
    });
  }

  puedeGenerarDocumentacion(proyecto: ProyectoHistorial) {
    return (
      proyecto.estado === 'analizado' &&
      proyecto.estado_documentacion !== 'procesando' &&
      proyecto.estado_documentacion !== 'pendiente'
    );
  }

  fechaProyecto(proyecto: ProyectoHistorial) {
    return proyecto.creado_en || proyecto.created_at || null;
  }

  abrirJson(idRepositorio: string) {
    this.abrirArchivo(idRepositorio, 'graph.json', 'application/json');
  }

  abrirReporte(idRepositorio: string) {
    this.abrirArchivo(idRepositorio, 'GRAPH_REPORT.md', 'text/markdown');
  }

  abrirGrafo(idRepositorio: string) {
    this.abrirArchivo(idRepositorio, 'graph.html', 'text/html');
  }

  descargarWord(idRepositorio: string) {
    this.repositoriosService.descargarWord(idRepositorio).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(
          new Blob([blob], {
            type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          })
        );
        const enlace = document.createElement('a');
        enlace.href = url;
        enlace.download = 'DOCUMENTACION_TECNICA.docx';
        enlace.click();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      },
      error: (error) => {
        this.mensaje = error?.error?.detail || 'No se pudo descargar el documento Word.';
      },
    });
  }

  private abrirArchivo(idRepositorio: string, nombreArchivo: NombreArchivoGraphify, tipo: string) {
    this.repositoriosService.obtenerArchivoGraphify(idRepositorio, nombreArchivo).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(new Blob([blob], { type: tipo }));
        window.open(url, '_blank', 'noopener');
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      },
      error: (error) => {
        this.mensaje = error?.error?.detail || 'No se pudo abrir el archivo solicitado.';
      },
    });
  }

  private configurarPollingHistorial() {
    const hayTrabajoActivo = this.proyectos.some(
      (proyecto) =>
        proyecto.estado === 'pendiente_analisis' ||
        proyecto.estado === 'analizando' ||
        proyecto.estado_documentacion === 'pendiente' ||
        proyecto.estado_documentacion === 'procesando'
    );

    if (hayTrabajoActivo) {
      this.iniciarPolling();
      return;
    }

    this.proyectoProcesando = '';
    this.detenerPolling();
  }

  private iniciarPolling() {
    if (this.pollingId) {
      return;
    }

    this.pollingId = setInterval(() => {
      this.repositoriosService.obtenerHistorial().subscribe({
        next: (respuesta) => {
          this.proyectos = respuesta.proyectos || [];
          this.configurarPollingHistorial();
        },
      });
    }, 5000);
  }

  private detenerPolling() {
    if (this.pollingId) {
      clearInterval(this.pollingId);
      this.pollingId = null;
    }
  }
}
