import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, inject, OnDestroy } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  NombreArchivoGraphify,
  ProyectoHistorial,
  RepositoriosService,
} from '../../servicios/repositorios.service';

type FaseAnalisis =
  | 'inicial'
  | 'subiendo'
  | 'encolando'
  | 'analizando'
  | 'completado'
  | 'error';

type EstadoProyecto =
  | ''
  | 'SUBIDO'
  | 'PENDIENTE_ANALISIS'
  | 'ANALIZANDO_GRAPHIFY'
  | 'GRAPHIFY_COMPLETADO'
  | 'ERROR_ANALISIS'
  | string;

@Component({
  selector: 'app-analisis-proyecto',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './analisis-proyecto.html',
  styleUrl: './analisis-proyecto.scss',
})
export class AnalisisProyecto implements OnDestroy {
  private repositoriosService = inject(RepositoriosService);
  private changeDetectorRef = inject(ChangeDetectorRef);

  private pollingId: ReturnType<typeof setInterval> | null = null;
  private consultandoEstado = false;
  private componenteDestruido = false;

  archivoSeleccionado: File | null = null;

  fase: FaseAnalisis = 'inicial';

  idRepositorio = '';
  estadoProyecto: EstadoProyecto = '';

  mensaje = '';
  mensajeError = '';
  mensajeResultado = '';

  urlGrafo = '';
  urlJson = '';
  urlReporte = '';

  ngOnDestroy() {
    this.componenteDestruido = true;
    this.detenerPolling();
  }

  get cargando() {
    return (
      this.fase === 'subiendo' ||
      this.fase === 'encolando' ||
      this.fase === 'analizando'
    );
  }

  get puedeAnalizar() {
    return Boolean(this.archivoSeleccionado) && !this.cargando;
  }

  get analisisCompletado() {
    return this.fase === 'completado' || this.estadoProyecto === 'GRAPHIFY_COMPLETADO';
  }

  get analisisConError() {
    return this.fase === 'error' || this.estadoProyecto === 'ERROR_ANALISIS';
  }

  get textoBotonPrincipal() {
    const textos: Record<FaseAnalisis, string> = {
      inicial: 'Analizar repositorio',
      subiendo: 'Subiendo repositorio...',
      encolando: 'Encolando análisis...',
      analizando: 'Analizando repositorio...',
      completado: 'Analizar otro repositorio',
      error: 'Reintentar análisis',
    };

    return textos[this.fase];
  }

  get estadoLegible() {
    const estados: Record<string, string> = {
      SUBIDO: 'Repositorio subido',
      PENDIENTE_ANALISIS: 'Análisis en cola',
      ANALIZANDO_GRAPHIFY: 'Analizando con Graphify',
      GRAPHIFY_COMPLETADO: 'Análisis completado',
      ERROR_ANALISIS: 'Error en el análisis',
    };

    return estados[this.estadoProyecto] || this.estadoProyecto;
  }

  seleccionarArchivo(evento: Event) {
    const input = evento.target as HTMLInputElement;

    if (!input.files || input.files.length === 0) return;

    this.archivoSeleccionado = input.files[0];
    this.reiniciarEstadoPantalla();
  }

