import { CommonModule } from '@angular/common';
import { Component, inject, OnDestroy } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  NombreArchivoGraphify,
  ProyectoHistorial,
  RepositoriosService,
} from '../../servicios/repositorios.service';

@Component({
  selector: 'app-analisis-proyecto',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './analisis-proyecto.html',
  styleUrl: './analisis-proyecto.scss',
})
export class AnalisisProyecto implements OnDestroy {
  private repositoriosService = inject(RepositoriosService);
  private pollingId: ReturnType<typeof setInterval> | null = null;

  archivoSeleccionado: File | null = null;
  cargando = false;
  mensaje = '';
  idRepositorio = '';
  estadoProyecto = '';

  urlGrafo = '';
  urlJson = '';
  urlReporte = '';
  mensajeResultado = '';

  ngOnDestroy() {
    this.detenerPolling();
  }

  seleccionarArchivo(evento: Event) {
    const input = evento.target as HTMLInputElement;

    if (!input.files || input.files.length === 0) return;

    this.archivoSeleccionado = input.files[0];
    this.idRepositorio = '';
    this.mensaje = '';

    this.urlGrafo = '';
    this.urlJson = '';
    this.urlReporte = '';
    this.mensajeResultado = '';
  }

  subirYAnalizar() {
    if (!this.archivoSeleccionado) {
      this.mensaje = 'Selecciona un archivo ZIP primero.';
      return;
    }

    this.cargando = true;
    this.mensaje = '';

    this.urlGrafo = '';
    this.urlJson = '';
    this.urlReporte = '';
    this.mensajeResultado = '';
    this.estadoProyecto = '';

    this.repositoriosService.subirRepositorio(this.archivoSeleccionado).subscribe({
      next: (respuestaSubida) => {
        this.repositoriosService
          .analizarRepositorio(respuestaSubida.id_repositorio, respuestaSubida.nombre_archivo)
          .subscribe({
            next: (respuestaAnalisis) => {
              this.idRepositorio = respuestaAnalisis.id_repositorio;
              this.estadoProyecto = respuestaAnalisis.estado || 'pendiente_analisis';
              this.mensaje = 'Repositorio subido. El análisis fue encolado correctamente.';
              this.iniciarPollingEstado();
            },
            error: (error) => {
              this.cargando = false;
              this.mensaje = this.obtenerMensajeError(
                error,
                'No se pudo analizar el repositorio.'
              );
            },
          });
      },
      error: (error) => {
        this.cargando = false;
        this.mensaje = this.obtenerMensajeError(
          error,
          'No se pudo subir el repositorio.'
        );
      },
    });
  }

  abrirGrafo() {
    this.abrirArchivo('graph.html', 'text/html');
  }

  abrirJson() {
    this.abrirArchivo('graph.json', 'application/json');
  }

  abrirReporte() {
    this.abrirArchivo('GRAPH_REPORT.md', 'text/markdown');
  }

  private iniciarPollingEstado() {
    this.detenerPolling();
    this.cargando = true;
    this.consultarEstadoProyecto();
    this.pollingId = setInterval(() => this.consultarEstadoProyecto(), 4000);
  }

  private detenerPolling() {
    if (this.pollingId) {
      clearInterval(this.pollingId);
      this.pollingId = null;
    }
  }

  private consultarEstadoProyecto() {
    if (!this.idRepositorio) {
      return;
    }

    this.repositoriosService.obtenerEstadoProyecto(this.idRepositorio).subscribe({
      next: (respuestaEstado) => {
        this.actualizarEstadoAnalisis(respuestaEstado.proyecto);

        const tareaAnalisis = respuestaEstado.tareas.find((tarea) => tarea.tipo === 'analisis');
        const estadoAnalisis = respuestaEstado.proyecto.estado;

        if (tareaAnalisis?.estado === 'fallido' || estadoAnalisis === 'fallido') {
          this.cargando = false;
          this.detenerPolling();
          this.mensaje = respuestaEstado.proyecto.error_ultimo || 'El análisis falló.';
          return;
        }

        if (estadoAnalisis === 'analizado') {
          this.cargando = false;
          this.detenerPolling();
          this.mensaje = 'Análisis completado correctamente.';
          return;
        }

        this.cargando = true;
        this.mensaje = `Estado actual: ${estadoAnalisis}`;
      },
      error: (error) => {
        this.cargando = false;
        this.detenerPolling();
        this.mensaje = this.obtenerMensajeError(
          error,
          'No se pudo consultar el estado del análisis.'
        );
      },
    });
  }

  private actualizarEstadoAnalisis(proyecto: ProyectoHistorial) {
    const archivos = proyecto.archivos || {};
    const disponibles = proyecto.disponibles || {};
    const mensajes = proyecto.mensajes || {};

    this.idRepositorio = proyecto.id_repositorio;
    this.estadoProyecto = proyecto.estado;
    this.urlGrafo = archivos.html || '';
    this.urlJson = archivos.json || '';
    this.urlReporte = archivos.reporte || '';
    this.mensajeResultado = [
      !disponibles.html ? mensajes.html : '',
      !disponibles.reporte ? mensajes.reporte : '',
    ]
      .filter(Boolean)
      .join(' ');
  }

  private abrirArchivo(nombreArchivo: NombreArchivoGraphify, tipo: string) {
    if (!this.idRepositorio) {
      return;
    }

    this.repositoriosService
      .obtenerArchivoGraphify(this.idRepositorio, nombreArchivo)
      .subscribe({
        next: (blob) => {
          const url = URL.createObjectURL(new Blob([blob], { type: tipo }));
          window.open(url, '_blank', 'noopener');
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        },
        error: (error) => {
          this.mensaje = this.obtenerMensajeError(
            error,
            'No se pudo abrir el archivo solicitado.'
          );
        },
      });
  }

  private obtenerMensajeError(error: any, fallback: string) {
    return error?.error?.detail || fallback;
  }
}
