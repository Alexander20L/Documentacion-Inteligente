import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { API_BASE_URL } from './api.config';

@Injectable({
  providedIn: 'root',
})
export class AutenticacionService {
  private http = inject(HttpClient);

  private apiUrl = `${API_BASE_URL}/autenticacion`;

  registrar(datos: any) {
    return this.http.post(`${this.apiUrl}/registro`, datos);
  }

  login(datos: any) {
    return this.http.post(`${this.apiUrl}/login`, datos);
  }
}