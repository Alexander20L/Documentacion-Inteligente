import { inject } from '@angular/core';
import { HttpInterceptorFn } from '@angular/common/http';
import { from } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { AutenticacionService } from '../servicios/autenticacion.service';

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const autenticacionService = inject(AutenticacionService);

  return from(autenticacionService.obtenerAccessToken()).pipe(
    switchMap((token) => {
      if (!token) {
        return next(request);
      }

      return next(
        request.clone({
          setHeaders: {
            Authorization: `Bearer ${token}`,
          },
        })
      );
    })
  );
};
