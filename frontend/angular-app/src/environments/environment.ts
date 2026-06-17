declare global {
  interface Window {
    __DOCUGRAPH_ENV__?: {
      apiBaseUrl?: string;
      supabaseUrl?: string;
      supabaseAnonKey?: string;
    };
  }
}

const runtimeConfig = window.__DOCUGRAPH_ENV__ ?? {};
const hostname = window.location.hostname;
const isLocalhost = hostname === 'localhost' || hostname === '127.0.0.1';

export const environment = {
  production: !isLocalhost,
  apiBaseUrl:
    runtimeConfig.apiBaseUrl?.trim() ||
    (isLocalhost ? 'http://127.0.0.1:8000' : ''),

  supabaseUrl: runtimeConfig.supabaseUrl?.trim() || '',
  supabaseAnonKey: runtimeConfig.supabaseAnonKey?.trim() || '',
};

export {};