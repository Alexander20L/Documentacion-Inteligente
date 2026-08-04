import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { CrearEjecucionC4 } from '../modelos/c4.model';
import { API_BASE_URL } from './api.config';
import { C4Service } from './c4.service';

describe('C4Service', () => {
  let service: C4Service;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(C4Service);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('creates a run with its guided context', () => {
    const solicitud: CrearEjecucionC4 = {
      contexto: {
        nombre_sistema: 'Portal',
        descripcion: 'Gestiona solicitudes',
        proposito: 'Centralizar la operacion',
        actores: [{ nombre: 'Operador', descripcion: 'Gestiona solicitudes' }],
        sistemas_externos: [],
      },
    };

    service.crearEjecucion('repo-1', solicitud).subscribe();

    const request = http.expectOne(`${API_BASE_URL}/repositorios/repo-1/c4/ejecuciones`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(solicitud);
    request.flush({});
  });

  it('requests artifacts as authenticated blobs', () => {
    service.descargarArtefacto('repo-1', 'run-1', 'artifact-1').subscribe();

    const request = http.expectOne(
      `${API_BASE_URL}/repositorios/repo-1/c4/ejecuciones/run-1/artefactos/artifact-1`,
    );
    expect(request.request.method).toBe('GET');
    expect(request.request.responseType).toBe('blob');
    request.flush(new Blob());
  });
});
