import { CommonModule } from '@angular/common';
import { DestroyRef, Component, inject } from '@angular/core';
import { FormArray, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import {
  LucideArrowLeft,
  LucideArrowRight,
  LucideCheck,
  LucideFileArchive,
  LucidePlay,
  LucidePlus,
  LucideTrash2,
  LucideUpload,
} from '@lucide/angular';
import { EMPTY, timer } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EjecucionC4 } from '../../modelos/c4.model';
import { C4Service } from '../../servicios/c4.service';
import { RepositoriosService } from '../../servicios/repositorios.service';
import { ProgresoC4 } from '../../componentes/progreso-c4/progreso-c4';

type FilaContexto = FormGroup<{
  nombre: FormControl<string>;
  descripcion: FormControl<string>;
}>;

@Component({
  selector: 'app-analisis-proyecto',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterLink,
    ProgresoC4,
    LucideArrowLeft,
    LucideArrowRight,
    LucideCheck,
    LucideFileArchive,
    LucidePlay,
    LucidePlus,
    LucideTrash2,
    LucideUpload,
  ],
  templateUrl: './analisis-proyecto.html',
  styleUrl: './analisis-proyecto.scss',
})
export class AnalisisProyecto {
  private readonly repositoriosService = inject(RepositoriosService);
  private readonly c4Service = inject(C4Service);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly formulario = new FormGroup({
    nombreSistema: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    descripcion: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    proposito: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    actores: new FormArray<FilaContexto>([]),
    sistemasExternos: new FormArray<FilaContexto>([]),
  });

  archivoSeleccionado: File | null = null;
  pasoActual = 1;
  pasoMaximo = 1;
  tieneActores: boolean | null = null;
  tieneSistemasExternos: boolean | null = null;
  procesando = false;
  mensaje = '';
  mensajeError = '';
  ejecucion: EjecucionC4 | null = null;
  avisoRed = '';
  accionEnCurso = false;

  seleccionarArchivo(evento: Event) {
    this.archivoSeleccionado = (evento.target as HTMLInputElement).files?.item(0) ?? null;
    this.mensajeError = '';
  }

  agregarActor() {
    this.formulario.controls.actores.push(this.crearFila());
  }

  agregarSistemaExterno() {
    this.formulario.controls.sistemasExternos.push(this.crearFila());
  }

  quitarActor(indice: number) {
    this.formulario.controls.actores.removeAt(indice);
  }

  quitarSistemaExterno(indice: number) {
    this.formulario.controls.sistemasExternos.removeAt(indice);
  }

  elegirActores(valor: boolean) {
    this.tieneActores = valor;
    this.mensajeError = '';
    if (!valor) {
      this.formulario.controls.actores.clear();
    } else if (this.formulario.controls.actores.length === 0) {
      this.agregarActor();
    }
  }

  elegirSistemasExternos(valor: boolean) {
    this.tieneSistemasExternos = valor;
    this.mensajeError = '';
    if (!valor) {
      this.formulario.controls.sistemasExternos.clear();
    } else if (this.formulario.controls.sistemasExternos.length === 0) {
      this.agregarSistemaExterno();
    }
  }

  avanzar() {
    if (!this.validarPaso(this.pasoActual)) return;
    this.pasoActual = Math.min(5, this.pasoActual + 1);
    this.pasoMaximo = Math.max(this.pasoMaximo, this.pasoActual);
    this.mensajeError = '';
  }

  retroceder() {
    this.pasoActual = Math.max(1, this.pasoActual - 1);
    this.mensajeError = '';
  }

  irAlPaso(paso: number) {
    if (paso <= this.pasoMaximo && !this.procesando) {
      this.pasoActual = paso;
      this.mensajeError = '';
    }
  }

