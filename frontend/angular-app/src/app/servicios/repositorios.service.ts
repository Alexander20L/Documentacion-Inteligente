import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { API_BASE_URL } from './api.config';

export type NombreArchivoGraphify =
  | 'graph.json'
  | 'manifest.json'
  | '.graphify_analysis.json'
  | 'graph.html'
  | 'GRAPH_REPORT.md';

export interface EstadoArchivosGraphify {
  archivos: {
    json: string | null;
    manifest: string | null;
    analysis: string | null;
    html: string | null;
    reporte: string | null;
  };
  disponibles: {
    json: boolean;
    manifest: boolean;
    analysis: boolean;
    html: boolean;
    reporte: boolean;
  };
  mensajes: {
    html?: string;
    reporte?: string;
  };
}

export interface RespuestaSubidaRepositorio {
  mensaje: string;
  id_repositorio: string;
  nombre_archivo: string;
}

export interface RespuestaAnalisisRepositorio extends EstadoArchivosGraphify {
  mensaje: string;
  id_repositorio: string;
}

export interface ProyectoHistorial extends EstadoArchivosGraphify {
  id_repositorio: string;
  nombre_archivo: string;
  estado: string;
  creado_en?: string;
  created_at?: string;
  estado_documentacion?: string;
  error_ultimo?: string | null;
  url_graph_html: string | null;
  url_graph_json: string | null;
  url_reporte: string | null;
  url_word: string | null;
}

export interface TareaProyecto {
  id: string;
  id_repositorio: string;
  tipo: 'analisis' | 'documentacion';
  estado: 'pendiente' | 'procesando' | 'completado' | 'fallido';
  error_ultimo?: string | null;
  payload?: Record<string, unknown>;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface RespuestaHistorialProyectos {
  mensaje: string;
  proyectos: ProyectoHistorial[];
}

export interface RespuestaEncolarTarea {
  mensaje: string;
  id_repositorio: string;
  tarea: TareaProyecto;
  estado?: string;
  estado_documentacion?: string;
}

export interface RespuestaEstadoProyecto {
  mensaje: string;
  proyecto: ProyectoHistorial;
  tareas: TareaProyecto[];
}

export interface RespuestaGenerarDocumentacion {
  mensaje: string;
  id_repositorio: string;
  documentacion: string;
  url_word: string;
}

export interface RespuestaVerDocumentacion {
  mensaje: string;
  id_repositorio: string;
  documentacion: string;
}

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

    return this.http.post<RespuestaSubidaRepositorio>(`${this.apiRepositorios}/subir`, formData);
  }

  analizarRepositorio(idRepositorio: string, nombreArchivo: string) {
    return this.http.post<RespuestaEncolarTarea>(
      `${this.apiRepositorios}/${idRepositorio}/analizar`,
      {
        nombre_archivo: nombreArchivo,
      }
    );
  }

  obtenerHistorial() {
    return this.http.get<RespuestaHistorialProyectos>(`${this.apiRepositorios}/historial`);
  }

  generarDocumentacion(idRepositorio: string) {
    return this.http.post<RespuestaEncolarTarea>(
      `${this.apiDocumentacion}/${idRepositorio}/generar`,
      {}
    );
  }

  obtenerEstadoProyecto(idRepositorio: string) {
    return this.http.get<RespuestaEstadoProyecto>(`${this.apiRepositorios}/${idRepositorio}/estado`);
  }

  verDocumentacion(idRepositorio: string) {
    return this.http.get<RespuestaVerDocumentacion>(
      `${this.apiDocumentacion}/${idRepositorio}/ver`
    );
  }

  obtenerArchivoGraphify(idRepositorio: string, nombreArchivo: NombreArchivoGraphify) {
    return this.http.get(`${this.apiRepositorios}/${idRepositorio}/${nombreArchivo}`, {
      responseType: 'blob',
    });
  }

  descargarWord(idRepositorio: string) {
    return this.http.get(`${this.apiDocumentacion}/${idRepositorio}/word`, {
      responseType: 'blob',
    });
  }
}
