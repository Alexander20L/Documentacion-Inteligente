import { CommonModule } from '@angular/common';
import { Component, DestroyRef, inject, OnDestroy, OnInit } from '@angular/core';
import { RouterLink, ActivatedRoute } from '@angular/router';
import { EMPTY, timer } from 'rxjs';
import { catchError, switchMap, takeWhile } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ArtefactoC4, DiagramaC4, EjecucionC4 } from '../../modelos/c4.model';
import { C4Service } from '../../servicios/c4.service';
import { ProgresoC4 } from '../../componentes/progreso-c4/progreso-c4';
import {
  LucideArrowLeft,
  LucideDownload,
  LucideExternalLink,
  LucideFileArchive,
  LucideFileCode2,
  LucideFileText,
  LucideImage,
  LucideLoaderCircle,
  LucidePackageOpen,
  LucideZoomIn,
} from '@lucide/angular';

interface DiagramaVisible extends DiagramaC4 {
  url: string;
}

export interface GrupoArtefactosC4 {
  titulo: string;
  clave: 'semantica' | 'rag' | 'agentes' | 'c4';
  artefactos: ArtefactoC4[];
}

export function agruparArtefactos(artefactos: ArtefactoC4[]): GrupoArtefactosC4[] {
  const grupos: GrupoArtefactosC4[] = [
    { titulo: 'Indice semantico', clave: 'semantica', artefactos: [] },
    { titulo: 'RAG y evidencia', clave: 'rag', artefactos: [] },
    { titulo: 'Revision multiagente', clave: 'agentes', artefactos: [] },
    { titulo: 'Modelo C4', clave: 'c4', artefactos: [] },
  ];
  for (const artefacto of artefactos) {
    const clasificacion = `${artefacto.tipo ?? ''} ${artefacto.etiqueta ?? ''}`.toLowerCase();
    let clave: GrupoArtefactosC4['clave'] = 'c4';
    if (/agente|juez|conflicto|hu[eé]rfano/.test(clasificacion)) clave = 'agentes';
    else if (/rag|evidencia|recuperaci[oó]n/.test(clasificacion)) clave = 'rag';
    else if (/sem[aá]ntic|indice|índice|chunk|vector/.test(clasificacion)) clave = 'semantica';
    grupos.find((grupo) => grupo.clave === clave)?.artefactos.push(artefacto);
  }
  return grupos.filter((grupo) => grupo.artefactos.length);
}

