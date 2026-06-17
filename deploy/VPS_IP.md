# Despliegue en VPS con IP pública

## Objetivo

- Frontend público en `http://84.247.191.38/`
- Backend FastAPI interno en `127.0.0.1:8001`
- Nginx sirviendo Angular y haciendo proxy a FastAPI

## Backend

1. Crear el entorno virtual dentro de `backend/`:

```bash
cd /root/Documentacion-Inteligente/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

2. Configurar variables de entorno del backend:

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_ANON_KEY=...
SUPABASE_JWT_AUDIENCE=authenticated
GEMINI_API_KEY=...
CORS_ORIGINS=http://84.247.191.38
```

3. Levantar backend y worker con PM2:

```bash
cd /root/Documentacion-Inteligente
pm2 start ecosystem.config.cjs
pm2 save
```

## Frontend

1. Usar Node `20.19.0` o superior compatible con Angular 21.
2. Instalar dependencias y generar el build:

```bash
cd /root/Documentacion-Inteligente/frontend/angular-app
npm install
npm run build
```

3. Configurar `public/runtime-config.js` antes de servir Angular:

```js
window.__DOCUGRAPH_ENV__ = {
  apiBaseUrl: '',
  supabaseUrl: 'https://TU-PROYECTO.supabase.co',
  supabaseAnonKey: 'TU_ANON_KEY',
};
```

El build debe quedar en:

`/root/Documentacion-Inteligente/frontend/angular-app/dist/angular-app/browser`

## Nginx

1. Copiar `deploy/nginx/documentacion-inteligente.conf` a la VPS.
2. Enlazarlo como sitio activo.
3. Recargar Nginx.

Ejemplo:

```bash
sudo cp /root/Documentacion-Inteligente/deploy/nginx/documentacion-inteligente.conf /etc/nginx/sites-available/documentacion-inteligente
sudo ln -sf /etc/nginx/sites-available/documentacion-inteligente /etc/nginx/sites-enabled/documentacion-inteligente
sudo nginx -t
sudo systemctl reload nginx
```

## Resultado esperado

- `http://84.247.191.38/` carga Angular
- `http://84.247.191.38/repositorios/` responde FastAPI
- el navegador ya no usa `:3000` ni `:8001`
- los archivos del análisis se consultan desde el backend autenticado