  iniciarAnalisis() {
    if (this.procesando) return;
    for (let paso = 1; paso <= 4; paso += 1) {
      if (!this.validarPaso(paso)) {
        this.pasoActual = paso;
        return;
      }
    }

    const archivo = this.archivoSeleccionado;
    if (!archivo) return;
    this.procesando = true;
    this.mensaje = 'Subiendo repositorio...';
    this.mensajeError = '';

    this.repositoriosService
      .subirRepositorio(archivo)
      .pipe(
        switchMap((subida) => {
          this.mensaje = 'Iniciando descubrimiento arquitectonico...';
          const valor = this.formulario.getRawValue();
          return this.c4Service.crearEjecucion(subida.id_repositorio, {
            contexto: {
              nombre_sistema: valor.nombreSistema,
              descripcion: valor.descripcion,
              proposito: valor.proposito,
              actores: valor.actores,
              sistemas_externos: valor.sistemasExternos,
            },
          });
        }),
        catchError((error) => {
          this.procesando = false;
          this.mensaje = '';
          this.mensajeError = this.obtenerError(error, 'No se pudo iniciar el analisis C4.');
          return EMPTY;
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((ejecucion) => this.iniciarPolling(ejecucion));
  }

  private iniciarPolling(inicial: EjecucionC4) {
    this.ejecucion = inicial;
    this.mensaje = inicial.mensaje || 'Analizando el repositorio...';
    timer(0, 4000)
      .pipe(
        switchMap(() =>
          this.c4Service.obtenerEjecucion(inicial.id_repositorio, inicial.id).pipe(
            catchError((error) => {
              this.avisoRed = `${this.obtenerError(error, 'No se pudo consultar la ejecucion.')} Se reintentara automaticamente.`;
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((ejecucion) => {
        this.ejecucion = ejecucion;
        this.avisoRed = '';
        this.mensajeError = '';
        this.mensaje = ejecucion.mensaje || `Fase actual: ${ejecucion.fase}`;
        if (ejecucion.fase === 'revision') {
          void this.router.navigate([
            '/c4',
            ejecucion.id_repositorio,
            'ejecuciones',
            ejecucion.id,
            'revision',
          ]);
        } else if (['completado', 'fallido', 'cancelado'].includes(ejecucion.estado)) {
          void this.router.navigate([
            '/c4',
            ejecucion.id_repositorio,
            'ejecuciones',
            ejecucion.id,
            'resultado',
          ]);
        }
      });
  }

  cancelar() {
    if (!this.ejecucion || this.accionEnCurso) return;
    if (!globalThis.confirm('¿Cancelar este análisis? El progreso del intento actual se perderá.')) return;
    this.accionEnCurso = true;
    this.c4Service
      .cancelarEjecucion(this.ejecucion.id_repositorio, this.ejecucion.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (ejecucion) => {
          this.ejecucion = ejecucion;
          this.accionEnCurso = false;
          void this.router.navigate([
            '/c4',
            ejecucion.id_repositorio,
            'ejecuciones',
            ejecucion.id,
            'resultado',
          ]);
        },
        error: (error) => {
          this.accionEnCurso = false;
          this.mensajeError = this.obtenerError(error, 'No se pudo cancelar la ejecucion.');
        },
      });
  }

  private crearFila(): FilaContexto {
    return new FormGroup({
      nombre: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
      descripcion: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    });
  }

  private validarPaso(paso: number) {
    if (paso === 1) {
      if (!this.archivoSeleccionado) {
        this.mensajeError = 'Selecciona el archivo ZIP que quieres analizar.';
        return false;
      }
      if (!this.archivoSeleccionado.name.toLowerCase().endsWith('.zip')) {
        this.mensajeError = 'El repositorio debe estar contenido en un archivo ZIP.';
        return false;
      }
    }

    if (paso === 2) {
      const controles = [
        this.formulario.controls.nombreSistema,
        this.formulario.controls.descripcion,
        this.formulario.controls.proposito,
      ];
      controles.forEach((control) => control.markAsTouched());
      if (controles.some((control) => control.invalid)) {
        this.mensajeError = 'Completa el nombre, la descripción y el propósito del sistema.';
        return false;
      }
    }

    if (paso === 3) {
      if (this.tieneActores === null) {
        this.mensajeError = 'Indica si hay personas o roles que usan el sistema.';
        return false;
      }
      this.formulario.controls.actores.markAllAsTouched();
      if (this.tieneActores && (this.formulario.controls.actores.length === 0 || this.formulario.controls.actores.invalid)) {
        this.mensajeError = 'Completa al menos un actor o selecciona “No”.';
        return false;
      }
    }

    if (paso === 4) {
      if (this.tieneSistemasExternos === null) {
        this.mensajeError = 'Indica si el sistema se integra con servicios o sistemas externos.';
        return false;
      }
      this.formulario.controls.sistemasExternos.markAllAsTouched();
      if (
        this.tieneSistemasExternos &&
        (this.formulario.controls.sistemasExternos.length === 0 || this.formulario.controls.sistemasExternos.invalid)
      ) {
        this.mensajeError = 'Completa al menos una integración o selecciona “No”.';
        return false;
      }
    }

    return true;
  }

  private obtenerError(error: unknown, fallback: string) {
    const respuesta = error as { error?: { detail?: string }; message?: string };
    return respuesta.error?.detail || respuesta.message || fallback;
  }
}
