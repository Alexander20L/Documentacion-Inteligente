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
import { ElementoC4 } from '../../modelos/c4.model';

export function normalizarNombre(texto: string): string {
  return texto
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\[.*?\]/g, ' ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

@Component({
  selector: 'app-lienzo-diagrama-c4',
  standalone: true,
  template: `
    <div class="lienzo-diagrama">
      <div class="barra-lienzo">
        <strong class="titulo-lienzo">{{ titulo }}</strong>
        <div class="controles" aria-label="Controles del lienzo">
          <button type="button" (click)="acercar()" title="Acercar">+</button>
          <button type="button" (click)="alejar()" title="Alejar">−</button>
          <button type="button" (click)="ajustar()" title="Ajustar al lienzo">Ajustar</button>
          <button type="button" (click)="tamanoReal()" title="Tamaño real">100%</button>
        </div>
      </div>
      <div class="viewport" #viewport (wheel)="onRueda($event)" (pointerdown)="onPulsar($event)">
        <div class="mundo" #mundo>
          <div class="svg-holder" #holder></div>
        </div>
      </div>
      <p class="pista">
        Arrastra para mover · rueda para zoom · clic en un elemento para ver su detalle
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
      .lienzo-diagrama {
        display: flex;
        flex-direction: column;
        height: 100%;
        min-height: 420px;
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
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
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
      .svg-holder svg {
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

      :host ::ng-deep .svg-holder g[data-c4-clicable] {
        cursor: pointer;
      }
      :host ::ng-deep .svg-holder g[data-c4-clicable]:hover rect {
        stroke: #e11d48;
        stroke-width: 3;
      }
      :host ::ng-deep .svg-holder g[data-c4-seleccionado] rect {
        stroke: #e11d48;
        stroke-width: 3.5;
      }
    `,
  ],
})
export class LienzoDiagramaC4 implements AfterViewInit {
  private readonly changeDetector = inject(ChangeDetectorRef);

  @ViewChild('viewport') private viewportRef?: ElementRef<HTMLDivElement>;
  @ViewChild('mundo') private mundoRef?: ElementRef<HTMLDivElement>;
  @ViewChild('holder') private holderRef?: ElementRef<HTMLDivElement>;

  @Input() set svgTexto(value: string) {
    this._svgTexto = value;
    this.inyectar();
  }
  @Input() set elementos(value: ElementoC4[]) {
    this._elementos = value;
    this.emparejar();
  }
  @Input() set seleccionadoId(value: string) {
    this._seleccionadoId = value;
    this.resaltarSeleccion();
  }
  @Input() titulo = 'Diagrama';
  @Output() seleccionar = new EventEmitter<string>();

  _svgTexto = '';
  _elementos: ElementoC4[] = [];
  _seleccionadoId = '';

  private escala = 1;
  private tx = 0;
  private ty = 0;
  private anchoSvg = 0;
  private altoSvg = 0;
  private arrastrando = false;
  private ultimoX = 0;
  private ultimoY = 0;
  private inyectado = false;

  ngAfterViewInit() {
    if (!this.inyectado) {
      queueMicrotask(() => {
        if (!this.inyectado) this.inyectar();
      });
    }
  }

  inyectar() {
    const holder = this.holderRef?.nativeElement;
    if (!holder || !this._svgTexto.trim()) return;
    holder.innerHTML = '';
    const contenedor = document.createElement('div');
    contenedor.innerHTML = this._svgTexto.trim();
    const svg = contenedor.querySelector('svg');
    if (!svg) {
      holder.textContent = '';
      return;
    }
    const vb = svg.getAttribute('viewBox') ?? '';
    const partes = vb.split(/\s+/).map(Number);
    this.anchoSvg = partes[2] || 600;
    this.altoSvg = partes[3] || 400;
    svg.setAttribute('style', `width:${this.anchoSvg}px;height:${this.altoSvg}px;`);
    holder.appendChild(svg);
    this.inyectado = true;
    this.emparejar();
    this.ajustar();
  }

  emparejar() {
    const svg = this.holderRef?.nativeElement?.querySelector('svg');
    if (!svg) return;
    for (const g of Array.from(svg.querySelectorAll('g'))) {
      const esEntidad =
        g.getAttribute('class')?.includes('entity') || g.getAttribute('class')?.includes('cluster');
      if (!esEntidad) continue;
      const textos = Array.from(g.children)
        .filter((hijo) => hijo.tagName === 'text')
        .map((hijo) => hijo.textContent ?? '')
        .join(' ');
      const normalizado = normalizarNombre(textos);
      const candidatos = this._elementos
        .filter((elemento) => {
          const nombre = normalizarNombre(elemento.nombre);
          return nombre.length > 3 && normalizado.includes(nombre);
        })
        .sort((a, b) => normalizarNombre(b.nombre).length - normalizarNombre(a.nombre).length);
      const match = candidatos[0];
      if (!match) continue;
      const idAnterior = g.getAttribute('data-c4-id');
      g.setAttribute('data-c4-clicable', 'true');
      g.setAttribute('data-c4-id', match.id);
      (g as SVGElement).style.cursor = 'pointer';
      if (idAnterior !== match.id) {
        g.addEventListener('click', (evento) => {
          evento.stopPropagation();
          this.seleccionar.emit(match.id);
        });
      }
    }
    this.resaltarSeleccion();
  }

  resaltarSeleccion() {
    const svg = this.holderRef?.nativeElement?.querySelector('svg');
    if (!svg) return;
    for (const g of Array.from(svg.querySelectorAll('g[data-c4-clicable]'))) {
      if (g.getAttribute('data-c4-id') === this._seleccionadoId) {
        g.setAttribute('data-c4-seleccionado', 'true');
      } else {
        g.removeAttribute('data-c4-seleccionado');
      }
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
    const nuevaEscala = Math.min(8, Math.max(0.1, this.escala * factor));
    this.escala = nuevaEscala;
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
    if (!viewport || !this.anchoSvg || !this.altoSvg) return;
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
