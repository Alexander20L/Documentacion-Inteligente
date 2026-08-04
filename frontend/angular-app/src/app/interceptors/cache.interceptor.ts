import { HttpInterceptorFn } from '@angular/common/http';
import { API_BASE_URL } from '../servicios/api.config';

export const cacheInterceptor: HttpInterceptorFn = (request, next) => {
  if (request.method !== 'GET' || !request.url.startsWith(API_BASE_URL)) {
    return next(request);
  }
  return next(
    request.clone({
      setHeaders: {
        'Cache-Control': 'no-store, no-cache, must-revalidate',
        Pragma: 'no-cache',
        Expires: '0',
      },
    })
  );
};
