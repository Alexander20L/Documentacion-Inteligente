import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, inject, OnDestroy, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  NombreArchivoGraphify,
  ProyectoHistorial,
  RepositoriosService,
} from '../../servicios/repositorios.service';

type EstadoAnalisis =
  | 'SUBIDO'
  | 'PENDIENTE_ANALISIS'
  | 'ANALIZANDO_GRAPHIFY'
  | 'GRAPHIFY_COMPLETADO'
  | 'ERROR_ANALISIS'
  | string;

type EstadoDocumentacion =
  | 'PENDIENTE'
  | 'GENERANDO_DOCUMENTACION'
  | 'DOCUMENTACION_COMPLETADA'
  | 'ERROR_DOCUMENTACION'
  | string;

@Component({
  selector: 'app-historial-proyectos',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './historial-proyectos.html',
  styleUrl: './historial-proyectos.scss',
})
export class HistorialProyectos implements OnInit, OnDestroy {
  private repositoriosService = inject(RepositoriosService);
  private changeDetectorRef = inject(ChangeDetectorRef);

  private pollingId: ReturnType<typeof setInterval> | null = null;
  private componenteDestruido = false;
  private consultandoHistorial = false;

  proyectos: ProyectoHistorial[] = [];
  cargando = true;
  mensaje = '';
  mensajeError = '';
  proyectoProcesando = '';

  ngOnInit() {
    this.obtenerHistorial(true);
  }

  ngOnDestroy() {
    this.componenteDestruido = true;
    this.detenerPolling();
  }

  obtenerHistorial(mostrarCargando = false) {
    if (this.consultandoHistorial) return;

    this.consultandoHistorial = true;

    if (mostrarCargando) {
      this.cargando = true;
      this.refrescarVista();
    }

    this.repositoriosService.obtenerHistorial().subscribe({
      next: (respuesta) => {
        this.proyectos = respuesta.proyectos || [];
        this.cargando = false;
        this.consultandoHistorial = false;
        this.mensajeError = '';

        this.sincronizarProyectoProcesando();
        this.configurarPollingHistorial();
        this.refrescarVista();
      },
      error: (error) => {
        this.mensajeError = this.obtenerMensajeError(
          error,
          'No se pudo cargar el historial.'
        );
        this.proyectos = [];
        this.cargando = false;
        this.consultandoHistorial = false;
        this.detenerPolling();
        this.refrescarVista();
      },
    });
  }

generarDocumentacion(proyecto: ProyectoHistorial) {
  if (!this.puedeGenerarDocumentacion(proyecto)) return;

  this.proyectoProcesando = proyecto.id_repositorio;
  this.mensaje = '';
  this.mensajeError = '';

  // Actualización optimista para que la UI cambie inmediatamente.
  proyecto.estado_documentacion = 'GENERANDO_DOCUMENTACION';
  this.refrescarVista();

  this.repositoriosService.generarDocumentacion(proyecto.id_repositorio).subscribe({
    next: () => {
      this.mensaje = 'La documentación fue encolada correctamente.';

      // No llamamos obtenerHistorial inmediatamente porque puede traer todavía PENDIENTE.
      // El polling se encargará de refrescar cuando el worker actualice Supabase.
      this.iniciarPolling();
      this.refrescarVista();
    },
    error: (error) => {
      this.proyectoProcesando = '';
      proyecto.estado_documentacion = 'ERROR_DOCUMENTACION';

      this.mensajeError = this.obtenerMensajeError(
        error,
        'Error al generar documentación.'
      );

      this.refrescarVista();
    },
  });
}

  puedeGenerarDocumentacion(proyecto: ProyectoHistorial) {
    const estadoAnalisis = proyecto.estado as EstadoAnalisis;
    const estadoDocumentacion = proyecto.estado_documentacion as EstadoDocumentacion;

    if (estadoAnalisis !== 'GRAPHIFY_COMPLETADO') return false;
    if (estadoDocumentacion === 'GENERANDO_DOCUMENTACION') return false;

    return true;
  }

  puedeVerDocumentacion(proyecto: ProyectoHistorial) {
    return proyecto.estado_documentacion === 'DOCUMENTACION_COMPLETADA';
  }

  puedeDescargarWord(proyecto: ProyectoHistorial) {
    return Boolean(proyecto.url_word);
  }

