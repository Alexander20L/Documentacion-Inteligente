import { Observable, timer, merge } from 'rxjs';
import { share } from 'rxjs/operators';

/**
 * Emite en intervalos regulares y además re-emite inmediatamente cuando la
 * pestaña vuelve a ser visible (el navegador pausa los timers en background,
 * por lo que sin este evento las vistas con polling parecen "congeladas" hasta
 * que el usuario vuelve).
 *
 * La primera emisión ocurre en t=0 para cargar de inmediato. Cada evento de
 * visibilidad vuelve a emitir para forzar una carga fresca sin esperar el
 * siguiente intervalo.
 */
export function pollingReanudable(intervaloMs: number): Observable<number> {
  const intervalos = timer(0, intervaloMs);
  const alVolverVisible = new Observable<number>((suscriptor) => {
    const handler = () => {
      if (document.visibilityState === 'visible') {
        suscriptor.next(Date.now());
      }
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  });
  return merge(intervalos, alVolverVisible).pipe(share());
}
