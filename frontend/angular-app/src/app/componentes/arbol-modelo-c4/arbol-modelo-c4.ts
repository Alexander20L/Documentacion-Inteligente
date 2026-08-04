import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  LucideChevronDown,
  LucideChevronRight,
  LucideBox,
  LucideLayers,
  LucideGlobe,
  LucideUser,
} from '@lucide/angular';
import { ElementoC4 } from '../../modelos/c4.model';

export interface NodoArbolC4 {
  elemento: ElementoC4;
  hijos: NodoArbolC4[];
  expandido: boolean;
}

@Component({
  selector: 'app-arbol-modelo-c4',
  standalone: true,
  imports: [
    CommonModule,
    LucideChevronDown,
    LucideChevronRight,
    LucideBox,
    LucideLayers,
    LucideGlobe,
    LucideUser,
  ],
  templateUrl: './arbol-modelo-c4.html',
  styleUrl: './arbol-modelo-c4.scss',
})
export class ArbolModeloC4 {
  @Input() set elementos(value: ElementoC4[]) {
    this.arbol = this.construirArbol(value);
  }
  @Input() seleccionadoId = '';
  @Output() seleccionar = new EventEmitter<ElementoC4>();

  arbol: NodoArbolC4[] = [];

  private construirArbol(elementos: ElementoC4[]): NodoArbolC4[] {
    const porId = new Map(elementos.map((item) => [item.id, item]));
    const raices: NodoArbolC4[] = [];
    const nodos = new Map<string, NodoArbolC4>();
    for (const elemento of elementos) {
      nodos.set(elemento.id, { elemento, hijos: [], expandido: true });
    }
    for (const nodo of nodos.values()) {
      const padreId = nodo.elemento.padre_id;
      const padre = padreId && nodos.get(padreId) ? nodos.get(padreId)! : null;
      if (padre) {
        padre.hijos.push(nodo);
      } else {
        raices.push(nodo);
      }
    }
    return raices.sort((a, b) => a.elemento.nombre.localeCompare(b.elemento.nombre));
  }

  alternar(nodo: NodoArbolC4) {
    nodo.expandido = !nodo.expandido;
  }

  click(nodo: NodoArbolC4) {
    this.seleccionar.emit(nodo.elemento);
  }

  icono(elemento: ElementoC4) {
    if (elemento.tipo === 'container') return 'contenedor';
    if (elemento.tipo === 'component') return 'componente';
    if (elemento.tipo === 'person') return 'persona';
    return 'sistema';
  }
}