  textoBotonDocumentacion(proyecto: ProyectoHistorial) {
    if (proyecto.estado_documentacion === 'ERROR_DOCUMENTACION') {
      return 'Reintentar documentación';
    }

    if (proyecto.estado_documentacion === 'DOCUMENTACION_COMPLETADA') {
      return 'Regenerar documentación';
    }

    if (
      proyecto.estado_documentacion === 'GENERANDO_DOCUMENTACION' ||
      this.proyectoProcesando === proyecto.id_repositorio
    ) {
      return 'Generando...';
    }

    return 'Generar documentación';
  }

  estadoAnalisisLegible(estado: string) {
    const estados: Record<string, string> = {
      SUBIDO: 'Subido',
      PENDIENTE_ANALISIS: 'En cola',
      ANALIZANDO_GRAPHIFY: 'Analizando',
      GRAPHIFY_COMPLETADO: 'Completado',
      ERROR_ANALISIS: 'Error',
    };

    return estados[estado] || estado;
  }

  estadoDocumentacionLegible(estado?: string) {
    const estados: Record<string, string> = {
      PENDIENTE: 'Pendiente',
      GENERANDO_DOCUMENTACION: 'Generando',
      DOCUMENTACION_COMPLETADA: 'Completada',
      ERROR_DOCUMENTACION: 'Error',
    };

    return estados[estado || ''] || estado || 'Pendiente';
  }

  claseEstadoAnalisis(estado: string) {
    const clases: Record<string, string> = {
      SUBIDO: 'estado-neutral',
      PENDIENTE_ANALISIS: 'estado-pendiente',
      ANALIZANDO_GRAPHIFY: 'estado-proceso',
      GRAPHIFY_COMPLETADO: 'estado-completado',
      ERROR_ANALISIS: 'estado-error',
    };

    return clases[estado] || 'estado-neutral';
  }

  claseEstadoDocumentacion(estado?: string) {
    const clases: Record<string, string> = {
      PENDIENTE: 'estado-neutral',
      GENERANDO_DOCUMENTACION: 'estado-proceso',
      DOCUMENTACION_COMPLETADA: 'estado-completado',
      ERROR_DOCUMENTACION: 'estado-error',
    };

    return clases[estado || ''] || 'estado-neutral';
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
        this.mensajeError = this.obtenerMensajeError(
          error,
          'No se pudo descargar el documento Word.'
        );
        this.refrescarVista();
      },
    });
  }

  trackByRepositorio(_: number, proyecto: ProyectoHistorial) {
    return proyecto.id_repositorio;
  }

  private abrirArchivo(
    idRepositorio: string,
    nombreArchivo: NombreArchivoGraphify,
    tipo: string
  ) {
    this.repositoriosService
      .obtenerArchivoGraphify(idRepositorio, nombreArchivo)
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

  private configurarPollingHistorial() {
    const hayTrabajoActivo = this.proyectos.some((proyecto) => {
      const estadoAnalisis = proyecto.estado;
      const estadoDocumentacion = proyecto.estado_documentacion;

      return (
        estadoAnalisis === 'PENDIENTE_ANALISIS' ||
        estadoAnalisis === 'ANALIZANDO_GRAPHIFY' ||
        estadoDocumentacion === 'GENERANDO_DOCUMENTACION'
      );
    });

    if (hayTrabajoActivo) {
      this.iniciarPolling();
      return;
    }

    this.proyectoProcesando = '';
    this.detenerPolling();
  }

  private sincronizarProyectoProcesando() {
  if (!this.proyectoProcesando) return;

  const proyecto = this.proyectos.find(
    (item) => item.id_repositorio === this.proyectoProcesando
  );

  if (!proyecto) {
    this.proyectoProcesando = '';
    return;
  }

  if (proyecto.estado_documentacion !== 'GENERANDO_DOCUMENTACION') {
    this.proyectoProcesando = '';
  }
}

  private iniciarPolling() {
    if (this.pollingId) return;

    this.pollingId = setInterval(() => {
      this.obtenerHistorial(false);
    }, 5000);
  }

  private detenerPolling() {
    if (this.pollingId) {
      clearInterval(this.pollingId);
      this.pollingId = null;
    }
  }

  private refrescarVista() {
    if (this.componenteDestruido) return;
    this.changeDetectorRef.detectChanges();
  }

  private obtenerMensajeError(error: any, fallback: string) {
    return error?.error?.detail || error?.message || fallback;
  }
}