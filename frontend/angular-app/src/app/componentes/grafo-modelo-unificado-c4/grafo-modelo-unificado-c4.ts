import {
  AfterViewInit,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  inject,
  Input,
  Output,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ElementoC4, RelacionC4 } from '../../modelos/c4.model';

interface CajaRender {
  elemento: ElementoC4;
  x: number;
  y: number;
  ancho: number;
  alto: number;
  hCabecera: number;
  tipo: 'sistema' | 'contenedor' | 'elemento';
  colapsado: boolean;
  tieneHijos: boolean;
  nivel: number;
}

interface ConexionRender {
  puntos: { x: number; y: number }[];
  tecnologia?: string | null;
  mx: number;
  my: number;
}
const W_COMPONENTE = 220;
const H_COMPONENTE = 84;
const W_ENTIDAD = 250;
const H_ENTIDAD = 96;
const H_CAB_CONTENEDOR = 40;
const H_CAB_SISTEMA = 44;
const PAD = 14;
const PAD_CONTENIDO = 60;
const ALTO_CUERPO_VACIO = 112;
const GAP_COMPONENTE = 72;
const GAP_CONTENEDOR = 140;
const GAP_PRINCIPAL = 80;
const ANCHO_MIN_CONTENEDOR = 320;
const ANCHO_MIN_SISTEMA = 380;

const COLORES: Record<string, string> = {
  software_system: '#0b3133',
  container: '#315c89',
  component: '#116466',
  person: '#57340b',
  external_system: '#7a4a8f',
};

function colorDe(tipo: string): string {
  return COLORES[tipo] || '#5a6472';
}

function etiquetaTipo(tipo: string): string {
  const etiquetas: Record<string, string> = {
    software_system: 'Sistema',
    container: 'Contenedor',
    component: 'Componente',
    person: 'Persona',
    external_system: 'Externo',
  };
  return etiquetas[tipo] || tipo;
}

