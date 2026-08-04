import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LucideChevronLeft, LucideChevronRight, LucideX } from '@lucide/angular';
import { ElementoC4 } from '../../modelos/c4.model';
import { LienzoDiagramaC4 } from '../lienzo-diagrama-c4/lienzo-diagrama-c4';

export interface DiagramaModalC4 {
  id: string;
  nombre: string;
  nivel: string;
  svg: string;
}

const NIVELES = ['context', 'containers', 'components'] as const;

function etiquetaNivel(nivel: string): string {
  const etiquetas: Record<string, string> = {
    context: 'Contexto',
    containers: 'Contenedores',
    components: 'Componentes',
  };
  return etiquetas[nivel] || nivel;
}

@Component({
  selector: 'app-modal-diagramas-c4',
  standalone: true,
  imports: [CommonModule, LienzoDiagramaC4, LucideChevronLeft, LucideChevronRight, LucideX],
  templateUrl: './modal-diagramas-c4.html',
  styleUrl: './modal-diagramas-c4.scss',
})
export class ModalDiagramasC4 {
  @Input() abierto = false;
  @Input() titulo = '';
  @Input() elementos: ElementoC4[] = [];
  @Input() seleccionadoId = '';
  @Input() diagramas: DiagramaModalC4[] = [];
  @Input() set diagramaInicial(value: DiagramaModalC4 | null) {
    if (value) this.fijarInicial(value);
  }
  @Output() cerrar = new EventEmitter<void>();

  nivelActual: string = 'containers';
  indiceActual = 0;

  get nivelesPresentes() {
    const presentes = new Set(this.diagramas.map((diagrama) => diagrama.nivel));
    return NIVELES.filter((nivel) => presentes.has(nivel));
  }

  get diagramasDelNivel() {
    return this.diagramas.filter((diagrama) => diagrama.nivel === this.nivelActual);
  }

  get diagramaActual() {
    const lista = this.diagramasDelNivel;
    return lista[this.indiceActual] ?? lista[0] ?? null;
  }

  private fijarInicial(diagrama: DiagramaModalC4) {
    this.nivelActual = diagrama.nivel;
    const indice = this.diagramasDelNivel.findIndex((item) => item.id === diagrama.id);
    this.indiceActual = indice >= 0 ? indice : 0;
  }

  cambiarNivel(nivel: string) {
    this.nivelActual = nivel;
    this.indiceActual = 0;
  }

  anterior() {
    const lista = this.diagramasDelNivel;
    if (!lista.length) return;
    this.indiceActual = (this.indiceActual - 1 + lista.length) % lista.length;
  }

  siguiente() {
    const lista = this.diagramasDelNivel;
    if (!lista.length) return;
    this.indiceActual = (this.indiceActual + 1) % lista.length;
  }

  etiquetaNivel(nivel: string): string {
    return etiquetaNivel(nivel);
  }

  cerrarModal() {
    this.cerrar.emit();
  }
}
