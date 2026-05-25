export const API_HOST = (() => {
  if (typeof window === 'undefined') {
    return '127.0.0.1';
  }

  return window.location.hostname;
})();

export const API_PORT = API_HOST === 'localhost' || API_HOST === '127.0.0.1' ? '8000' : '8001';

export const API_BASE_URL = `http://${API_HOST}:${API_PORT}`;