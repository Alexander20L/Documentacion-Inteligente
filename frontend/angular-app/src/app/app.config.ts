import { APP_INITIALIZER, ApplicationConfig, inject } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';

import { routes } from './app.routes';
import { AutenticacionService } from './servicios/autenticacion.service';
import { authInterceptor } from './interceptors/auth.interceptor';

function inicializarAutenticacion() {
  const autenticacionService = inject(AutenticacionService);
  return () => autenticacionService.inicializar();
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor])),
    {
      provide: APP_INITIALIZER,
      multi: true,
      useFactory: inicializarAutenticacion,
    },
  ],
};
