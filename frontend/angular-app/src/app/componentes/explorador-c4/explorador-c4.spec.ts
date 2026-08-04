import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { ElementoC4 } from '../../modelos/c4.model';
import { ExploradorC4Pagina, esSvgMermaid } from './explorador-c4';

describe('esSvgMermaid', () => {
  it('detecta un SVG de Mermaid por su firma', () => {
    expect(esSvgMermaid('<svg id="my-svg" class="flowchart" viewBox="0 0 100 100"></svg>')).toBe(
      true,
    );
  });

  it('no marca un SVG de PlantUML como Mermaid', () => {
    expect(
      esSvgMermaid(
        '<svg xmlns="http://www.w3.org/2000/svg" data-diagram-type="DESCRIPTION" viewBox="0 0 100 100"><?plantuml 1.2026.6?></svg>',
      ),
    ).toBe(false);
  });

  it('devuelve false con contenido vacío', () => {
    expect(esSvgMermaid('')).toBe(false);
  });
});

function elemento(
  parcial: Partial<ElementoC4> & { id: string; nombre: string; tipo: string },
): ElementoC4 {
  return {
    descripcion: '',
    inferido: false,
    decision: 'APROBADO',
    ...parcial,
  };
}

describe('ExploradorC4Pagina', () => {
  let component: ExploradorC4Pagina;
  let fixture: ComponentFixture<ExploradorC4Pagina>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ExploradorC4Pagina],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => '' } } },
        },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(ExploradorC4Pagina);
    component = fixture.componentInstance;
  });

  it('filtra los diagramas que mencionan el elemento por texto normalizado', () => {
    const contenedor = elemento({
      id: 'c1',
      nombre: 'Base de datos PostgreSQL',
      tipo: 'container',
    });
    component.diagramas = [
      {
        id: 'd1',
        nombre: 'Contenedores',
        nivel: 'containers',
        svg: '<svg><text>Base de datos PostgreSQL</text></svg>',
        texto: 'base de datos postgresql',
      },
      {
        id: 'd2',
        nombre: 'Componentes',
        nivel: 'components',
        svg: '<svg><text>Gestión de Usuarios</text></svg>',
        texto: 'gestion de usuarios',
      },
    ];

    const resultado = component.diagramasDelElemento(contenedor);
    expect(resultado.map((d) => d.id)).toEqual(['d1']);
  });

  it('no devuelve diagramas cuando ninguno menciona el elemento', () => {
    const contenedor = elemento({ id: 'c1', nombre: 'Otro', tipo: 'container' });
    component.diagramas = [
      {
        id: 'd1',
        nombre: 'Contenedores',
        nivel: 'containers',
        svg: '<svg><text>Base de datos PostgreSQL</text></svg>',
        texto: 'base de datos postgresql',
      },
    ];

    expect(component.diagramasDelElemento(contenedor)).toEqual([]);
  });
});
