module.exports = {
  apps: [
    {
      name: 'documentacion-backend',
      cwd: './backend',
      script: './.venv/bin/gunicorn',
      args: '-k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8001 --workers 2 --timeout 300 --access-logfile - --error-logfile - --capture-output --log-level info',
      interpreter: 'none',
      env: {
        PORT: 8001,
        PUBLIC_BACKEND_URL: process.env.PUBLIC_BACKEND_URL || 'http://127.0.0.1:8001',
        CORS_ORIGINS:
          process.env.CORS_ORIGINS ||
          'http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:4200,http://localhost:4200',
      },
    },
    {
      name: 'documentacion-frontend',
      cwd: './frontend/angular-app',
      script: 'serve-spa.cjs',
      interpreter: 'node',
      env: {
        PORT: 3000,
      },
    },
  ],
};