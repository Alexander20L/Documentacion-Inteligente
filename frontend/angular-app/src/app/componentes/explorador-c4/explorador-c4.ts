import { ChangeDetectorRef, Component, DestroyRef, inject, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideArrowLeft, LucideLoaderCircle, LucideBox } from '@lucide/angular';
import { C4Service } from '../../servicios/c4.service';
import { DiagramaC4, ElementoC4, ExploradorC4, RelacionC4 } from '../../modelos/c4.model';
import { ArbolModeloC4 } from '../../componentes/arbol-modelo-c4/arbol-modelo-c4';
import { GrafoModeloUnificadoC4 } from '../../componentes/grafo-modelo-unificado-c4/grafo-modelo-unificado-c4';
import {
  LienzoDiagramaC4,
  normalizarNombre,
} from '../../componentes/lienzo-diagrama-c4/lienzo-diagrama-c4';
import { PanelDetalleC4 } from '../../componentes/panel-detalle-c4/panel-detalle-c4';
import { ModalDecisionC4 } from '../../componentes/modal-decision-c4/modal-decision-c4';
import {
  DiagramaModalC4,
  ModalDiagramasC4,
} from '../../componentes/modal-diagramas-c4/modal-diagramas-c4';

interface DiagramaVisible extends DiagramaC4 {
  svg: string;
  texto: string;
}

export function esSvgMermaid(svg: string): boolean {
  if (!svg) return false;
  const cabecera = svg.slice(0, 1200);
  const firmaMermaid = /id="my-svg"|class="flowchart"|class="sequence"|aria-roledescription/.test(
    cabecera,
  );
  const firmaPlantuml = /data-diagram-type|<\?plantuml/.test(cabecera);
  if (firmaPlantuml) return false;
  return firmaMermaid;
}

