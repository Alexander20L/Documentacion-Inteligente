import { computed, Injectable, signal } from '@angular/core';
import { type Session } from '@supabase/supabase-js';
import { obtenerClienteSupabase, supabaseConfigurado } from './supabase-cliente';

export interface RegistroUsuarioPayload {
  nombre: string;
  correo: string;
  contrasena: string;
}

export interface LoginUsuarioPayload {
  correo: string;
  contrasena: string;
}

@Injectable({
  providedIn: 'root',
})
export class AutenticacionService {
  private readonly session = signal<Session | null>(null);

  readonly usuarioActual = computed(() => {
    const user = this.session()?.user;

    if (!user) {
      return null;
    }

    return {
      id: user.id,
      nombre:
        user.user_metadata['nombre'] ||
        user.user_metadata['full_name'] ||
        user.email ||
        'Usuario',
      correo: user.email || '',
    };
  });

  async inicializar() {
    if (!supabaseConfigurado()) {
      return;
    }

    const supabase = obtenerClienteSupabase();
    const { data, error } = await supabase.auth.getSession();

    if (error) {
      throw new Error(error.message);
    }

    this.session.set(data.session);
    supabase.auth.onAuthStateChange((_evento, session) => {
      this.session.set(session);
    });
  }

  async registrar(datos: RegistroUsuarioPayload) {
    const { data, error } = await obtenerClienteSupabase().auth.signUp({
      email: datos.correo,
      password: datos.contrasena,
      options: {
        data: {
          nombre: datos.nombre,
          full_name: datos.nombre,
        },
      },
    });

    if (error) {
      throw new Error(error.message);
    }

    this.session.set(data.session);
    return data;
  }

  async login(datos: LoginUsuarioPayload) {
    const { data, error } = await obtenerClienteSupabase().auth.signInWithPassword({
      email: datos.correo,
      password: datos.contrasena,
    });

    if (error) {
      throw new Error(error.message);
    }

    this.session.set(data.session);
    return data;
  }

  async logout() {
    const { error } = await obtenerClienteSupabase().auth.signOut();

    if (error) {
      throw new Error(error.message);
    }

    this.session.set(null);
  }

  async obtenerAccessToken() {
    if (this.session()) {
      return this.session()?.access_token ?? null;
    }

    if (!supabaseConfigurado()) {
      return null;
    }

    const { data, error } = await obtenerClienteSupabase().auth.getSession();

    if (error) {
      throw new Error(error.message);
    }

    this.session.set(data.session);
    return data.session?.access_token ?? null;
  }

  async estaAutenticado() {
    return Boolean(await this.obtenerAccessToken());
  }

  obtenerMensajeError(error: unknown, fallback = 'Ocurrió un error inesperado') {
    if (error instanceof Error && error.message) {
      return error.message;
    }

    return fallback;
  }
}
