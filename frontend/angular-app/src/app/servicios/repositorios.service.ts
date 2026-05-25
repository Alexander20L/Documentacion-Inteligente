import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { API_BASE_URL } from './api.config';

@Injectable({
  providedIn: 'root',
})
export class RepositoriosService {
  private http = inject(HttpClient);

  private apiRepositorios = `${API_BASE_URL}/repositorios`;
  private apiDocumentacion = `${API_BASE_URL}/documentacion`;

  subirRepositorio(archivo: File) {
    const formData = new FormData();
    formData.append('archivo', archivo);

    return this.http.post(`${this.apiRepositorios}/subir`, formData);
  }

  analizarRepositorio(
    idRepositorio: string,
    usuarioId: string,
    nombreArchivo: string
  ) {
    return this.http.post(
      `${this.apiRepositorios}/${idRepositorio}/analizar`,
      {},
      {
        params: {
          usuario_id: usuarioId,
          nombre_archivo: nombreArchivo,
        },
      }
    );
  }

  obtenerHistorial() {
    return this.http.get(`${this.apiRepositorios}/historial`);
  }

  generarDocumentacion(idRepositorio: string) {
    return this.http.post(
      `${this.apiDocumentacion}/${idRepositorio}/generar`,
      {}
    );
  }

  verDocumentacion(idRepositorio: string) {
  return this.http.get(
    `${this.apiDocumentacion}/${idRepositorio}/ver`
  );
}
}