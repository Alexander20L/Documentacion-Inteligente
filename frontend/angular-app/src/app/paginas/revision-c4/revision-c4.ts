import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, DestroyRef, inject, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY } from 'rxjs';
import { catchError, exhaustMap, takeWhile, timeout } from 'rxjs/operators';
import { pollingReanudable } from '../../servicios/polling-reanudable';
import {
  DecisionCandidatoC4,
  ElementoC4,
  EvidenciaCandidatoC4,
  GuardarRevisionC4,
  HallazgoJuezC4,
  HuerfanoC4,
  ConflictoC4,
  RelacionC4,
  ResumenSemanticoC4,
  RevisionC4 as ModeloRevisionC4,
  EjecucionC4,
} from '../../modelos/c4.model';
import { C4Service } from '../../servicios/c4.service';
import { ProgresoC4 } from '../../componentes/progreso-c4/progreso-c4';
import {
  LucideAlertTriangle,
  LucideArrowLeft,
  LucideCheck,
  LucideChevronDown,
  LucideFileSearch,
  LucideFilter,
  LucideGitBranch,
  LucideNetwork,
  LucideRotateCcw,
  LucideSave,
  LucideSparkles,
  LucideX,
} from '@lucide/angular';

interface GrupoElementosRevision {
  titulo: string;
  descripcion: string;
  elementos: ElementoC4[];
}

type FiltroEstadoRevision = 'todos' | 'pendientes' | 'aprobados' | 'rechazados';

interface CambioLoteRevision {
  candidato: ElementoC4 | RelacionC4;
  decisionAnterior: DecisionCandidatoC4;
}

