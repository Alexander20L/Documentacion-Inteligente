import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AutenticacionService } from '../servicios/autenticacion.service';

export const guestGuard: CanActivateFn = async () => {
  const autenticacionService = inject(AutenticacionService);
  const router = inject(Router);

  if (await autenticacionService.estaAutenticado()) {
    return router.createUrlTree(['/dashboard']);
  }

  return true;
};
