import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root',
})
export class AutenticacionService {
  private http = inject(HttpClient);

  private apiUrl = 'http://127.0.0.1:8000/autenticacion';

  registrar(datos: any) {
    return this.http.post(`${this.apiUrl}/registro`, datos);
  }

  login(datos: any) {
    return this.http.post(`${this.apiUrl}/login`, datos);
  }
}