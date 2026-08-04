import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnChanges, OnDestroy, Output } from '@angular/core';
import {
  LucideBan,
  LucideCheck,
  LucideCircleDashed,
  LucideCircleX,
  LucideClock3,
  LucideLoaderCircle,
  LucideRotateCcw,
  LucideTriangleAlert,
} from '@lucide/angular';
import { EjecucionC4, ResumenEjecucionC4, TareaActualC4 } from '../../modelos/c4.model';

@Component({
  selector: 'app-progreso-c4',
  standalone: true,
  imports: [
    CommonModule,
    LucideBan,
    LucideCheck,
    LucideCircleDashed,
    LucideCircleX,
    LucideClock3,
    LucideLoaderCircle,
    LucideRotateCcw,
    LucideTriangleAlert,
  ],
  templateUrl: './progreso-c4.html',
  styleUrl: './progreso-c4.scss',
})
export class ProgresoC4 implements OnChanges, OnDestroy {
  @Input({ required: true }) ejecucion!: EjecucionC4 | ResumenEjecucionC4;
  @Input() compacto = false;
  @Input() avisoRed = '';
  @Input() accionEnCurso = false;
  @Output() cancelar = new EventEmitter<void>();
  @Output() reintentar = new EventEmitter<void>();

  ahora = Date.now();
  private reloj?: ReturnType<typeof setInterval>;

  ngOnChanges() {
    this.ahora = Date.now();
    if (this.activa && !this.reloj) {
      this.reloj = setInterval(() => (this.ahora = Date.now()), 1000);
    } else if (!this.activa) {
      this.detenerReloj();
    }
  }

  ngOnDestroy() {
    this.detenerReloj();
  }

  get tarea(): TareaActualC4 | null {
    return this.ejecucion.tarea_actual ?? null;
  }

  get activa() {
    if (this.tarea?.paso === 'revision_humana') return false;
    return ['pendiente', 'procesando'].includes(this.tarea?.estado ?? this.ejecucion.estado);
  }

  get porcentaje() {
    return Math.max(0, Math.min(100, this.tarea?.progreso ?? 0));
  }

  get estado() {
    if (this.tarea?.paso === 'revision_humana') return 'Esperando revisión';
    const estados: Record<string, string> = {
      pendiente: 'Pendiente',
      procesando: 'En proceso',
      completado: 'Completada',
      fallido: 'Fallida',
      cancelado: 'Cancelada',
    };
    return estados[this.tarea?.estado ?? this.ejecucion.estado] ?? this.ejecucion.estado;
  }

  get estadoClave() {
    if (this.tarea?.paso === 'revision_humana') return 'revision';
    return this.tarea?.estado ?? this.ejecucion.estado;
  }

  get mostrarCancelar() {
    return this.activa && (!this.compacto || this.cancelar.observed);
  }

  get mostrarReintentar() {
    return this.ejecucion.estado === 'fallido' && (!this.compacto || this.reintentar.observed);
  }

  get paso() {
    const paso = this.tarea?.paso || this.ejecucion.fase;
    const etiquetas: Record<string, string> = {
      en_cola: 'Esperando un worker disponible',
      preparar_copia: 'Preparando una copia segura',
      sanear_fuentes: 'Saneando archivos fuente',
      extraer_estructura: 'Extrayendo estructura del proyecto',
      preparar_repositorio: 'Preparando el repositorio',
      escanear_fuentes: 'Escaneando archivos fuente',
      analizar_grafo: 'Extrayendo dependencias',
      preparar_agentes: 'Preparando el análisis semántico',
      analizar_modulos: 'Analizando módulos',
      preparar_revision: 'Preparando la revisión',
      publicar_revision: 'Publicando candidatos',
      registrar_revision: 'Registrando la revisión',
      revision_humana: 'Esperando tu revisión',
      generar_modelo: 'Generando el modelo Structurizr',
      preparar_publicacion: 'Preparando la publicación',
      generar_dsl: 'Generando el workspace Structurizr',
      validar_structurizr: 'Validando el workspace Structurizr',
      validar_modelo: 'Validando el modelo',
      renderizar_diagramas: 'Renderizando diagramas',
      generar_documentos: 'Generando documentación',
      registrar_artefactos: 'Registrando artefactos',
      confirmar_artefactos: 'Confirmando artefactos publicados',
      completado: 'Proceso completado',
    };
    return etiquetas[paso] ?? paso.replaceAll('_', ' ');
  }

  get mensaje() {
    return this.tarea?.mensaje || ('mensaje' in this.ejecucion ? this.ejecucion.mensaje : null);
  }

  get ultimaActividad(): string | null {
    return this.tarea?.ultima_actividad_en || this.ejecucion.actualizado_en || null;
  }

  get inactiva() {
    const actividad = this.fecha(this.ultimaActividad);
    return this.activa && actividad !== null && this.ahora - actividad > 300_000;
  }

  get unidadesVisibles() {
    return this.tarea?.unidades_completadas != null && this.tarea?.unidades_totales != null;
  }

  get tiempoRestante() {
    const segundos = this.tarea?.eta_segundos;
    if (segundos == null) return this.activa ? 'Calculando tiempo restante' : 'No aplica';
    const minutos = Math.max(1, Math.ceil(segundos / 60));
    return `Aproximadamente ${minutos} min`;
  }

  duracion(desde?: string | null) {
    const inicio = this.fecha(desde);
    if (inicio === null) return 'No disponible';
    const segundos = Math.max(0, Math.floor((this.ahora - inicio) / 1000));
    const horas = Math.floor(segundos / 3600);
    const minutos = Math.floor((segundos % 3600) / 60);
    const resto = segundos % 60;
    return horas
      ? `${horas} h ${minutos} min`
      : minutos
        ? `${minutos} min ${resto} s`
        : `${resto} s`;
  }

  actividadRelativa() {
    const actividad = this.fecha(this.ultimaActividad);
    if (actividad === null) return 'No disponible';
    const segundos = Math.max(0, Math.floor((this.ahora - actividad) / 1000));
    if (segundos < 10) return 'Ahora';
    if (segundos < 60) return `Hace ${segundos} s`;
    return `Hace ${Math.floor(segundos / 60)} min`;
  }

  private fecha(valor?: string | null) {
    if (!valor) return null;
    const tiempo = Date.parse(valor);
    return Number.isNaN(tiempo) ? null : tiempo;
  }

  private detenerReloj() {
    if (this.reloj) clearInterval(this.reloj);
    this.reloj = undefined;
  }
}
