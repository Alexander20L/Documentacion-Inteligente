import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ElementoC4 } from '../../modelos/c4.model';
import { LienzoDiagramaC4, normalizarNombre } from './lienzo-diagrama-c4';

describe('normalizarNombre', () => {
  it('normaliza mayusculas, acentos y corchetes', () => {
    expect(normalizarNombre('Servidor de Aplicaci\u00f3n FastAPI')).toBe(
      'servidor de aplicacion fastapi',
    );
  });

  it('limpia marcas de tipo como [Software System]', () => {
    expect(normalizarNombre('FastAPI RealWorld API [Software System]')).toBe(
      'fastapi realworld api',
    );
  });
});

describe('LienzoDiagramaC4', () => {
  let component: LienzoDiagramaC4;
  let fixture: ComponentFixture<LienzoDiagramaC4>;

  const elementos: ElementoC4[] = [
    {
      id: 'e1',
      nombre: 'FastAPI RealWorld API',
      descripcion: 'Sistema principal',
      tipo: 'software_system',
      inferido: false,
      decision: 'APROBADO',
    },
    {
      id: 'e2',
      nombre: 'Base de datos PostgreSQL',
      descripcion: 'Persistencia',
      tipo: 'container',
      inferido: false,
      decision: 'APROBADO',
    },
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LienzoDiagramaC4],
    }).compileComponents();
    fixture = TestBed.createComponent(LienzoDiagramaC4);
    component = fixture.componentInstance;
  });

  it('marca como clicables las entidades que coinciden con elementos', async () => {
    const svg =
      '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">' +
      '<g class="entity"><text>FastAPI RealWorld API</text><rect></rect></g>' +
      '<g class="entity"><text>Otra cosa</text><rect></rect></g>' +
      '</svg>';
    component.elementos = elementos;
    component.svgTexto = svg;
    fixture.detectChanges();
    await fixture.whenStable();

    const svgElement = component['holderRef']?.nativeElement?.querySelector('svg');
    const clicables = svgElement
      ? Array.from(svgElement.querySelectorAll('g[data-c4-clicable]'))
      : [];
    expect(clicables.length).toBe(1);
    expect(clicables[0].getAttribute('data-c4-id')).toBe('e1');
  });
});
