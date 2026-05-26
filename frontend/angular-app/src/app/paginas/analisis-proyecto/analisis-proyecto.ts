import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { RepositoriosService } from '../../servicios/repositorios.service';

@Component({
  selector: 'app-analisis-proyecto',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './analisis-proyecto.html',
  styleUrl: './analisis-proyecto.scss',
})
export class AnalisisProyecto {
  private repositoriosService = inject(RepositoriosService);
  private detectorCambios = inject(ChangeDetectorRef);

  archivoSeleccionado: File | null = null;
  cargando = false;
  mensaje = '';

  urlGrafo = '';
  urlJson = '';
  urlReporte = '';
  mensajeResultado = '';

  seleccionarArchivo(evento: Event) {
    const input = evento.target as HTMLInputElement;

    if (!input.files || input.files.length === 0) return;

    this.archivoSeleccionado = input.files[0];

    this.urlGrafo = '';
    this.urlJson = '';
    this.urlReporte = '';
    this.mensajeResultado = '';
  }

  subirYAnalizar() {
    if (!this.archivoSeleccionado) {
      alert('Selecciona un archivo ZIP primero');
      return;
    }

    this.cargando = true;

    this.urlGrafo = '';
    this.urlJson = '';
    this.urlReporte = '';
    this.mensajeResultado = '';

    this.repositoriosService.subirRepositorio(this.archivoSeleccionado).subscribe({
      next: (respuestaSubida: any) => {
        const usuarioGuardado = localStorage.getItem('usuario');

        if (!usuarioGuardado) {
          alert('No hay usuario en sesión');
          this.cargando = false;
          this.detectorCambios.detectChanges();
          return;
        }

        const usuario = JSON.parse(usuarioGuardado);

        this.repositoriosService
          .analizarRepositorio(
            respuestaSubida.id_repositorio,
            usuario.id,
            respuestaSubida.nombre_archivo
          )
          .subscribe({
            next: (respuestaAnalisis: any) => {
              const archivos = respuestaAnalisis.archivos || {};
              const disponibles = respuestaAnalisis.disponibles || {};
              const mensajes = respuestaAnalisis.mensajes || {};

              this.urlGrafo = archivos.html || '';
              this.urlJson = archivos.json || '';
              this.urlReporte = archivos.reporte || '';
              this.mensajeResultado = [
                !disponibles.html ? mensajes.html : '',
                !disponibles.reporte ? mensajes.reporte : '',
              ]
                .filter(Boolean)
                .join(' ');

              this.cargando = false;
              this.detectorCambios.detectChanges();
            },
            error: (error) => {
              this.cargando = false;
              console.error(error);
              this.detectorCambios.detectChanges();
            },
          });
      },
      error: (error) => {
        this.cargando = false;
        console.error(error);
        this.detectorCambios.detectChanges();
      },
    });
  }
}
