export const API_HOST = (() => {
  if (typeof window === 'undefined') {
    return '127.0.0.1';
  }

  return window.location.hostname;
})();

export const API_BASE_URL = (() => {
  if (typeof window === 'undefined') {
    return 'http://127.0.0.1:8001';
  }

  if (API_HOST === 'localhost' || API_HOST === '127.0.0.1') {
    return 'http://127.0.0.1:8001';
  }

  return `${window.location.protocol}//${window.location.hostname}:8001`;
})();