@Component({
  selector: 'app-revision-c4',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    ProgresoC4,
    LucideAlertTriangle,
    LucideArrowLeft,
    LucideCheck,
    LucideChevronDown,
    LucideFileSearch,
    LucideFilter,
    LucideGitBranch,
    LucideNetwork,
    LucideRotateCcw,
    LucideSave,
    LucideSparkles,
    LucideX,
  ],
  templateUrl: './revision-c4.html',
  styleUrl: './revision-c4.scss',
})
export class RevisionC4 implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly c4Service = inject(C4Service);
  private readonly destroyRef = inject(DestroyRef);
  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly metadatosRecibidos = new Set<
    'resumen_semantico' | 'conflictos' | 'huerfanos' | 'hallazgos_juez'
  >();

  readonly idRepositorio = this.route.snapshot.paramMap.get('idRepositorio') ?? '';
  readonly idEjecucion = this.route.snapshot.paramMap.get('idEjecucion') ?? '';

  elementos: ElementoC4[] = [];
  relaciones: RelacionC4[] = [];
  candidatos: (ElementoC4 | RelacionC4)[] = [];
  elementosVisibles: ElementoC4[] = [];
  gruposElementosVisibles: GrupoElementosRevision[] = [];
  relacionesVisibles: RelacionC4[] = [];
  candidatosPendientesVisibles: (ElementoC4 | RelacionC4)[] = [];
  pendientes = 0;
  aprobados = 0;
  rechazados = 0;
  decididos = 0;
  totalInferidos = 0;
  porcentajeDecidido = 0;
  inconsistencias = 0;
  modulos: string[] = [];
  agentes: string[] = [];
  resumenSemantico?: ResumenSemanticoC4;
  conflictos: ConflictoC4[] = [];
  huerfanos: HuerfanoC4[] = [];
  hallazgosJuez: HallazgoJuezC4[] = [];
  filtroEstado: FiltroEstadoRevision = 'pendientes';
  filtroModulo = '';
  filtroAgente = '';
  hash = '';
  version = 0;
  cargando = true;
  guardando = false;
  mensaje = '';
  mensajeError = '';
  ejecucion: EjecucionC4 | null = null;
  revisionCargada = false;
  cargandoRevision = false;
  avisoRed = '';
  accionEnCurso = false;
  ultimoLote: CambioLoteRevision[] = [];

  ngOnInit() {
    if (!this.idRepositorio || !this.idEjecucion) {
      this.cargando = false;
      this.mensajeError = 'La ruta de revision no es valida.';
      return;
    }

    this.consultarEjecucion();
  }

  cargarRevision() {
    if (this.cargandoRevision || this.revisionCargada) return;
    this.cargandoRevision = true;
    this.cargando = true;
    this.mensajeError = '';
    this.c4Service
      .obtenerRevision(this.idRepositorio, this.idEjecucion)
      .pipe(timeout(15000), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (revision) => {
          this.hash = revision.hash;
          this.version = revision.version;
          this.elementos = revision.elementos.map((elemento) => ({ ...elemento }));
          this.relaciones = revision.relaciones.map((relacion) => ({ ...relacion }));
          this.ultimoLote = [];
          this.asignarMetadatos(revision);
          this.actualizarVista();
          this.revisionCargada = true;
          this.cargandoRevision = false;
          this.cargando = false;
          this.changeDetector.markForCheck();
        },
        error: (error) => {
          this.cargandoRevision = false;
          this.cargando = false;
          this.mensajeError = this.obtenerError(error, 'No se pudieron cargar los candidatos.');
          this.changeDetector.markForCheck();
        },
      });
  }

  cancelar() {
    if (!globalThis.confirm('¿Cancelar esta ejecución C4?')) return;
    this.ejecutarAccion('cancelar');
  }

  reintentar() {
    this.ejecutarAccion('reintentar');
  }

  decidir(candidato: ElementoC4 | RelacionC4, decision: DecisionCandidatoC4) {
    if (candidato.inferido) {
      candidato.decision = decision;
      this.actualizarVista();
    }
  }

  aprobarVisibles() {
    this.aplicarLote('APROBADO');
  }

  rechazarVisibles() {
    const cantidad = this.candidatosPendientesVisibles.length;
    if (!cantidad) return;
    if (
      !globalThis.confirm(
        `¿Rechazar ${cantidad} candidato${cantidad === 1 ? '' : 's'} inferido${cantidad === 1 ? '' : 's'} pendiente${cantidad === 1 ? '' : 's'} visible${cantidad === 1 ? '' : 's'}?`,
      )
    ) {
      return;
    }
    this.aplicarLote('RECHAZADO');
  }

  deshacerUltimoLote() {
    if (!this.ultimoLote.length) return;
    const cantidad = this.ultimoLote.length;
    for (const cambio of this.ultimoLote) {
      if (this.esInferenciaRevisable(cambio.candidato)) {
        cambio.candidato.decision = cambio.decisionAnterior;
      }
    }
    this.ultimoLote = [];
    this.mensaje = `Se deshizo el ultimo lote de ${cantidad} candidato${cantidad === 1 ? '' : 's'}.`;
    this.mensajeError = '';
    this.actualizarVista();
  }

  guardar() {
    if (!this.validar()) return;
    this.guardando = true;
    this.mensaje = '';
    this.mensajeError = '';
    this.c4Service
      .guardarRevision(this.idRepositorio, this.idEjecucion, this.crearRevision())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (revision) => {
          this.hash = revision.hash;
          this.version = revision.version;
          this.elementos = revision.elementos.map((elemento) => ({ ...elemento }));
          this.relaciones = revision.relaciones.map((relacion) => ({ ...relacion }));
          this.ultimoLote = [];
          this.asignarMetadatos(revision);
          this.actualizarVista();
          this.guardando = false;
          this.mensaje = 'Revision guardada.';
          this.changeDetector.markForCheck();
        },
        error: (error) => {
          this.guardando = false;
          this.mensajeError = this.obtenerError(
            error,
            'No se pudo guardar. Actualiza la pagina si la revision cambio.',
          );
          this.changeDetector.markForCheck();
        },
      });
  }

  aprobar() {
    if (!this.validar()) return;
    const pendientes = [...this.elementos, ...this.relaciones].some(
      (candidato) => candidato.inferido && candidato.decision === 'PENDIENTE',
    );
    if (pendientes) {
      this.mensajeError = 'Aprueba o rechaza todos los candidatos inferidos antes de continuar.';
      return;
    }

    this.guardando = true;
    this.mensajeError = '';
    this.c4Service
      .aprobarRevision(this.idRepositorio, this.idEjecucion, this.crearRevision())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          void this.router.navigate([
            '/c4',
            this.idRepositorio,
            'ejecuciones',
            this.idEjecucion,
            'resultado',
          ]);
        },
        error: (error) => {
          this.guardando = false;
          this.mensajeError = this.obtenerError(error, 'No se pudo aprobar la revision.');
          this.changeDetector.markForCheck();
        },
      });
  }

  nombreElemento(id: string) {
    return this.elementos.find((elemento) => elemento.id === id)?.nombre || id;
  }

  derivacionRelacion(relacion: RelacionC4) {
    const etiquetas: Record<string, string> = {
      import_python: 'Import directo verificado',
      import_fuente: 'Import directo verificado',
      base_datos: 'Configuración de base de datos',
      contexto_analista: 'Confirmada por el analista',
      inferencia: 'Inferida por agente',
    };
    return etiquetas[relacion.derivacion || ''] || relacion.derivacion || 'Origen no indicado';
  }

  etiquetaMarcado(marcado: string) {
    const etiquetas: Record<string, string> = {
      sin_evidencia_import: 'Sin evidencia de import directo',
      probable_duplicado: 'Posible duplicado de otra capacidad',
    };
    return etiquetas[marcado] || marcado;
  }

  actualizarVista() {
    this.candidatos = [...this.elementos, ...this.relaciones];
    this.elementosVisibles = this.elementos.filter((candidato) => this.cumpleFiltros(candidato));
    this.relacionesVisibles = this.relaciones.filter((candidato) => this.cumpleFiltros(candidato));
    this.candidatosPendientesVisibles = [
      ...this.elementosVisibles,
      ...this.relacionesVisibles,
    ].filter(
      (candidato) =>
        this.esInferenciaRevisable(candidato) && candidato.decision === 'PENDIENTE',
    );
    this.pendientes = this.candidatos.filter(
      (candidato) => candidato.inferido && candidato.decision === 'PENDIENTE',
    ).length;
    this.aprobados = this.candidatos.filter(
      (candidato) => candidato.inferido && candidato.decision === 'APROBADO',
    ).length;
    this.rechazados = this.candidatos.filter(
      (candidato) => candidato.inferido && candidato.decision === 'RECHAZADO',
    ).length;
    this.totalInferidos = this.pendientes + this.aprobados + this.rechazados;
    this.decididos = this.aprobados + this.rechazados;
    this.porcentajeDecidido = this.totalInferidos
      ? Math.round((this.decididos / this.totalInferidos) * 100)
      : 100;
    const elementosRechazados = new Set(
      this.elementos.filter((item) => item.decision === 'RECHAZADO').map((item) => item.id),
    );
    this.inconsistencias =
      this.elementos.filter(
        (item) =>
          item.decision === 'APROBADO' &&
          Boolean(item.padre_id && elementosRechazados.has(item.padre_id)),
      ).length +
      this.relaciones.filter(
        (item) =>
          item.decision === 'APROBADO' &&
          (elementosRechazados.has(item.origen_id) || elementosRechazados.has(item.destino_id)),
      ).length;
    this.modulos = this.valoresFiltro('modulo');
    this.agentes = this.valoresFiltro('agente');

    const ordenados = (elementos: ElementoC4[]) => [...elementos].sort((a, b) => {
      const padreA = a.padre_id ? this.nombreElemento(a.padre_id) : '';
      const padreB = b.padre_id ? this.nombreElemento(b.padre_id) : '';
      return padreA.localeCompare(padreB) || a.nombre.localeCompare(b.nombre);
    });
    this.gruposElementosVisibles = [
      {
        titulo: 'Contexto',
        descripcion: 'Personas y sistema confirmado por el analista',
        elementos: ordenados(this.elementosVisibles.filter((item) => ['person', 'software_system', 'external_system'].includes(item.tipo))),
      },
      {
        titulo: 'Contenedores',
        descripcion: 'Aplicaciones y almacenes desplegables',
        elementos: ordenados(this.elementosVisibles.filter((item) => item.tipo === 'container')),
      },
      {
        titulo: 'Componentes',
        descripcion: 'Responsabilidades agrupadas por contenedor padre',
        elementos: ordenados(this.elementosVisibles.filter((item) => item.tipo === 'component')),
      },
    ].filter((grupo) => grupo.elementos.length);
  }

  get filtrosActivos() {
    return this.filtroEstado !== 'todos' || Boolean(this.filtroModulo) || Boolean(this.filtroAgente);
  }

  limpiarFiltros() {
    this.filtroEstado = 'todos';
    this.filtroModulo = '';
    this.filtroAgente = '';
    this.actualizarVista();
  }

  mostrarPendientes() {
    this.filtroEstado = 'pendientes';
    this.actualizarVista();
  }

  filtrarPorEstado(estado: FiltroEstadoRevision) {
    this.filtroEstado = estado;
    this.actualizarVista();
  }

  ubicacion(evidencia: EvidenciaCandidatoC4) {
    if (evidencia.linea_inicio == null) return evidencia.ruta;
    const rango =
      evidencia.linea_fin != null && evidencia.linea_fin !== evidencia.linea_inicio
        ? `${evidencia.linea_inicio}-${evidencia.linea_fin}`
        : `${evidencia.linea_inicio}`;
    return `${evidencia.ruta}:${rango}`;
  }

  trackById(_: number, candidato: ElementoC4 | RelacionC4) {
    return candidato.id;
  }

  private consultarEjecucion() {
    pollingReanudable(4000)
      .pipe(
        exhaustMap(() =>
          this.c4Service.obtenerEjecucion(this.idRepositorio, this.idEjecucion).pipe(
            timeout(15000),
            catchError((error) => {
              this.cargando = false;
              this.avisoRed = `${this.obtenerError(error, 'No se pudo consultar la ejecucion.')} Se reintentara automaticamente.`;
              this.changeDetector.markForCheck();
              return EMPTY;
            }),
          ),
        ),
        takeWhile(
          (ejecucion) =>
            ['pendiente', 'procesando'].includes(ejecucion.estado) &&
            ejecucion.fase !== 'revision',
          true,
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((ejecucion) => {
        this.ejecucion = ejecucion;
        this.cargando = false;
        this.avisoRed = '';
        if (ejecucion.fase === 'revision') this.cargarRevision();
        this.changeDetector.markForCheck();
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
        if (accion === 'reintentar') this.consultarEjecucion();
      },
      error: (error) => {
        this.accionEnCurso = false;
        this.mensajeError = this.obtenerError(error, `No se pudo ${accion} la ejecucion.`);
      },
    });
  }

  private crearRevision(): GuardarRevisionC4 {
    return {
      hash: this.hash,
      version: this.version,
      elementos: this.elementos,
      relaciones: this.relaciones,
      ...(this.metadatosRecibidos.has('resumen_semantico') && {
        resumen_semantico: this.resumenSemantico,
      }),
      ...(this.metadatosRecibidos.has('conflictos') && { conflictos: this.conflictos }),
      ...(this.metadatosRecibidos.has('huerfanos') && { huerfanos: this.huerfanos }),
      ...(this.metadatosRecibidos.has('hallazgos_juez') && {
        hallazgos_juez: this.hallazgosJuez,
      }),
    };
  }

  private asignarMetadatos(revision: ModeloRevisionC4) {
    this.metadatosRecibidos.clear();
    for (const campo of [
      'resumen_semantico',
      'conflictos',
      'huerfanos',
      'hallazgos_juez',
    ] as const) {
      if (revision[campo] !== undefined) this.metadatosRecibidos.add(campo);
    }
    this.resumenSemantico = revision.resumen_semantico;
    this.conflictos = revision.conflictos ?? [];
    this.huerfanos = revision.huerfanos ?? [];
    this.hallazgosJuez = revision.hallazgos_juez ?? [];
  }

  private cumpleFiltros(candidato: ElementoC4 | RelacionC4) {
    const decisionesPorFiltro: Record<Exclude<FiltroEstadoRevision, 'todos'>, DecisionCandidatoC4> = {
      pendientes: 'PENDIENTE',
      aprobados: 'APROBADO',
      rechazados: 'RECHAZADO',
    };
    if (
      this.filtroEstado !== 'todos' &&
      (!candidato.inferido || candidato.decision !== decisionesPorFiltro[this.filtroEstado])
    ) return false;
    const modulos = this.metadatosCandidato(candidato, 'modulo');
    const agentes = this.metadatosCandidato(candidato, 'agente');
    return (
      (!this.filtroModulo || modulos.includes(this.filtroModulo)) &&
      (!this.filtroAgente || agentes.includes(this.filtroAgente))
    );
  }

  private valoresFiltro(campo: 'modulo' | 'agente') {
    return [
      ...new Set(this.candidatos.flatMap((candidato) => this.metadatosCandidato(candidato, campo))),
    ].sort();
  }

  private aplicarLote(decision: Extract<DecisionCandidatoC4, 'APROBADO' | 'RECHAZADO'>) {
    if (!this.candidatosPendientesVisibles.length) return;
    this.ultimoLote = this.candidatosPendientesVisibles.map((candidato) => ({
      candidato,
      decisionAnterior: candidato.decision,
    }));
    for (const cambio of this.ultimoLote) {
      if (
        this.esInferenciaRevisable(cambio.candidato) &&
        cambio.candidato.decision === 'PENDIENTE'
      ) {
        cambio.candidato.decision = decision;
      }
    }
    const cantidad = this.ultimoLote.length;
    this.mensaje = `${cantidad} candidato${cantidad === 1 ? '' : 's'} visible${cantidad === 1 ? '' : 's'} ${decision === 'APROBADO' ? 'aprobado' : 'rechazado'}${cantidad === 1 ? '' : 's'}.`;
    this.mensajeError = '';
    this.actualizarVista();
  }

  private esInferenciaRevisable(candidato: ElementoC4 | RelacionC4) {
    return candidato.inferido && candidato.procedencia !== 'analyst_provided';
  }

  private metadatosCandidato(candidato: ElementoC4 | RelacionC4, campo: 'modulo' | 'agente') {
    return [
      candidato[campo],
      ...(candidato.evidencias ?? []).map((evidencia) => evidencia[campo]),
    ].filter((valor): valor is string => Boolean(valor));
  }

  private validar() {
    if ([...this.elementos, ...this.relaciones].some((item) => !item.nombre.trim())) {
      this.mensajeError = 'Todos los candidatos deben tener nombre.';
      return false;
    }
    if (this.inconsistencias) {
      this.mensajeError = `${this.inconsistencias} decisiones aprobadas dependen de elementos rechazados.`;
      return false;
    }
    return true;
  }

  private obtenerError(error: unknown, fallback: string) {
    const respuesta = error as { error?: { detail?: string }; message?: string };
    return respuesta.error?.detail || respuesta.message || fallback;
  }
}