@Component({
  selector: 'app-grafo-modelo-unificado-c4',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="grafo-unificado">
      <div class="barra-lienzo">
        <strong class="titulo-lienzo">Modelo C4 completo</strong>
        <div class="controles" aria-label="Controles del lienzo">
          <button type="button" (click)="acercar()" title="Acercar">+</button>
          <button type="button" (click)="alejar()" title="Alejar">−</button>
          <button type="button" (click)="ajustar()" title="Ajustar al lienzo">Ajustar</button>
          <button type="button" (click)="tamanoReal()" title="Tamaño real">100%</button>
        </div>
      </div>
      <div class="leyenda" aria-label="Leyenda de tipos">
        <span *ngFor="let item of leyenda" class="leyenda-item">
          <i class="punto" [style.background]="item.color"></i>{{ item.nombre }}
        </span>
      </div>
      <div class="viewport" #viewport (wheel)="onRueda($event)" (pointerdown)="onPulsar($event)">
        <div class="mundo" #mundo>
          <svg
            [attr.viewBox]="viewBox"
            [attr.width]="anchoSvg"
            [attr.height]="altoSvg"
            class="svg-grafo"
            (click)="clickFondo($event)"
          >
            <defs>
              <marker
                id="flecha-unificado"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#8a93a0"></path>
              </marker>
            </defs>

            <g *ngFor="let caja of cajas">
              <g
                [attr.transform]="'translate(' + caja.x + ',' + caja.y + ')'"
                class="caja"
                [class.caja-nivel]="caja.tipo !== 'elemento'"
                [class.seleccionada]="seleccionadoId === caja.elemento.id"
                [attr.role]="'button'"
                [attr.tabindex]="0"
                (keydown.enter)="seleccionar.emit(caja.elemento.id)"
                (click)="seleccionar.emit(caja.elemento.id)"
              >
                <ng-container *ngIf="caja.tipo !== 'elemento'">
                  <rect
                    class="fondo-nivel"
                    [attr.width]="caja.ancho"
                    [attr.height]="caja.alto"
                    rx="10"
                    ry="10"
                  ></rect>
                  <rect
                    class="cabecera"
                    [attr.width]="caja.ancho"
                    [attr.height]="caja.hCabecera"
                    rx="10"
                    ry="10"
                    [attr.fill]="colorDe(caja.elemento.tipo)"
                  ></rect>
                  <rect
                    class="cabecera-bajo"
                    [attr.width]="caja.ancho"
                    [attr.y]="caja.hCabecera - 8"
                    [attr.height]="8"
                    [attr.fill]="colorDe(caja.elemento.tipo)"
                  ></rect>
                  <g
                    *ngIf="caja.tieneHijos"
                    class="chevron"
                    (click)="alternar($event, caja.elemento.id)"
                    [attr.transform]="
                      'translate(' + (caja.ancho - 18) + ',' + caja.hCabecera / 2 + ')'
                    "
                  >
                    <circle r="8" [attr.fill]="colorDe(caja.elemento.tipo)"></circle>
                    <text y="3.5" text-anchor="middle" fill="#fff" font-size="12" font-weight="800">
                      {{ caja.colapsado ? '+' : '−' }}
                    </text>
                  </g>
                  <text
                    class="nombre-cabecera"
                    [attr.x]="caja.ancho / 2"
                    [attr.y]="caja.hCabecera / 2 + 1"
                    text-anchor="middle"
                    dominant-baseline="middle"
                    fill="#fff"
                    font-size="13"
                    font-weight="700"
                  >
                    {{ truncar(caja.elemento.nombre, 34) }}
                  </text>
                  <g *ngIf="!caja.tieneHijos" class="cuerpo-vacio">
                    <svg
                      class="icono-cuerpo-vacio"
                      [attr.x]="caja.ancho / 2 - 27"
                      [attr.y]="caja.hCabecera + 14"
                      width="54"
                      height="54"
                      viewBox="0 0 24 24"
                      fill="none"
                      [attr.stroke]="colorDe(caja.elemento.tipo)"
                      stroke-width="1.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <path
                        *ngFor="let d of pathsIcono(iconoDe(caja.elemento))"
                        [attr.d]="d"
                      ></path>
                    </svg>
                    <text
                      text-anchor="middle"
                      [attr.x]="caja.ancho / 2"
                      [attr.y]="caja.hCabecera + 82"
                      fill="#5a6472"
                      font-size="10"
                      font-weight="700"
                      letter-spacing="0.08em"
                    >
                      {{ etiquetaTipo(caja.elemento.tipo).toUpperCase() }}
                    </text>
                  </g>
                </ng-container>
                <ng-container *ngIf="caja.tipo === 'elemento'">
                  <rect
                    class="rect-elemento"
                    [attr.width]="caja.ancho"
                    [attr.height]="caja.alto"
                    rx="8"
                    ry="8"
                    [attr.fill]="colorFondo(caja.elemento.tipo)"
                    [attr.stroke]="colorDe(caja.elemento.tipo)"
                  ></rect>
                  <rect
                    class="banda-elemento"
                    [attr.width]="caja.ancho"
                    [attr.height]="6"
                    rx="8"
                    ry="8"
                    [attr.fill]="colorDe(caja.elemento.tipo)"
                  ></rect>
                  <g
                    [attr.transform]="'translate(' + caja.ancho / 2 + ',' + 24 + ')'"
                    class="icono-elemento"
                  >
                    <svg
                      width="26"
                      height="26"
                      viewBox="0 0 24 24"
                      fill="none"
                      [attr.stroke]="colorDe(caja.elemento.tipo)"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      [attr.transform]="'translate(-13,-13)'"
                    >
                      <path
                        *ngFor="let d of pathsIcono(iconoDe(caja.elemento))"
                        [attr.d]="d"
                      ></path>
                    </svg>
                  </g>
                  <text
                    [attr.x]="caja.ancho / 2"
                    [attr.y]="52"
                    text-anchor="middle"
                    class="nombre-elemento"
                  >
                    {{ truncar(caja.elemento.nombre, 26) }}
                  </text>
                  <text
                    [attr.x]="caja.ancho / 2"
                    [attr.y]="68"
                    text-anchor="middle"
                    class="tipo-elemento"
                  >
                    {{ etiquetaTipo(caja.elemento.tipo) }}
                  </text>
                </ng-container>
              </g>
            </g>

            <g *ngFor="let conexion of conexiones">
              <path [attr.d]="rutaD(conexion.puntos)" class="linea-halo" fill="none"></path>
              <path
                [attr.d]="rutaD(conexion.puntos)"
                class="linea-relacion"
                fill="none"
                marker-end="url(#flecha-unificado)"
              ></path>
              <g
                [attr.transform]="'translate(' + conexion.mx + ',' + conexion.my + ')'"
                class="etiqueta-relacion"
                *ngIf="conexion.tecnologia"
              >
                <rect
                  [attr.x]="-(conexion.tecnologia.length * 6.4) / 2 - 5"
                  [attr.y]="-11"
                  [attr.width]="conexion.tecnologia.length * 6.4 + 10"
                  [attr.height]="19"
                  rx="9"
                  ry="9"
                ></rect>
                <text
                  text-anchor="middle"
                  dominant-baseline="middle"
                  font-size="9.5"
                  font-weight="600"
                  fill="#405064"
                >
                  {{ conexion.tecnologia }}
                </text>
              </g>
            </g>
          </svg>
        </div>
      </div>
      <p class="pista">
        Arrastra para mover · rueda para zoom · clic en un elemento para ver su detalle · clic en
        {{ '−' }}/{{ '+' }} para colapsar un nivel
      </p>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        width: 100%;
        height: 100%;
      }
      .grafo-unificado {
        display: flex;
        flex-direction: column;
        height: 100%;
        min-height: 460px;
        border: 1px solid var(--line);
        border-radius: 12px;
        overflow: hidden;
        background: #f4f5f4;
      }
      .barra-lienzo {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 12px;
        background: #fff;
        border-bottom: 1px solid var(--line);
      }
      .titulo-lienzo {
        font-size: 0.8rem;
        color: #405064;
        flex: 1;
      }
      .controles {
        display: flex;
        gap: 4px;
      }
      .controles button {
        padding: 5px 11px;
        border: 1px solid var(--line);
        border-radius: 7px;
        background: #fff;
        color: #405064;
        font-weight: 800;
        font-size: 0.76rem;
        cursor: pointer;
      }
      .controles button:hover {
        background: #eef1f4;
      }
      .leyenda {
        display: flex;
        flex-wrap: wrap;
        gap: 6px 14px;
        padding: 7px 12px;
        background: #fff;
        border-bottom: 1px solid var(--line);
        font-size: 0.7rem;
        color: #5a6472;
      }
      .leyenda-item {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-weight: 700;
      }
      .leyenda-item .punto {
        width: 10px;
        height: 10px;
        border-radius: 3px;
        display: inline-block;
      }
      .viewport {
        flex: 1;
        position: relative;
        overflow: hidden;
        touch-action: none;
        cursor: grab;
      }
      .viewport.paneando {
        cursor: grabbing;
      }
      .mundo {
        position: absolute;
        top: 0;
        left: 0;
        transform-origin: 0 0;
      }
      .svg-grafo {
        display: block;
        max-width: none;
      }
      .pista {
        padding: 6px 12px;
        font-size: 0.7rem;
        color: #8a93a0;
        background: #fff;
        border-top: 1px solid var(--line);
      }

      .caja {
        cursor: pointer;
        user-select: none;
      }
      .caja:hover .fondo-nivel {
        stroke: #0b3133;
        stroke-width: 2.5;
      }
      .caja:hover .rect-elemento {
        filter: brightness(1.02);
      }
      .caja.seleccionada .fondo-nivel {
        stroke: #e11d48;
        stroke-width: 3;
      }
      .caja.seleccionada .rect-elemento {
        stroke: #e11d48;
        stroke-width: 3;
      }
      .fondo-nivel {
        fill: #f4f8f8;
        stroke: #c8d0d6;
        stroke-width: 1.5;
      }
      .cabecera-bajo {
        pointer-events: none;
      }
      .nombre-elemento {
        fill: #1c2733;
        font-size: 12px;
        font-weight: 700;
      }
      .tipo-elemento {
        fill: #5a6472;
        font-size: 9.5px;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      .chevron {
        cursor: pointer;
      }
      .chevron:hover circle {
        filter: brightness(1.2);
      }
      .linea-halo {
        stroke: #fff;
        stroke-width: 6;
        stroke-linejoin: round;
      }
      .linea-relacion {
        stroke: #5c6b7a;
        stroke-width: 2;
        stroke-linejoin: round;
      }
      .etiqueta-relacion rect {
        fill: #fff;
        stroke: #d8dcdf;
      }
      .svg-grafo text {
        font-family: 'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace;
      }
    `,
  ],
})
export class GrafoModeloUnificadoC4 implements AfterViewInit {
  private readonly changeDetector = inject(ChangeDetectorRef);

  @ViewChild('viewport') private viewportRef?: ElementRef<HTMLDivElement>;
  @ViewChild('mundo') private mundoRef?: ElementRef<HTMLDivElement>;

  @Input() set elementos(value: ElementoC4[]) {
    this._elementos = value;
    this.calcular();
  }
  @Input() set relaciones(value: RelacionC4[]) {
    this._relaciones = value;
    this.calcular();
  }
  @Input() seleccionadoId = '';
  @Output() seleccionar = new EventEmitter<string>();

  _elementos: ElementoC4[] = [];
  _relaciones: RelacionC4[] = [];
  cajas: CajaRender[] = [];
  conexiones: ConexionRender[] = [];
  viewBox = '0 0 800 600';
  anchoSvg = 800;
  altoSvg = 600;

  readonly leyenda = [
    { color: '#0b3133', nombre: 'Sistema' },
    { color: '#315c89', nombre: 'Contenedor' },
    { color: '#116466', nombre: 'Componente' },
    { color: '#57340b', nombre: 'Persona' },
    { color: '#7a4a8f', nombre: 'Externo' },
  ];

  private colapsados = new Set<string>();
  private escala = 1;
  private tx = 0;
  private ty = 0;
  private arrastrando = false;
  private ultimoX = 0;
  private ultimoY = 0;

  ngAfterViewInit() {
    queueMicrotask(() => this.ajustar());
  }

  truncar(texto: string, maxCaracteres: number): string {
    if (texto.length <= maxCaracteres) return texto;
    return texto.slice(0, maxCaracteres - 1).trimEnd() + '…';
  }

  colorDe(tipo: string): string {
    return colorDe(tipo);
  }

  colorFondo(tipo: string): string {
    const fondos: Record<string, string> = {
      software_system: '#e6efef',
      container: '#e3ecf3',
      component: '#e0f0ee',
      person: '#f0e7d8',
      external_system: '#ece4f0',
    };
    return fondos[tipo] || '#eef1f4';
  }

  etiquetaTipo(tipo: string): string {
    return etiquetaTipo(tipo);
  }

  iconoDe(elemento: ElementoC4): string {
    if (elemento.tipo === 'person') return 'user';
    if (elemento.tipo === 'external_system') return 'external';
    if (elemento.tipo === 'software_system') return 'system';
    if (elemento.tipo === 'component') return 'component';
    const nombre = elemento.nombre.toLowerCase();
    if (
      nombre.includes('base de datos') ||
      nombre.includes('database') ||
      nombre.includes('postgres') ||
      nombre.includes('sql') ||
      nombre.includes('almacen')
    ) {
      return 'database';
    }
    return 'server';
  }

  pathsIcono(clave: string): string[] {
    const iconos: Record<string, string[]> = {
      user: ['M20 21v-1a8 8 0 0 0-16 0v1', 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z'],
      database: [
        'M3 5a9 3 0 0 0 18 0a9 3 0 0 0-18 0',
        'M3 5v14a9 3 0 0 0 18 0V5',
        'M3 12a9 3 0 0 0 18 0',
      ],
      server: ['M2 4h20', 'M2 12h20', 'M2 20h20', 'M6 4v0', 'M6 12v0', 'M6 20v0'],
      component: [
        'M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z',
        'm3.3 7 8.7 5 8.7-5',
        'M12 22V12',
      ],
      system: ['M12 2a15.3 15.3 0 0 1 0 20 15.3 15.3 0 0 1 0-20', 'M2 12h20'],
      external: ['M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z'],
    };
    return iconos[clave] || iconos['system'];
  }

  private calcular() {
    const elementos = this._elementos;
    if (!elementos.length) {
      this.cajas = [];
      this.conexiones = [];
      return;
    }
    const porId = new Map(elementos.map((item) => [item.id, item]));
    const hijosDe = new Map<string, ElementoC4[]>();
    for (const elemento of elementos) {
      const padre = elemento.padre_id && porId.has(elemento.padre_id) ? elemento.padre_id : '';
      if (!hijosDe.has(padre)) hijosDe.set(padre, []);
      hijosDe.get(padre)!.push(elemento);
    }

    const esHoja = (tipo: string) =>
      tipo === 'component' || tipo === 'person' || tipo === 'external_system';

    const medir = (elemento: ElementoC4): { w: number; h: number } => {
      const hijos = hijosDe.get(elemento.id) ?? [];
      const visible = hijos.filter(
        (hijo) => !(this.colapsados.has(hijo.id) && !esHoja(hijo.tipo)),
      ).length;
      const colapsado = this.colapsados.has(elemento.id);
      if (elemento.tipo === 'container') {
        if (colapsado || !visible) {
          return { w: ANCHO_MIN_CONTENEDOR, h: H_CAB_CONTENEDOR + ALTO_CUERPO_VACIO };
        }
        const cols = Math.max(1, Math.ceil(Math.sqrt(visible)));
        const rows = Math.ceil(visible / cols);
        const ancho = Math.max(
          ANCHO_MIN_CONTENEDOR,
          cols * W_COMPONENTE + (cols - 1) * GAP_COMPONENTE + PAD_CONTENIDO * 2,
        );
        const alto =
          H_CAB_CONTENEDOR + rows * H_COMPONENTE + (rows - 1) * GAP_COMPONENTE + PAD_CONTENIDO * 2;
        return { w: ancho, h: alto };
      }
      if (elemento.tipo === 'software_system') {
        if (colapsado || !visible) {
          return { w: ANCHO_MIN_SISTEMA, h: H_CAB_SISTEMA + ALTO_CUERPO_VACIO };
        }
        const contenedores = hijos.filter((hijo) => hijo.tipo === 'container');
        const anchos = contenedores.map((contenedor) => medir(contenedor).w);
        const totalAncho = anchos.reduce((a, b) => a + b, 0) + (anchos.length - 1) * GAP_CONTENEDOR;
        const maxAlto = Math.max(0, ...contenedores.map((contenedor) => medir(contenedor).h));
        return {
          w: Math.max(ANCHO_MIN_SISTEMA, totalAncho + PAD_CONTENIDO * 2),
          h: H_CAB_SISTEMA + maxAlto + PAD_CONTENIDO * 2,
        };
      }
      if (esHoja(elemento.tipo)) {
        return elemento.tipo === 'component'
          ? { w: W_COMPONENTE, h: H_COMPONENTE }
          : { w: W_ENTIDAD, h: H_ENTIDAD };
      }
      return { w: ANCHO_MIN_SISTEMA, h: H_CAB_SISTEMA + ALTO_CUERPO_VACIO };
    };

    const cajas: CajaRender[] = [];
    const colocar = (elemento: ElementoC4, x: number, y: number, nivel: number, esTop: boolean) => {
      const medida = medir(elemento);
      const esNivel = elemento.tipo === 'software_system' || elemento.tipo === 'container';
      const colapsado = this.colapsados.has(elemento.id);
      const hijos = hijosDe.get(elemento.id) ?? [];
      const tieneHijos =
        esNivel && hijos.some((hijo) => !(this.colapsados.has(hijo.id) && !esHoja(hijo.tipo)));
      cajas.push({
        elemento,
        x,
        y,
        ancho: medida.w,
        alto: medida.h,
        hCabecera:
          elemento.tipo === 'software_system'
            ? H_CAB_SISTEMA
            : elemento.tipo === 'container'
              ? H_CAB_CONTENEDOR
              : 0,
        tipo: esNivel
          ? elemento.tipo === 'software_system'
            ? 'sistema'
            : 'contenedor'
          : 'elemento',
        colapsado,
        tieneHijos,
        nivel,
      });
      if (!tieneHijos || colapsado) return;
      if (elemento.tipo === 'container') {
        const cols = Math.max(1, Math.ceil(Math.sqrt(hijos.length)));
        hijos.forEach((hijo, indice) => {
          const cx = x + PAD_CONTENIDO + (indice % cols) * (W_COMPONENTE + GAP_COMPONENTE);
          const cy =
            y +
            H_CAB_CONTENEDOR +
            PAD_CONTENIDO +
            Math.floor(indice / cols) * (H_COMPONENTE + GAP_COMPONENTE);
          colocar(hijo, cx, cy, nivel + 1, false);
        });
      } else if (elemento.tipo === 'software_system') {
        let cx = x + PAD_CONTENIDO;
        for (const contenedor of hijos.filter((hijo) => hijo.tipo === 'container')) {
          colocar(contenedor, cx, y + H_CAB_SISTEMA + PAD_CONTENIDO, nivel + 1, false);
          cx += medir(contenedor).w + GAP_CONTENEDOR;
        }
      }
    };

    const topLevel = elementos
      .filter((elemento) => {
        if (elemento.padre_id && porId.has(elemento.padre_id)) return false;
        const padre = elemento.padre_id ? porId.get(elemento.padre_id)! : null;
        return !padre || padre.tipo !== 'software_system';
      })
      .sort((a, b) => {
        const orden = ['person', 'external_system', 'software_system'];
        return orden.indexOf(a.tipo) - orden.indexOf(b.tipo);
      });

    let xCursor = PAD;
    const yTop = PAD;
    for (const top of topLevel) {
      colocar(top, xCursor, yTop, 0, true);
      xCursor += medir(top).w + GAP_PRINCIPAL;
    }

    this.cajas = cajas;
    this.anchoSvg = Math.max(600, xCursor - GAP_PRINCIPAL + PAD);
    this.altoSvg = Math.max(400, Math.max(...cajas.map((c) => c.y + c.alto)) + PAD);
    this.viewBox = `0 0 ${this.anchoSvg} ${this.altoSvg}`;

    const cajaPorId = new Map(cajas.map((caja) => [caja.elemento.id, caja]));
    const pares: { relacion: RelacionC4; origen: CajaRender; destino: CajaRender }[] = [];
    for (const relacion of this._relaciones) {
      const origen = cajaPorId.get(relacion.origen_id);
      const destino = cajaPorId.get(relacion.destino_id);
      if (!origen || !destino) continue;
      pares.push({ relacion, origen, destino });
    }
    const anclados: { relacion: RelacionC4; origen: CajaRender; destino: CajaRender }[] = [];
    for (const par of pares) {
      const origen = this.anclar(par.origen, par.destino, cajaPorId);
      const destino = this.anclar(par.destino, par.origen, cajaPorId);
      if (origen.elemento.id === destino.elemento.id) continue;
      anclados.push({ relacion: par.relacion, origen, destino });
    }
    const porPar = new Map<string, typeof anclados>();
    for (const par of anclados) {
      const clave = `${par.origen.elemento.id}>${par.destino.elemento.id}`;
      if (!porPar.has(clave)) porPar.set(clave, []);
      porPar.get(clave)!.push(par);
    }
    const conexiones: ConexionRender[] = [];
    for (const grupo of porPar.values()) {
      grupo.forEach((par, indice) => {
        const p1 = this.puntoBorde(
          par.origen,
          par.destino.x + par.destino.ancho / 2,
          par.destino.y + par.destino.alto / 2,
        );
        const p2 = this.puntoBorde(
          par.destino,
          par.origen.x + par.origen.ancho / 2,
          par.origen.y + par.origen.alto / 2,
        );
        const dx = p2.x - p1.x;
        const dy = p2.y - p1.y;
        const len = Math.hypot(dx, dy) || 1;
        const nx = -dy / len;
        const ny = dx / len;
        const lado = indice % 2 === 0 ? 1 : -1;
        const offset = lado * 10 * Math.ceil((indice + 1) / 2);
        const p1Off = { x: p1.x + nx * offset, y: p1.y + ny * offset };
        const p2Off = { x: p2.x + nx * offset, y: p2.y + ny * offset };
        const puntos = [p1Off, p2Off];
        const etiqueta = this.posicionEtiqueta(p1Off, p2Off, cajas);
        conexiones.push({
          puntos,
          tecnologia: par.relacion.tecnologia,
          mx: etiqueta.x,
          my: etiqueta.y,
        });
      });
    }
    this.conexiones = conexiones;
  }

  rutaD(puntos: { x: number; y: number }[]): string {
    if (!puntos.length) return '';
    let d = `M ${puntos[0].x} ${puntos[0].y}`;
    for (let i = 1; i < puntos.length; i++) {
      d += ` L ${puntos[i].x} ${puntos[i].y}`;
    }
    return d;
  }

  private posicionEtiqueta(
    p1: { x: number; y: number },
    p2: { x: number; y: number },
    cajas: CajaRender[],
  ) {
    const mx = (p1.x + p2.x) / 2;
    const my = (p1.y + p2.y) / 2;
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len;
    const ny = dx / len;
    let mejor = { x: mx, y: my, dist: -1 };
    for (let paso = 0; paso <= 8; paso++) {
      const off = 10 + paso * 8;
      const c = { x: mx + nx * off, y: my + ny * off };
      const d = this.distanciaACajaMasCercana(c.x, c.y, cajas);
      if (d >= 0 && (mejor.dist < 0 || d > mejor.dist)) {
        mejor = { x: c.x, y: c.y, dist: d };
      }
    }
    return { x: mejor.x, y: mejor.y };
  }

  private anclar(
    caja: CajaRender,
    otraCaja: CajaRender,
    cajaPorId: Map<string, CajaRender>,
  ): CajaRender {
    if (caja.elemento.tipo !== 'component') return caja;
    const padreId = caja.elemento.padre_id;
    const cajaPadre = padreId ? cajaPorId.get(padreId) : undefined;
    if (!cajaPadre) return caja;
    const mismoContenedor =
      otraCaja.elemento.tipo === 'component' && otraCaja.elemento.padre_id === padreId;
    if (mismoContenedor) return caja;
    return cajaPadre;
  }

  private distanciaACajaMasCercana(x: number, y: number, cajas: CajaRender[]) {
    let minimo = -1;
    for (const caja of cajas) {
      const dentro =
        x >= caja.x - 6 &&
        x <= caja.x + caja.ancho + 6 &&
        y >= caja.y - 6 &&
        y <= caja.y + caja.alto + 6;
      if (dentro) {
        const dx = Math.max(caja.x - x, 0, x - (caja.x + caja.ancho));
        const dy = Math.max(caja.y - y, 0, y - (caja.y + caja.alto));
        const dist = Math.hypot(dx, dy);
        if (minimo < 0 || dist < minimo) minimo = dist;
      }
    }
    return minimo;
  }

  private puntoBorde(caja: CajaRender, tx: number, ty: number) {
    const cx = caja.x + caja.ancho / 2;
    const cy = caja.y + caja.alto / 2;
    const dx = tx - cx;
    const dy = ty - cy;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const txEscala = Math.abs(ux) > 0.0001 ? caja.ancho / 2 / Math.abs(ux) : Infinity;
    const tyEscala = Math.abs(uy) > 0.0001 ? caja.alto / 2 / Math.abs(uy) : Infinity;
    const t = Math.min(txEscala, tyEscala);
    return { x: cx + ux * t, y: cy + uy * t };
  }

  alternar(evento: Event, id: string) {
    evento.stopPropagation();
    if (this.colapsados.has(id)) {
      this.colapsados.delete(id);
    } else {
      this.colapsados.add(id);
    }
    this.calcular();
  }

  clickFondo(evento: MouseEvent) {
    if ((evento.target as SVGElement).tagName === 'svg') {
      this.seleccionar.emit('');
    }
  }

  private aplicarTransformacion() {
    const mundo = this.mundoRef?.nativeElement;
    if (!mundo) return;
    mundo.style.transform = `translate(${this.tx}px, ${this.ty}px) scale(${this.escala})`;
  }

  onRueda(evento: WheelEvent) {
    evento.preventDefault();
    const factor = evento.deltaY < 0 ? 1.12 : 1 / 1.12;
    this.escala = Math.min(8, Math.max(0.1, this.escala * factor));
    this.aplicarTransformacion();
  }

  onPulsar(evento: PointerEvent) {
    if (evento.button !== 0) return;
    this.arrastrando = true;
    this.ultimoX = evento.clientX;
    this.ultimoY = evento.clientY;
    this.viewportRef?.nativeElement.classList.add('paneando');
    const mover = (movimiento: PointerEvent) => {
      if (!this.arrastrando) return;
      this.tx += movimiento.clientX - this.ultimoX;
      this.ty += movimiento.clientY - this.ultimoY;
      this.ultimoX = movimiento.clientX;
      this.ultimoY = movimiento.clientY;
      this.aplicarTransformacion();
    };
    const soltar = () => {
      this.arrastrando = false;
      this.viewportRef?.nativeElement.classList.remove('paneando');
      window.removeEventListener('pointermove', mover);
      window.removeEventListener('pointerup', soltar);
    };
    window.addEventListener('pointermove', mover);
    window.addEventListener('pointerup', soltar);
  }

  acercar() {
    this.escala = Math.min(8, this.escala * 1.25);
    this.aplicarTransformacion();
  }

  alejar() {
    this.escala = Math.max(0.1, this.escala / 1.25);
    this.aplicarTransformacion();
  }

  ajustar() {
    const viewport = this.viewportRef?.nativeElement;
    if (!viewport) return;
    const vw = viewport.clientWidth || 600;
    const vh = viewport.clientHeight || 400;
    this.escala = Math.max(0.05, Math.min((vw - 40) / this.anchoSvg, (vh - 40) / this.altoSvg));
    this.tx = (vw - this.anchoSvg * this.escala) / 2;
    this.ty = (vh - this.altoSvg * this.escala) / 2;
    this.aplicarTransformacion();
  }

  tamanoReal() {
    this.escala = 1;
    this.tx = 0;
    this.ty = 0;
    this.aplicarTransformacion();
  }
}
