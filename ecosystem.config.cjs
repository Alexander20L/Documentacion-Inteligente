module.exports = {
  apps: [
    {
      name: 'documentacion-backend',
      cwd: './backend',
      script: './.venv/bin/gunicorn',
      args: '-k uvicorn.workers.UvicornWorker main:app --bind 127.0.0.1:8001 --workers 2 --timeout 300 --access-logfile - --error-logfile - --capture-output --log-level info',
      interpreter: 'none',
      env: {
        PORT: 8001,
        CORS_ORIGINS:
          process.env.CORS_ORIGINS ||
          'http://84.247.191.38,http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:4200,http://localhost:4200',
      },
    },
    {
      name: 'documentacion-worker',
      cwd: './backend',
      script: './.venv/bin/python',
      args: 'worker.py',
      interpreter: 'none',
      env: {
        WORKER_POLL_INTERVAL_SECONDS: process.env.WORKER_POLL_INTERVAL_SECONDS || 5,
        WORKER_BATCH_SIZE: process.env.WORKER_BATCH_SIZE || 5,
      },
    },
  ],
};
