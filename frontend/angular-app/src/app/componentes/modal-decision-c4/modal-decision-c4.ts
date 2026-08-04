import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LucideCheck, LucideX, LucideAlertTriangle } from '@lucide/angular';

@Component({
  selector: 'app-modal-decision-c4',
  standalone: true,
  imports: [CommonModule, LucideCheck, LucideX, LucideAlertTriangle],
  templateUrl: './modal-decision-c4.html',
  styleUrl: './modal-decision-c4.scss',
})
export class ModalDecisionC4 {
  @Input() abierto = false;
  @Input() nombre = '';
  @Input() decision: 'APROBADO' | 'RECHAZADO' = 'APROBADO';
  @Input() enProgreso = false;
  @Output() confirmar = new EventEmitter<void>();
  @Output() cancelar = new EventEmitter<void>();
}
