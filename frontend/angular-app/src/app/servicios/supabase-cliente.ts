import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { environment } from '../../environments/environment';

let cliente: SupabaseClient | null = null;

export function supabaseConfigurado() {
  return Boolean(environment.supabaseUrl && environment.supabaseAnonKey);
}

export function obtenerClienteSupabase() {
  if (!supabaseConfigurado()) {
    throw new Error(
      'Falta configurar Supabase en frontend/angular-app/public/runtime-config.js'
    );
  }

  if (!cliente) {
    cliente = createClient(environment.supabaseUrl, environment.supabaseAnonKey, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    });
  }

  return cliente;
}
