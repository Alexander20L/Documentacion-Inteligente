import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ElementoC4 } from '../../modelos/c4.model';
import { DiagramaModalC4 } from '../modal-diagramas-c4/modal-diagramas-c4';
import { PanelDetalleC4 } from './panel-detalle-c4';

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

describe('PanelDetalleC4', () => {
  let component: PanelDetalleC4;
  let fixture: ComponentFixture<PanelDetalleC4>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PanelDetalleC4],
    }).compileComponents();
    fixture = TestBed.createComponent(PanelDetalleC4);
    component = fixture.componentInstance;
  });

  it('muestra nombres cortos legibles en vez del nombre del archivo', () => {
    const diagrama: DiagramaModalC4 = {
      id: 'd1',
      nombre: 'structurizr-containers_element_93a5fe083a80bff0580d_0b5e21a1.svg',
      nivel: 'containers',
      svg: '<svg></svg>',
    };
    expect(component.nombreDiagrama(diagrama)).toBe('Vista de contenedores');
  });

  it('incluye el elemento en el nombre de los diagramas de componentes', () => {
    const contenedor = elemento({
      id: 'c1',
      nombre: 'Servidor de Aplicacion FastAPI',
      tipo: 'container',
    });
    component.elemento = contenedor;
    const diagrama: DiagramaModalC4 = {
      id: 'd2',
      nombre: 'structurizr-components_agent_element_125e23e3a6e82076aff0_b994c361.svg',
      nivel: 'components',
      svg: '<svg></svg>',
    };
    expect(component.nombreDiagrama(diagrama)).toBe(
      'Componentes de Servidor de Aplicacion FastAPI',
    );
  });

  it('emite verDiagrama al hacer clic', () => {
    const diagrama: DiagramaModalC4 = {
      id: 'd1',
      nombre: 'structurizr-containers_element_93a5fe083a80bff0580d_0b5e21a1.svg',
      nivel: 'containers',
      svg: '<svg></svg>',
    };
    const espia = vi.fn();
    component.verDiagrama.subscribe(espia);
    component.verDiagrama.emit(diagrama);
    expect(espia).toHaveBeenCalledWith(diagrama);
  });
});
