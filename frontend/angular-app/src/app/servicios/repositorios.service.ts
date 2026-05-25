import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root',
})
export class RepositoriosService {
  private http = inject(HttpClient);

  private apiRepositorios = 'http://127.0.0.1:8000/repositorios';
  private apiDocumentacion = 'http://127.0.0.1:8000/documentacion';

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