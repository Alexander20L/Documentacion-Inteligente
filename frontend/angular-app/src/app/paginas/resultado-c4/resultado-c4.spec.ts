import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { agruparArtefactos, ResultadoC4 } from './resultado-c4';

describe('agruparArtefactos', () => {
  it('groups artifacts from optional type and label metadata', () => {
    const grupos = agruparArtefactos([
      { id: '1', nombre: 'indice.json', tipo: 'semantic_index' },
      { id: '2', nombre: 'evidencia.json', etiqueta: 'Evidencia RAG' },
      { id: '3', nombre: 'juez.json', tipo: 'judge', etiqueta: 'Informe del juez' },
      { id: '4', nombre: 'modelo.dsl' },
    ]);

    expect(grupos.map((grupo) => [grupo.clave, grupo.artefactos.length])).toEqual([
      ['semantica', 1],
      ['rag', 1],
      ['agentes', 1],
      ['c4', 1],
    ]);
  });

  it('keeps artifacts without classification metadata in the C4 group', () => {
    expect(agruparArtefactos([{ id: '1', nombre: 'rag-named-only.json' }])[0].clave).toBe('c4');
  });
});

describe('ResultadoC4', () => {
  let component: ResultadoC4;
  let fixture: ComponentFixture<ResultadoC4>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ResultadoC4],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => '' } } },
        },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(ResultadoC4);
    component = fixture.componentInstance;
  });

  it('agrupa diagramas por nivel y separa plantuml de mermaid', () => {
    component.diagramas = [
      {
        id: 'd1',
        nombre: 'context-plantuml.svg',
        nivel: 'context',
        url: 'blob:1',
        origen: 'plantuml',
      },
      {
        id: 'd2',
        nombre: 'context-mermaid.svg',
        nivel: 'context',
        url: 'blob:2',
        origen: 'mermaid',
      },
      {
        id: 'd3',
        nombre: 'containers-plantuml.svg',
        nivel: 'containers',
        url: 'blob:3',
        origen: 'plantuml',
      },
    ];

    const grupos = component.diagramasPorNivel();
    expect(grupos.map((grupo) => grupo.nivel)).toEqual(['context', 'containers']);
    expect(grupos[0].plantuml.map((d) => d.id)).toEqual(['d1']);
    expect(grupos[0].mermaid.map((d) => d.id)).toEqual(['d2']);
  });

  it('usa etiqueta de nivel en español', () => {
    expect(component.etiquetaNivel('components')).toBe('Componentes');
  });

  it('separa nombre y extension', () => {
    expect(component.sinExtension('canonical-model.json')).toBe('canonical-model');
    expect(component.extension('canonical-model.json')).toBe('json');
    expect(component.sinExtension('sin-extension')).toBe('sin-extension');
    expect(component.extension('sin-extension')).toBe('');
  });

  it('selecciona pestaña de artefactos y ajusta la activa si falta', () => {
    component.gruposArtefactosPestanas([
      { id: '1', nombre: 'juez.json', tipo: 'judge' },
      { id: '2', nombre: 'modelo.dsl' },
    ]);
    expect(component.pestanaArtefactos).toBe('c4');
    component.seleccionarPestanaArtefactos('agentes');
    expect(component.pestanaArtefactos).toBe('agentes');
    component.gruposArtefactosPestanas([
      { id: '3', nombre: 'evidencia.json', etiqueta: 'Evidencia RAG' },
    ]);
    expect(component.pestanaArtefactos).toBe('rag');
  });

  it('abre y cierra el modal de diagrama', () => {
    const diagrama = {
      id: 'd1',
      nombre: 'context.svg',
      nivel: 'context',
      url: 'blob:1',
      origen: 'plantuml',
    };
    component.abrirDiagrama(diagrama);
    expect(component.diagramaAbierto?.id).toBe('d1');
    expect(component.zoomModal).toBe(1);
    expect(component.panX).toBe(0);
    component.cerrarDiagrama();
    expect(component.diagramaAbierto).toBeNull();
  });

  it('acerca, aleja y reinicia el zoom del modal', () => {
    component.zoomModal = 1;
    component.acercarModal();
    expect(component.zoomModal).toBeGreaterThan(1);
    component.alejarModal();
    expect(component.zoomModal).toBe(1);
    component.acercarModal();
    component.panX = 40;
    component.panY = -20;
    component.reiniciarZoomModal();
    expect(component.zoomModal).toBe(1);
    expect(component.panX).toBe(0);
    expect(component.panY).toBe(0);
  });
});
