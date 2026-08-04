import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ModalDiagramasC4 } from './modal-diagramas-c4';

describe('ModalDiagramasC4', () => {
  let component: ModalDiagramasC4;
  let fixture: ComponentFixture<ModalDiagramasC4>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ModalDiagramasC4],
    }).compileComponents();
    fixture = TestBed.createComponent(ModalDiagramasC4);
    component = fixture.componentInstance;
  });

  it('lista solo los niveles presentes', () => {
    component.diagramas = [
      { id: 'd1', nombre: 'Contenedores', nivel: 'containers', svg: '<svg></svg>' },
      { id: 'd2', nombre: 'Componentes', nivel: 'components', svg: '<svg></svg>' },
    ];
    expect(component.nivelesPresentes).toEqual(['containers', 'components']);
  });

  it('fija el nivel e indice inicial segun el diagrama inicial', () => {
    component.diagramas = [
      { id: 'd1', nombre: 'Contenedores', nivel: 'containers', svg: '<svg></svg>' },
      { id: 'd2', nombre: 'Componentes 1', nivel: 'components', svg: '<svg></svg>' },
      { id: 'd3', nombre: 'Componentes 2', nivel: 'components', svg: '<svg></svg>' },
    ];
    component.diagramaInicial = component.diagramas[2];
    expect(component.nivelActual).toBe('components');
    expect(component.indiceActual).toBe(1);
    expect(component.diagramaActual?.id).toBe('d3');
  });

  it('navega anterior y siguiente con vuelta', () => {
    component.diagramas = [
      { id: 'd1', nombre: 'Contenedores', nivel: 'containers', svg: '<svg></svg>' },
      { id: 'd2', nombre: 'Componentes 1', nivel: 'components', svg: '<svg></svg>' },
      { id: 'd3', nombre: 'Componentes 2', nivel: 'components', svg: '<svg></svg>' },
    ];
    component.nivelActual = 'components';
    component.indiceActual = 0;
    component.anterior();
    expect(component.indiceActual).toBe(1);
    component.siguiente();
    expect(component.indiceActual).toBe(0);
    component.siguiente();
    expect(component.indiceActual).toBe(1);
    component.siguiente();
    expect(component.indiceActual).toBe(0);
  });
});
