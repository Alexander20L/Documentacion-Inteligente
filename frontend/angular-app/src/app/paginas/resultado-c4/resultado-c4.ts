import { CommonModule } from '@angular/common';
import {
  ChangeDetectorRef,
  Component,
  DestroyRef,
  ElementRef,
  inject,
  OnDestroy,
  OnInit,
  ViewChild,
} from '@angular/core';
import { RouterLink, ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ArtefactoC4, DiagramaC4, EjecucionC4 } from '../../modelos/c4.model';
import { C4Service } from '../../servicios/c4.service';
import { ProgresoC4 } from '../../componentes/progreso-c4/progreso-c4';
import {
  LucideArrowLeft,
  LucideCheck,
  LucideDownload,
  LucideExternalLink,
  LucideFileArchive,
  LucideFileCode2,
  LucideFileText,
  LucideImage,
  LucideLoaderCircle,
  LucideNetwork,
  LucidePackageOpen,
  LucideX,
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
    LucideCheck,
    LucideDownload,
    LucideExternalLink,
    LucideFileArchive,
    LucideFileCode2,
    LucideFileText,
    LucideImage,
    LucideLoaderCircle,
    LucideNetwork,
    LucidePackageOpen,
    LucideX,
    LucideZoomIn,
  ],
  templateUrl: './resultado-c4.html',
  styleUrl: './resultado-c4.scss',
})
export class ResultadoC4 implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly c4Service = inject(C4Service);
  private readonly destroyRef = inject(DestroyRef);
  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly urls = new Set<string>();
  private intervaloPolling: number | null = null;
  private activo = false;

  readonly idRepositorio = this.route.snapshot.paramMap.get('idRepositorio') ?? '';
  readonly idEjecucion = this.route.snapshot.paramMap.get('idEjecucion') ?? '';

  @ViewChild('imgModal') private imgModal?: ElementRef<HTMLImageElement>;

  ejecucion: EjecucionC4 | null = null;
  diagramas: DiagramaVisible[] = [];
  cargando = true;
  mensajeError = '';
  descargaActiva = '';
  avisoRed = '';
  accionEnCurso = false;
  diagramasConError: string[] = [];
  pestanaArtefactos = 'c4';
  pestanaDiagramas = 'context';
  diagramaAbierto: DiagramaVisible | null = null;
  zoomModal = 1;
  panX = 0;
  panY = 0;
  private arrastrandoModal = false;
  private ultimoXModal = 0;
  private ultimoYModal = 0;
  readonly Math = Math;
  ngOnInit() {
    if (!this.idRepositorio || !this.idEjecucion) {
      this.cargando = false;
      this.mensajeError = 'La ruta del resultado no es valida.';
      return;
    }

    this.consultarEjecucion();
    this.intervaloPolling = window.setInterval(() => this.consultarEjecucion(), 4000);
    this.registrarReintentoAlVolverVisible();
    window.setTimeout(() => {
      if (this.cargando) {
        this.cargando = false;
        this.mensajeError =
          'La petición de la ejecución tardó demasiado. Revisa que el backend esté activo en http://127.0.0.1:8000.';
        this.changeDetector.detectChanges();
      }
    }, 15000);
  }

  private consultarEjecucion() {
    this.c4Service
      .obtenerEjecucion(this.idRepositorio, this.idEjecucion)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (ejecucion) => {
          this.ejecucion = ejecucion;
          this.cargando = false;
          this.avisoRed = '';
          if (ejecucion.diagramas.length && !this.estaActiva(ejecucion)) {
            this.cargarDiagramas(ejecucion.diagramas);
          }
          if (this.estaActiva(ejecucion)) {
            this.activo = true;
          } else if (this.activo) {
            this.activo = false;
            if (this.intervaloPolling !== null) {
              window.clearInterval(this.intervaloPolling);
              this.intervaloPolling = null;
            }
          }
          this.changeDetector.detectChanges();
        },
        error: (error) => {
          this.cargando = false;
          this.avisoRed = `${this.obtenerError(error, 'No se pudo consultar la ejecucion.')} Se reintentara automaticamente.`;
          this.changeDetector.detectChanges();
        },
      });
  }

  private registrarReintentoAlVolverVisible() {
    const handler = () => {
      if (document.visibilityState !== 'visible') return;
      this.consultarEjecucion();
      if (!this.ejecucion) return;
      const pendientes = this.ejecucion.diagramas.filter(
        (diagrama) =>
          !this.diagramas.some((visible) => visible.nombre === diagrama.nombre) &&
          !this.diagramasConError.includes(diagrama.nombre),
      );
      if (pendientes.length) this.cargarDiagramas(pendientes);
    };
    document.addEventListener('visibilitychange', handler);
    this.destroyRef.onDestroy(() => document.removeEventListener('visibilitychange', handler));
  }

  cancelar() {
    if (
      !globalThis.confirm('¿Cancelar la publicación? Los artefactos incompletos no se publicarán.')
    )
      return;
    this.ejecutarAccion('cancelar');
  }

  reintentar() {
    this.ejecutarAccion('reintentar');
  }

  ngOnDestroy() {
    if (this.intervaloPolling !== null) {
      window.clearInterval(this.intervaloPolling);
      this.intervaloPolling = null;
    }
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

  formatearFecha(fecha?: string | null) {
    if (!fecha) return 'No registrada';
    const fechaObj = new Date(fecha);
    if (Number.isNaN(fechaObj.getTime())) return fecha;
    return fechaObj.toLocaleString('es', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  validacionSuperada(ejecucion: EjecucionC4) {
    const validacion = ejecucion.validacion;
    if (!validacion) return true;
    return !validacion.errores?.length;
  }

  gruposArtefactos(artefactos: ArtefactoC4[]) {
    return agruparArtefactos(artefactos);
  }

  diagramasPorNivel() {
    const niveles: {
      nivel: string;
      etiqueta: string;
      plantuml: DiagramaVisible[];
      mermaid: DiagramaVisible[];
    }[] = [];
    const orden = ['context', 'containers', 'components'];
    for (const diagrama of this.diagramas) {
      let grupo = niveles.find((item) => item.nivel === diagrama.nivel);
      if (!grupo) {
        grupo = {
          nivel: diagrama.nivel,
          etiqueta: this.etiquetaNivel(diagrama.nivel),
          plantuml: [],
          mermaid: [],
        };
        niveles.push(grupo);
      }
      if (diagrama.origen === 'mermaid') {
        grupo.mermaid.push(diagrama);
      } else {
        grupo.plantuml.push(diagrama);
      }
    }
    return niveles.sort((a, b) => {
      const ia = orden.indexOf(a.nivel);
      const ib = orden.indexOf(b.nivel);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
  }

  etiquetaNivel(nivel: string) {
    const etiquetas: Record<string, string> = {
      context: 'Contexto',
      containers: 'Contenedores',
      components: 'Componentes',
    };
    return etiquetas[nivel] || nivel;
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

  sinExtension(nombre: string) {
    const indice = nombre.lastIndexOf('.');
    return indice > 0 ? nombre.slice(0, indice) : nombre;
  }

  extension(nombre: string) {
    const indice = nombre.lastIndexOf('.');
    return indice >= 0 ? nombre.slice(indice + 1) : '';
  }

  gruposArtefactosPestanas(artefactos: ArtefactoC4[]) {
    const grupos = agruparArtefactos(artefactos);
    if (grupos.length && !grupos.some((grupo) => grupo.clave === this.pestanaArtefactos)) {
      this.pestanaArtefactos = grupos[0].clave;
    }
    return grupos;
  }

  seleccionarPestanaArtefactos(clave: string) {
    this.pestanaArtefactos = clave;
  }

  gruposDiagramasPestanas() {
    const grupos = this.diagramasPorNivel();
    if (grupos.length && !grupos.some((grupo) => grupo.nivel === this.pestanaDiagramas)) {
      this.pestanaDiagramas = grupos[0].nivel;
    }
    return grupos;
  }

  seleccionarPestanaDiagramas(nivel: string) {
    this.pestanaDiagramas = nivel;
  }

  abrirDiagrama(diagrama: DiagramaVisible) {
    this.diagramaAbierto = diagrama;
    this.zoomModal = 1;
    this.panX = 0;
    this.panY = 0;
  }

  cerrarDiagrama() {
    this.diagramaAbierto = null;
    this.arrastrandoModal = false;
  }

  acercarModal() {
    this.zoomModal = Math.min(5, this.zoomModal * 1.25);
    this.aplicarTransformeModal();
  }

  alejarModal() {
    this.zoomModal = Math.max(0.25, this.zoomModal / 1.25);
    this.aplicarTransformeModal();
  }

  reiniciarZoomModal() {
    this.zoomModal = 1;
    this.panX = 0;
    this.panY = 0;
    this.aplicarTransformeModal();
  }

  onRuedaModal(evento: WheelEvent) {
    evento.preventDefault();
    const factor = evento.deltaY < 0 ? 1.15 : 1 / 1.15;
    this.zoomModal = Math.min(5, Math.max(0.25, this.zoomModal * factor));
    this.aplicarTransformeModal();
  }

  onPulsarModal(evento: PointerEvent) {
    if (evento.button !== 0) return;
    this.arrastrandoModal = true;
    this.ultimoXModal = evento.clientX;
    this.ultimoYModal = evento.clientY;
    const mover = (movimiento: PointerEvent) => {
      if (!this.arrastrandoModal) return;
      this.panX += movimiento.clientX - this.ultimoXModal;
      this.panY += movimiento.clientY - this.ultimoYModal;
      this.ultimoXModal = movimiento.clientX;
      this.ultimoYModal = movimiento.clientY;
      this.aplicarTransformeModal();
    };
    const soltar = () => {
      this.arrastrandoModal = false;
      window.removeEventListener('pointermove', mover);
      window.removeEventListener('pointerup', soltar);
    };
    window.addEventListener('pointermove', mover);
    window.addEventListener('pointerup', soltar);
  }

  private aplicarTransformeModal() {
    const img = this.imgModal?.nativeElement;
    if (!img) return;
    img.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.zoomModal})`;
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
        if (accion === 'reintentar') {
          if (this.intervaloPolling !== null) window.clearInterval(this.intervaloPolling);
          this.intervaloPolling = window.setInterval(() => this.consultarEjecucion(), 4000);
          this.consultarEjecucion();
        }
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
