import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  LucideCheck,
  LucideX,
  LucideFileSearch,
  LucideGitBranch,
  LucideSparkles,
  LucideAlertTriangle,
  LucideCircle,
  LucideMoveUpRight,
  LucideImage,
} from '@lucide/angular';
import { ElementoC4, EvidenciaCandidatoC4, RelacionC4 } from '../../modelos/c4.model';
import { DiagramaModalC4 } from '../modal-diagramas-c4/modal-diagramas-c4';

@Component({
  selector: 'app-panel-detalle-c4',
  standalone: true,
  imports: [
    CommonModule,
    LucideCheck,
    LucideX,
    LucideFileSearch,
    LucideGitBranch,
    LucideSparkles,
    LucideAlertTriangle,
    LucideCircle,
    LucideMoveUpRight,
    LucideImage,
  ],
  templateUrl: './panel-detalle-c4.html',
  styleUrl: './panel-detalle-c4.scss',
})
export class PanelDetalleC4 {
  @Input() elemento: ElementoC4 | null = null;
  @Input() relacion: RelacionC4 | null = null;
  @Input() puedeDecidir = false;
  @Input() nombrePadre = '';
  @Input() diagramas: DiagramaModalC4[] = [];
  @Output() decidir = new EventEmitter<'APROBADO' | 'RECHAZADO'>();
  @Output() verDiagrama = new EventEmitter<DiagramaModalC4>();

  etiquetaTipo(tipo: string) {
    const etiquetas: Record<string, string> = {
      container: 'Contenedor',
      component: 'Componente',
      software_system: 'Sistema de software',
      person: 'Persona',
      external_system: 'Sistema externo',
    };
    return etiquetas[tipo] || tipo;
  }

  etiquetaDerivacion(derivacion?: string | null) {
    const etiquetas: Record<string, string> = {
      import_python: 'Import directo verificado',
      import_fuente: 'Import directo verificado',
      base_datos: 'Configuración de base de datos',
      contexto_analista: 'Confirmada por el analista',
      inferencia: 'Inferida por agente',
    };
    return etiquetas[derivacion || ''] || derivacion || 'Origen no indicado';
  }

  etiquetaMarcado(marcado?: string | null) {
    const etiquetas: Record<string, string> = {
      sin_evidencia_import: 'Sin evidencia de import directo',
      probable_duplicado: 'Posible duplicado de otra capacidad',
    };
    return etiquetas[marcado || ''] || marcado || '';
  }

  etiquetaNivelDiagrama(nivel: string) {
    const etiquetas: Record<string, string> = {
      context: 'Contexto',
      containers: 'Contenedores',
      components: 'Componentes',
    };
    return etiquetas[nivel] || nivel;
  }

  nombreDiagrama(diagrama: DiagramaModalC4) {
    const base = this.etiquetaNivelDiagrama(diagrama.nivel);
    if (diagrama.nivel === 'components' && this.elemento?.nombre) {
      return `Componentes de ${this.elemento.nombre}`;
    }
    return `Vista de ${base.toLowerCase()}`;
  }

  diagramasPorNivel() {
    const niveles: { nivel: string; diagramas: DiagramaModalC4[] }[] = [];
    for (const diagrama of this.diagramas) {
      const grupo = niveles.find((item) => item.nivel === diagrama.nivel);
      if (grupo) {
        grupo.diagramas.push(diagrama);
      } else {
        niveles.push({ nivel: diagrama.nivel, diagramas: [diagrama] });
      }
    }
    const orden = ['context', 'containers', 'components'];
    return niveles.sort((a, b) => {
      const ia = orden.indexOf(a.nivel);
      const ib = orden.indexOf(b.nivel);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
  }

  ubicacion(evidencia: EvidenciaCandidatoC4) {
    if (evidencia.linea_inicio == null) return evidencia.ruta;
    const rango =
      evidencia.linea_fin != null && evidencia.linea_fin !== evidencia.linea_inicio
        ? `${evidencia.linea_inicio}-${evidencia.linea_fin}`
        : `${evidencia.linea_inicio}`;
    return `${evidencia.ruta}:${rango}`;
  }
}