@Component({
  selector: 'app-resultado-c4',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    ProgresoC4,
    LucideArrowLeft,
    LucideDownload,
    LucideExternalLink,
    LucideFileArchive,
    LucideFileCode2,
    LucideFileText,
    LucideImage,
    LucideLoaderCircle,
    LucidePackageOpen,
    LucideZoomIn,
  ],
  templateUrl: './resultado-c4.html',
  styleUrl: './resultado-c4.scss',
})
export class ResultadoC4 implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly c4Service = inject(C4Service);
  private readonly destroyRef = inject(DestroyRef);
  private readonly urls = new Set<string>();

  readonly idRepositorio = this.route.snapshot.paramMap.get('idRepositorio') ?? '';
  readonly idEjecucion = this.route.snapshot.paramMap.get('idEjecucion') ?? '';

  ejecucion: EjecucionC4 | null = null;
  diagramas: DiagramaVisible[] = [];
  cargando = true;
  mensajeError = '';
  descargaActiva = '';
  avisoRed = '';
  accionEnCurso = false;
  diagramasConError: string[] = [];

  ngOnInit() {
    if (!this.idRepositorio || !this.idEjecucion) {
      this.cargando = false;
      this.mensajeError = 'La ruta del resultado no es valida.';
      return;
    }

    this.iniciarPolling();
  }

  cancelar() {
    if (!globalThis.confirm('¿Cancelar la publicación? Los artefactos incompletos no se publicarán.')) return;
    this.ejecutarAccion('cancelar');
  }

  reintentar() {
    this.ejecutarAccion('reintentar');
  }

  private iniciarPolling() {
    timer(0, 4000)
      .pipe(
        switchMap(() =>
          this.c4Service.obtenerEjecucion(this.idRepositorio, this.idEjecucion).pipe(
            catchError((error) => {
              this.cargando = false;
              this.avisoRed = `${this.obtenerError(error, 'No se pudo consultar la ejecucion.')} Se reintentara automaticamente.`;
              return EMPTY;
            }),
          ),
        ),
        takeWhile((ejecucion) => this.estaActiva(ejecucion), true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((ejecucion) => {
        this.ejecucion = ejecucion;
        this.cargando = false;
        this.avisoRed = '';
        if (ejecucion.diagramas.length && !this.estaActiva(ejecucion)) {
          this.cargarDiagramas(ejecucion.diagramas);
        }
      });
  }

  ngOnDestroy() {
    this.urls.forEach((url) => URL.revokeObjectURL(url));
  }

  descargar(idArtefacto: string, nombre: string) {
    this.descargaActiva = nombre;
    this.mensajeError = '';
    this.c4Service
      .descargarArtefacto(this.idRepositorio, this.idEjecucion, idArtefacto)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          const url = URL.createObjectURL(blob);
          const enlace = document.createElement('a');
          enlace.href = url;
          enlace.download = nombre;
          enlace.click();
          URL.revokeObjectURL(url);
          this.descargaActiva = '';
        },
        error: (error) => {
          this.descargaActiva = '';
          this.mensajeError = this.obtenerError(error, 'No se pudo descargar el artefacto.');
        },
      });
  }

  estadoLegible(estado: string) {
    const estados: Record<string, string> = {
      pendiente: 'Pendiente',
      procesando: 'En proceso',
      completado: 'Completada',
      fallido: 'Fallida',
      cancelado: 'Cancelada',
    };
    return estados[estado] || estado;
  }

  gruposArtefactos(artefactos: ArtefactoC4[]) {
    return agruparArtefactos(artefactos);
  }

  claseEstado(estado: string) {
    if (estado === 'completado') return 'estado-completado';
    if (estado === 'fallido' || estado === 'cancelado') return 'estado-error';
    if (estado === 'pendiente') return 'estado-pendiente';
    return 'estado-proceso';
  }

  tipoArchivo(artefacto: ArtefactoC4) {
    const nombre = `${artefacto.nombre} ${artefacto.tipo ?? ''}`.toLowerCase();
    if (/\.(png|svg|jpe?g|webp)\b|imagen|diagrama/.test(nombre)) return 'imagen';
    if (/\.(zip|tar|gz)\b|archivo/.test(nombre)) return 'comprimido';
    if (/\.(json|ya?ml|dsl|puml|mmd)\b|c[oó]digo|structurizr/.test(nombre)) return 'codigo';
    return 'documento';
  }

  private cargarDiagramas(diagramas: DiagramaC4[]) {
    diagramas.forEach((diagrama) => {
      if (this.diagramas.some((visible) => visible.nombre === diagrama.nombre)) return;
      this.c4Service
        .descargarArtefacto(this.idRepositorio, this.idEjecucion, diagrama.id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (blob) => {
            const url = URL.createObjectURL(blob);
            this.urls.add(url);
            this.diagramas = [...this.diagramas, { ...diagrama, url }];
          },
          error: () => {
            this.diagramasConError = [...this.diagramasConError, diagrama.nombre];
            this.mensajeError = `No se pudo mostrar el diagrama ${diagrama.nombre}.`;
          },
        });
    });
  }

  private ejecutarAccion(accion: 'cancelar' | 'reintentar') {
    if (this.accionEnCurso) return;
    this.accionEnCurso = true;
    this.mensajeError = '';
    const solicitud =
      accion === 'cancelar'
        ? this.c4Service.cancelarEjecucion(this.idRepositorio, this.idEjecucion)
        : this.c4Service.reintentarEjecucion(this.idRepositorio, this.idEjecucion);
    solicitud.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (ejecucion) => {
        this.ejecucion = ejecucion;
        this.accionEnCurso = false;
        if (accion === 'reintentar') this.iniciarPolling();
      },
      error: (error) => {
        this.accionEnCurso = false;
        this.mensajeError = this.obtenerError(error, `No se pudo ${accion} la ejecucion.`);
      },
    });
  }

  private estaActiva(ejecucion: EjecucionC4) {
    return !['completado', 'fallido', 'cancelado'].includes(ejecucion.estado);
  }

  private obtenerError(error: unknown, fallback: string) {
    const respuesta = error as { error?: { detail?: string }; message?: string };
    return respuesta.error?.detail || respuesta.message || fallback;
  }
}