@Component({
  selector: 'app-explorador-c4',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    ArbolModeloC4,
    GrafoModeloUnificadoC4,
    LienzoDiagramaC4,
    PanelDetalleC4,
    ModalDecisionC4,
    ModalDiagramasC4,
    LucideArrowLeft,
    LucideLoaderCircle,
    LucideBox,
  ],
  templateUrl: './explorador-c4.html',
  styleUrl: './explorador-c4.scss',
})
export class ExploradorC4Pagina implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly c4Service = inject(C4Service);
  private readonly destroyRef = inject(DestroyRef);
  private readonly changeDetector = inject(ChangeDetectorRef);

  readonly idRepositorio = this.route.snapshot.paramMap.get('idRepositorio') ?? '';
  readonly idEjecucion = this.route.snapshot.paramMap.get('idEjecucion') ?? '';

  datos: ExploradorC4 | null = null;
  cargando = true;
  mensajeError = '';
  avisoRed = '';
  seleccionadoId = '';
  seleccionado: ElementoC4 | null = null;
  relacionSeleccionada: RelacionC4 | null = null;
  modalDiagramasAbierto = false;
  diagramasModal: DiagramaModalC4[] = [];
  diagramaInicialModal: DiagramaModalC4 | null = null;
  puedeDecidir = false;
  modalAbierto = false;
  decisionPendiente: 'APROBADO' | 'RECHAZADO' = 'APROBADO';
  guardando = false;
  diagramas: DiagramaVisible[] = [];
  diagramasConError: string[] = [];
  private cargados = new Set<string>();
  private intervaloExplorador: number | null = null;

  get elementos() {
    return this.datos?.revision?.elementos ?? [];
  }
  get relaciones() {
    return this.datos?.revision?.relaciones ?? [];
  }

  get nombreSistema() {
    const sistema = this.elementos.find((item) => item.tipo === 'software_system');
    return sistema?.nombre ?? 'Modelo C4';
  }

  get contenedores() {
    return this.elementos.filter((item) => item.tipo === 'container');
  }
  get componentes() {
    return this.elementos.filter((item) => item.tipo === 'component');
  }

  ngOnInit() {
    if (!this.idRepositorio || !this.idEjecucion) {
      this.cargando = false;
      this.mensajeError = 'La ruta del explorador no es valida.';
      return;
    }
    this.cargarExplorador();
    this.intervaloExplorador = window.setInterval(() => this.cargarExplorador(), 4000);
    const handler = () => {
      if (document.visibilityState === 'visible') this.cargarExplorador();
    };
    document.addEventListener('visibilitychange', handler);
    this.destroyRef.onDestroy(() => document.removeEventListener('visibilitychange', handler));
  }

  ngOnDestroy() {
    if (this.intervaloExplorador !== null) {
      window.clearInterval(this.intervaloExplorador);
      this.intervaloExplorador = null;
    }
  }

  private cargarExplorador() {
    this.c4Service
      .obtenerExplorador(this.idRepositorio, this.idEjecucion)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (datos) => {
          this.datos = datos;
          this.cargando = false;
          this.avisoRed = '';
          this.puedeDecidir = (datos.ejecucion.fase ?? '') === 'revision';
          if (datos.ejecucion.diagramas?.length) {
            this.cargarDiagramas(datos.ejecucion.diagramas);
          }
          if (!this.seleccionadoId && this.elementos.length) {
            const sistema =
              this.elementos.find((item) => item.tipo === 'software_system') ??
              this.contenedores[0];
            if (sistema) this.seleccionar(sistema.id);
          }
          this.changeDetector.detectChanges();
        },
        error: (error) => {
          this.cargando = false;
          this.avisoRed = `${this.obtenerError(error, 'No se pudo cargar el explorador.')} Se reintentara automaticamente.`;
          this.changeDetector.detectChanges();
        },
      });
  }

  private cargarDiagramas(diagramas: DiagramaC4[]) {
    diagramas
      .filter((diagrama) => !diagrama.origen || diagrama.origen === 'plantuml')
      .forEach((diagrama) => {
        if (this.cargados.has(diagrama.id)) return;
        this.cargados.add(diagrama.id);
        this.c4Service
          .descargarArtefactoSvg(this.idRepositorio, this.idEjecucion, diagrama.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: (svg) => {
              if (esSvgMermaid(svg)) return;
              this.diagramas = [
                ...this.diagramas,
                { ...diagrama, svg, texto: this.textoDiagrama(svg) },
              ];
              this.changeDetector.detectChanges();
            },
            error: () => {
              this.diagramasConError = [...this.diagramasConError, diagrama.id];
              this.changeDetector.detectChanges();
            },
          });
      });
  }

  private textoDiagrama(svg: string): string {
    try {
      const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
      return normalizarNombre(doc.documentElement.textContent ?? '');
    } catch {
      return '';
    }
  }

  diagramasDelElemento(elemento: ElementoC4 | null): DiagramaModalC4[] {
    if (!elemento) return [];
    const nombre = normalizarNombre(elemento.nombre);
    if (!nombre) return [];
    return this.diagramas
      .filter((diagrama) => diagrama.texto.includes(nombre))
      .map((diagrama) => ({
        id: diagrama.id,
        nombre: diagrama.nombre,
        nivel: diagrama.nivel,
        svg: diagrama.svg,
      }));
  }

  seleccionar(id: string | ElementoC4) {
    const idElemento = typeof id === 'string' ? id : id.id;
    this.seleccionadoId = idElemento;
    this.relacionSeleccionada = null;
    this.seleccionado = this.elementos.find((item) => item.id === idElemento) ?? null;
  }

  abrirDiagrama(diagrama: DiagramaModalC4) {
    this.diagramasModal = this.diagramasDelElemento(this.seleccionado);
    this.diagramaInicialModal = diagrama;
    this.modalDiagramasAbierto = true;
  }

  cerrarDiagramas() {
    this.modalDiagramasAbierto = false;
    this.diagramaInicialModal = null;
  }

  nombreElemento(id: string) {
    return this.elementos.find((item) => item.id === id)?.nombre ?? id;
  }

  solicitarDecision(decision: 'APROBADO' | 'RECHAZADO') {
    if (!this.puedeDecidir || this.guardando) return;
    const candidato = this.seleccionado ?? this.relacionSeleccionada;
    if (!candidato) return;
    if (!candidato.inferido) return;
    this.decisionPendiente = decision;
    this.modalAbierto = true;
  }

  confirmarDecision() {
    if (!this.datos?.revision || this.guardando) return;
    this.guardando = true;
    const revision = this.datos.revision;
    const objetivo = this.seleccionado ?? this.relacionSeleccionada;
    if (!objetivo) {
      this.guardando = false;
      return;
    }
    const objetivoId = objetivo.id;
    const siguiente: typeof revision = {
      ...revision,
      elementos: revision.elementos.map((item) =>
        item.id === objetivoId ? { ...item, decision: this.decisionPendiente } : item,
      ),
      relaciones: revision.relaciones.map((item) =>
        item.id === objetivoId ? { ...item, decision: this.decisionPendiente } : item,
      ),
    };
    this.c4Service
      .guardarRevision(this.idRepositorio, this.idEjecucion, siguiente)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (guardada) => {
          this.datos = { ...this.datos!, revision: guardada };
          const objetivoActualizado = this.seleccionado ?? this.relacionSeleccionada;
          if (objetivoActualizado) {
            const busqueda =
              this.elementos.find((item) => item.id === objetivoActualizado.id) ??
              this.relaciones.find((item) => item.id === objetivoActualizado.id);
            if (busqueda) this.seleccionadoId = busqueda.id;
          }
          this.modalAbierto = false;
          this.guardando = false;
        },
        error: (error) => {
          this.guardando = false;
          this.modalAbierto = false;
          this.mensajeError = this.obtenerError(
            error,
            'No se pudo guardar la decision. La revision pudo cambiar; vuelve a cargarla.',
          );
          this.cargarExplorador();
        },
      });
  }

  cancelarDecision() {
    this.modalAbierto = false;
  }

  private obtenerError(error: unknown, fallback: string) {
    const respuesta = error as { error?: { detail?: string }; message?: string };
    return respuesta.error?.detail || respuesta.message || fallback;
  }
}
