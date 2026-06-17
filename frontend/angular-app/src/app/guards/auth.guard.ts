import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AutenticacionService } from '../servicios/autenticacion.service';

export const authGuard: CanActivateFn = async (_route, state) => {
  const autenticacionService = inject(AutenticacionService);
  const router = inject(Router);

  if (await autenticacionService.estaAutenticado()) {
    return true;
  }

  return router.createUrlTree(['/login'], {
    queryParams: { redirectTo: state.url },
  });
};
