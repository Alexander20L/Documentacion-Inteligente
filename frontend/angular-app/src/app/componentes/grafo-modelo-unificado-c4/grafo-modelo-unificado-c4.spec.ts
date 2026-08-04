import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ElementoC4, RelacionC4 } from '../../modelos/c4.model';
import { GrafoModeloUnificadoC4 } from './grafo-modelo-unificado-c4';

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

describe('GrafoModeloUnificadoC4', () => {
  let component: GrafoModeloUnificadoC4;
  let fixture: ComponentFixture<GrafoModeloUnificadoC4>;

  const sistema = elemento({ id: 's1', nombre: 'Portal', tipo: 'software_system' });
  const contenedor = elemento({ id: 'c1', nombre: 'API', tipo: 'container', padre_id: 's1' });
  const componente = elemento({ id: 'cp1', nombre: 'Auth', tipo: 'component', padre_id: 'c1' });
  const relacion: RelacionC4 = {
    id: 'r1',
    nombre: 'Llama',
    descripcion: '',
    origen_id: 'cp1',
    destino_id: 'cp1',
    tecnologia: 'Python',
    inferido: false,
    decision: 'APROBADO',
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [GrafoModeloUnificadoC4],
    }).compileComponents();
    fixture = TestBed.createComponent(GrafoModeloUnificadoC4);
    component = fixture.componentInstance;
  });

  it('coloca el sistema, el contenedor y el componente anidados', () => {
    component.elementos = [sistema, contenedor, componente];
    component.relaciones = [relacion];
    fixture.detectChanges();

    expect(component.cajas.length).toBe(3);
    const ids = component.cajas.map((caja) => caja.elemento.id);
    expect(ids).toContain('s1');
    expect(ids).toContain('c1');
    expect(ids).toContain('cp1');
    const cajaSistema = component.cajas.find((caja) => caja.elemento.id === 's1')!;
    const cajaContenedor = component.cajas.find((caja) => caja.elemento.id === 'c1')!;
    const cajaComponente = component.cajas.find((caja) => caja.elemento.id === 'cp1')!;
    expect(cajaComponente.x).toBeGreaterThanOrEqual(cajaContenedor.x);
    expect(cajaComponente.y).toBeGreaterThan(cajaContenedor.y);
    expect(cajaContenedor.x).toBeGreaterThanOrEqual(cajaSistema.x);
  });

  it('emite la seleccion al hacer clic en un elemento', () => {
    component.elementos = [sistema, contenedor, componente];
    component.relaciones = [];
    fixture.detectChanges();

    let seleccionado = '';
    component.seleccionar.subscribe((id) => (seleccionado = id));
    const caja = component.cajas.find((caja) => caja.elemento.id === 'cp1')!;
    component.seleccionar.emit(caja.elemento.id);
    expect(seleccionado).toBe('cp1');
  });

  it('no genera conexiones cuando falta algun extremo', () => {
    component.elementos = [sistema, contenedor];
    component.relaciones = [relacion];
    fixture.detectChanges();

    expect(component.conexiones.length).toBe(0);
  });

  it('eleva al ancestro comun las relaciones entre componentes de contenedores distintos', () => {
    const contenedor2 = elemento({
      id: 'c2',
      nombre: 'Almacen',
      tipo: 'container',
      padre_id: 's1',
    });
    const componente2 = elemento({
      id: 'cp2',
      nombre: 'Repositorio',
      tipo: 'component',
      padre_id: 'c2',
    });
    const relacionCruzada: RelacionC4 = {
      id: 'r2',
      nombre: 'Usa',
      descripcion: '',
      origen_id: 'cp1',
      destino_id: 'cp2',
      tecnologia: 'Python',
      inferido: false,
      decision: 'APROBADO',
    };
    component.elementos = [sistema, contenedor, componente, contenedor2, componente2];
    component.relaciones = [relacionCruzada];
    fixture.detectChanges();

    expect(component.conexiones.length).toBe(1);
    const conexion = component.conexiones[0];
    expect(conexion.tecnologia).toBe('Python');
  });

  it('mantiene internas las relaciones entre componentes del mismo contenedor', () => {
    const componente2 = elemento({
      id: 'cp2',
      nombre: 'Perfil',
      tipo: 'component',
      padre_id: 'c1',
    });
    const relacionInterna: RelacionC4 = {
      id: 'r3',
      nombre: 'Depende',
      descripcion: '',
      origen_id: 'cp1',
      destino_id: 'cp2',
      tecnologia: 'Python import',
      inferido: false,
      decision: 'APROBADO',
    };
    component.elementos = [sistema, contenedor, componente, componente2];
    component.relaciones = [relacionInterna];
    fixture.detectChanges();

    expect(component.conexiones.length).toBe(1);
    expect(component.conexiones[0].tecnologia).toBe('Python import');
  });

  it('dibuja la conexion entre contenedores como una linea recta de dos puntos', () => {
    const contenedor2 = elemento({
      id: 'c2',
      nombre: 'Almacen',
      tipo: 'container',
      padre_id: 's1',
    });
    const relacionCruzada: RelacionC4 = {
      id: 'r4',
      nombre: 'Usa',
      descripcion: '',
      origen_id: 'c1',
      destino_id: 'c2',
      tecnologia: 'SQL',
      inferido: false,
      decision: 'APROBADO',
    };
    component.elementos = [sistema, contenedor, contenedor2];
    component.relaciones = [relacionCruzada];
    fixture.detectChanges();

    expect(component.conexiones.length).toBe(1);
    const puntos = component.conexiones[0].puntos;
    expect(puntos.length).toBe(2);
    expect(puntos[0].x).not.toBe(puntos[1].x);
    expect(component.rutaD(puntos)).toMatch(/^M /);
  });

  it('confina las conexiones internas dentro del contenedor padre', () => {
    const componente2 = elemento({
      id: 'cp2',
      nombre: 'Perfil',
      tipo: 'component',
      padre_id: 'c1',
    });
    const relacionInterna: RelacionC4 = {
      id: 'r5',
      nombre: 'Depende',
      descripcion: '',
      origen_id: 'cp1',
      destino_id: 'cp2',
      tecnologia: 'Python import',
      inferido: false,
      decision: 'APROBADO',
    };
    component.elementos = [sistema, contenedor, componente, componente2];
    component.relaciones = [relacionInterna];
    fixture.detectChanges();

    const cajaContenedor = component.cajas.find((caja) => caja.elemento.id === 'c1')!;
    const puntos = component.conexiones[0].puntos;
    for (const punto of puntos) {
      expect(punto.x).toBeGreaterThanOrEqual(cajaContenedor.x);
      expect(punto.x).toBeLessThanOrEqual(cajaContenedor.x + cajaContenedor.ancho);
      expect(punto.y).toBeGreaterThanOrEqual(cajaContenedor.y);
      expect(punto.y).toBeLessThanOrEqual(cajaContenedor.y + cajaContenedor.alto);
    }
  });

  it('asigna iconos por tipo: base de datos, persona y sistema', () => {
    const baseDatos = elemento({
      id: 'c2',
      nombre: 'Base de datos PostgreSQL',
      tipo: 'container',
      padre_id: 's1',
    });
    const persona = elemento({
      id: 'p1',
      nombre: 'Usuario de la plataforma',
      tipo: 'person',
    });
    component.elementos = [sistema, baseDatos, persona];
    fixture.detectChanges();

    expect(component.iconoDe(baseDatos)).toBe('database');
    expect(component.iconoDe(persona)).toBe('user');
    expect(component.iconoDe(sistema)).toBe('system');
    expect(component.pathsIcono('database').length).toBeGreaterThan(0);
  });

  it('da cuerpo alto a un contenedor sin hijos para mostrar el icono', () => {
    const baseDatos = elemento({
      id: 'c2',
      nombre: 'Base de datos PostgreSQL',
      tipo: 'container',
      padre_id: 's1',
    });
    component.elementos = [sistema, baseDatos];
    fixture.detectChanges();

    const caja = component.cajas.find((c) => c.elemento.id === 'c2')!;
    expect(caja.alto).toBeGreaterThan(120);
    expect(caja.tieneHijos).toBe(false);
  });
});
