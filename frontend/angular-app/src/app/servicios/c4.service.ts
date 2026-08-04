import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import {
  CrearEjecucionC4,
  EjecucionC4,
  GuardarRevisionC4,
  HistorialC4,
  RevisionC4,
} from '../modelos/c4.model';
import { API_BASE_URL } from './api.config';

@Injectable({ providedIn: 'root' })
export class C4Service {
  private readonly http = inject(HttpClient);
  private readonly repositoriosUrl = `${API_BASE_URL}/repositorios`;

  crearEjecucion(idRepositorio: string, solicitud: CrearEjecucionC4) {
    return this.http.post<EjecucionC4>(this.ejecucionesUrl(idRepositorio), solicitud);
  }

  obtenerEjecucion(idRepositorio: string, idEjecucion: string) {
    return this.http.get<EjecucionC4>(`${this.ejecucionesUrl(idRepositorio)}/${idEjecucion}`);
  }

  obtenerRevision(idRepositorio: string, idEjecucion: string) {
    return this.http.get<RevisionC4>(
      `${this.ejecucionesUrl(idRepositorio)}/${idEjecucion}/revision`,
    );
  }

  guardarRevision(idRepositorio: string, idEjecucion: string, revision: GuardarRevisionC4) {
    return this.http.put<RevisionC4>(
      `${this.ejecucionesUrl(idRepositorio)}/${idEjecucion}/revision`,
      revision,
    );
  }

  aprobarRevision(idRepositorio: string, idEjecucion: string, revision: GuardarRevisionC4) {
    return this.http.post<EjecucionC4>(
      `${this.ejecucionesUrl(idRepositorio)}/${idEjecucion}/revision/aprobar`,
      revision,
    );
  }

  cancelarEjecucion(idRepositorio: string, idEjecucion: string) {
    return this.http.post<EjecucionC4>(
      `${this.ejecucionesUrl(idRepositorio)}/${idEjecucion}/cancelar`,
      {},
    );
  }

  reintentarEjecucion(idRepositorio: string, idEjecucion: string) {
    return this.http.post<EjecucionC4>(
      `${this.ejecucionesUrl(idRepositorio)}/${idEjecucion}/reintentar`,
      {},
    );
  }

  obtenerHistorial() {
    return this.http.get<HistorialC4>(`${this.repositoriosUrl}/historial`);
  }

  descargarArtefacto(idRepositorio: string, idEjecucion: string, idArtefacto: string) {
    return this.http.get(
      `${this.ejecucionesUrl(idRepositorio)}/${idEjecucion}/artefactos/${encodeURIComponent(idArtefacto)}`,
      { responseType: 'blob' },
    );
  }

  private ejecucionesUrl(idRepositorio: string) {
    return `${this.repositoriosUrl}/${idRepositorio}/c4/ejecuciones`;
  }
}
