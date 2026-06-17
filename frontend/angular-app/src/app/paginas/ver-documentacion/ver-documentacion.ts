import { CommonModule } from '@angular/common';
import { Component, inject, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { RepositoriosService } from '../../servicios/repositorios.service';

@Component({
  selector: 'app-ver-documentacion',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './ver-documentacion.html',
  styleUrl: './ver-documentacion.scss',
})
export class VerDocumentacion implements OnInit {
  private route = inject(ActivatedRoute);
  private repositoriosService = inject(RepositoriosService);

  documentacion = '';
  cargando = true;

  ngOnInit() {
    const idRepositorio = this.route.snapshot.paramMap.get('id');

    if (!idRepositorio) {
      this.documentacion = 'No se encontró el ID del repositorio.';
      this.cargando = false;
      return;
    }

    this.repositoriosService.verDocumentacion(idRepositorio).subscribe({
      next: (respuesta) => {
        this.documentacion = respuesta.documentacion || 'No hay contenido disponible.';
        this.cargando = false;
      },
      error: (error) => {
        this.documentacion =
          error?.error?.detail || 'La documentación todavía no ha sido generada.';
        this.cargando = false;
      },
    });
  }
}