  subirYAnalizar() {
    if (!this.archivoSeleccionado) {
      this.finalizarConError('Selecciona un archivo ZIP primero.');
      return;
    }

    this.reiniciarEstadoPantalla();

    this.fase = 'subiendo';
    this.mensaje = 'Subiendo repositorio...';
    this.refrescarVista();

    this.repositoriosService.subirRepositorio(this.archivoSeleccionado).subscribe({
      next: (respuestaSubida) => {
        this.idRepositorio = respuestaSubida.id_repositorio;
        this.estadoProyecto = 'SUBIDO';

        this.fase = 'encolando';
        this.mensaje = 'Repositorio subido. Encolando análisis...';
        this.refrescarVista();

        this.encolarAnalisis(
          respuestaSubida.id_repositorio,
          respuestaSubida.nombre_archivo
        );
      },
      error: (error) => {
        this.finalizarConError(
          this.obtenerMensajeError(error, 'No se pudo subir el repositorio.')
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

  private encolarAnalisis(idRepositorio: string, nombreArchivo: string) {
    this.repositoriosService
      .analizarRepositorio(idRepositorio, nombreArchivo)
      .subscribe({
        next: (respuestaAnalisis) => {
          this.idRepositorio = respuestaAnalisis.id_repositorio;
          this.estadoProyecto =
            respuestaAnalisis.estado || 'PENDIENTE_ANALISIS';

          this.fase = 'analizando';
          this.mensaje = 'El análisis fue encolado correctamente.';
          this.refrescarVista();

          this.iniciarPollingEstado();
        },
        error: (error) => {
          this.finalizarConError(
            this.obtenerMensajeError(error, 'No se pudo analizar el repositorio.')
          );
        },
      });
  }

  private iniciarPollingEstado() {
    this.detenerPolling();

    this.fase = 'analizando';
    this.refrescarVista();

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
    if (!this.idRepositorio || this.consultandoEstado) return;

    this.consultandoEstado = true;

    this.repositoriosService.obtenerEstadoProyecto(this.idRepositorio).subscribe({
      next: (respuestaEstado) => {
        this.consultandoEstado = false;

        const proyecto = respuestaEstado.proyecto;
        const tareaAnalisis = respuestaEstado.tareas.find(
          (tarea) => tarea.tipo === 'analisis'
        );

        this.actualizarEstadoAnalisis(proyecto);

        if (
          tareaAnalisis?.estado === 'fallido' ||
          proyecto.estado === 'ERROR_ANALISIS'
        ) {
          this.finalizarConError(
            proyecto.error_ultimo ||
              tareaAnalisis?.error_ultimo ||
              'El análisis falló.'
          );
          return;
        }

        if (
          tareaAnalisis?.estado === 'completado' ||
          proyecto.estado === 'GRAPHIFY_COMPLETADO'
        ) {
          this.finalizarComoCompletado();
          return;
        }

        this.fase = 'analizando';
        this.mensaje = this.obtenerMensajeProceso(proyecto.estado);
        this.refrescarVista();
      },
      error: (error) => {
        this.consultandoEstado = false;

        this.finalizarConError(
          this.obtenerMensajeError(
            error,
            'No se pudo consultar el estado del análisis.'
          )
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

    this.urlGrafo = archivos.html || proyecto.url_graph_html || '';
    this.urlJson = archivos.json || proyecto.url_graph_json || '';
    this.urlReporte = archivos.reporte || proyecto.url_reporte || '';

    this.mensajeResultado = [
      !disponibles.html ? mensajes.html : '',
      !disponibles.reporte ? mensajes.reporte : '',
    ]
      .filter(Boolean)
      .join(' ');
  }

  private finalizarComoCompletado() {
    this.detenerPolling();

    this.fase = 'completado';
    this.estadoProyecto = 'GRAPHIFY_COMPLETADO';
    this.mensaje = 'Análisis completado correctamente.';
    this.mensajeError = '';

    this.refrescarVista();
  }

  private finalizarConError(mensaje: string) {
    this.detenerPolling();

    this.fase = 'error';
    this.mensaje = '';
    this.mensajeError = mensaje || 'Ocurrió un error inesperado durante el análisis.';

    this.refrescarVista();
  }

  private abrirArchivo(nombreArchivo: NombreArchivoGraphify, tipo: string) {
    if (!this.idRepositorio) return;

    this.repositoriosService
      .obtenerArchivoGraphify(this.idRepositorio, nombreArchivo)
      .subscribe({
        next: (blob) => {
          const url = URL.createObjectURL(new Blob([blob], { type: tipo }));

          window.open(url, '_blank', 'noopener');

          setTimeout(() => URL.revokeObjectURL(url), 60000);
        },
        error: (error) => {
          this.mensajeError = this.obtenerMensajeError(
            error,
            'No se pudo abrir el archivo solicitado.'
          );

          this.refrescarVista();
        },
      });
  }

  private obtenerMensajeProceso(estado: string) {
    const mensajes: Record<string, string> = {
      SUBIDO: 'Repositorio subido. Preparando análisis...',
      PENDIENTE_ANALISIS: 'El análisis está en cola.',
      ANALIZANDO_GRAPHIFY: 'Graphify está analizando el repositorio.',
    };

    return mensajes[estado] || `Estado actual: ${estado}`;
  }

  private reiniciarEstadoPantalla() {
    this.detenerPolling();

    this.consultandoEstado = false;
    this.fase = 'inicial';

    this.idRepositorio = '';
    this.estadoProyecto = '';

    this.mensaje = '';
    this.mensajeError = '';
    this.mensajeResultado = '';

    this.urlGrafo = '';
    this.urlJson = '';
    this.urlReporte = '';

    this.refrescarVista();
  }

  private refrescarVista() {
    if (this.componenteDestruido) return;

    this.changeDetectorRef.detectChanges();
  }

  private obtenerMensajeError(error: any, fallback: string) {
    return error?.error?.detail || error?.message || fallback;
  }
}