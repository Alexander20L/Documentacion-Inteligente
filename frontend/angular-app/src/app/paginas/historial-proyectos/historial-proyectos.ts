import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, DestroyRef, inject, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  LucideArrowLeft,
  LucideArrowRight,
  LucideCalendarDays,
  LucideCircleCheck,
  LucideCircleDashed,
  LucideCircleX,
  LucideClock3,
  LucideFolderGit2,
  LucideHistory,
  LucideLoaderCircle,
  LucideRefreshCw,
  LucideScanSearch,
} from '@lucide/angular';
import { EMPTY, merge, Subject, timer } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ResumenEjecucionC4 } from '../../modelos/c4.model';
import { C4Service } from '../../servicios/c4.service';
import { ProgresoC4 } from '../../componentes/progreso-c4/progreso-c4';

@Component({
  selector: 'app-historial-proyectos',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    ProgresoC4,
    LucideArrowLeft,
    LucideArrowRight,
    LucideCalendarDays,
    LucideCircleCheck,
    LucideCircleDashed,
    LucideCircleX,
    LucideClock3,
    LucideFolderGit2,
    LucideHistory,
    LucideLoaderCircle,
    LucideRefreshCw,
    LucideScanSearch,
  ],
  templateUrl: './historial-proyectos.html',
  styleUrl: './historial-proyectos.scss',
})
export class HistorialProyectos implements OnInit {
  private readonly c4Service = inject(C4Service);
  private readonly destroyRef = inject(DestroyRef);
  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly actualizacionManual = new Subject<void>();

  ejecuciones: ResumenEjecucionC4[] = [];
  cargando = true;
  actualizando = false;
  mensajeError = '';

  ngOnInit() {
    merge(timer(0, 30000), this.actualizacionManual)
      .pipe(
        switchMap(() =>
          this.c4Service.obtenerHistorial().pipe(
            catchError((error) => {
              this.cargando = false;
              this.actualizando = false;
              this.mensajeError = `${this.obtenerError(error, 'No se pudo cargar el historial C4.')} Se conservaran los datos visibles y se reintentara automaticamente.`;
              this.changeDetector.markForCheck();
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((respuesta) => {
        this.ejecuciones = respuesta.ejecuciones;
        this.cargando = false;
        this.actualizando = false;
        this.mensajeError = '';
        this.changeDetector.markForCheck();
      });
  }

  actualizarHistorial() {
    if (this.actualizando) return;
    this.actualizando = true;
    this.actualizacionManual.next();
  }

  rutaPrincipal(ejecucion: ResumenEjecucionC4) {
    const destino = ejecucion.fase === 'revision' ? 'revision' : 'resultado';
    return ['/c4', ejecucion.id_repositorio, 'ejecuciones', ejecucion.id, destino];
  }

  textoAccion(ejecucion: ResumenEjecucionC4) {
    return ejecucion.fase === 'revision' ? 'Revisar candidatos' : 'Ver ejecucion';
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

  claseEstado(estado: string) {
    if (estado === 'completado') return 'estado-completado';
    if (estado === 'fallido' || estado === 'cancelado') return 'estado-error';
    if (estado === 'pendiente') return 'estado-pendiente';
    return 'estado-proceso';
  }

  iconoEstado(estado: string) {
    if (estado === 'completado') return 'completado';
    if (estado === 'fallido' || estado === 'cancelado') return 'error';
    if (estado === 'pendiente') return 'pendiente';
    return 'proceso';
  }

  trackByEjecucion(_: number, ejecucion: ResumenEjecucionC4) {
    return ejecucion.id;
  }

  estaActiva(ejecucion: ResumenEjecucionC4) {
    if (ejecucion.fase === 'revision') return false;
    const estado = ejecucion.tarea_actual?.estado ?? ejecucion.estado;
    return ['pendiente', 'procesando'].includes(estado);
  }

  private obtenerError(error: unknown, fallback: string) {
    const respuesta = error as { error?: { detail?: string }; message?: string };
    return respuesta.error?.detail || respuesta.message || fallback;
  }
}
