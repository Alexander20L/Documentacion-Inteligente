const http = require('http');
const fs = require('fs');
const path = require('path');

const port = Number(process.env.PORT || 3000);

const candidates = [
  path.join(__dirname, 'dist', 'angular-app', 'browser'),
  path.join(__dirname, 'dist', 'angular-app'),
  path.join(__dirname, 'dist'),
  path.join(__dirname, '..', 'dist', 'angular-app', 'browser'),
  path.join(__dirname, '..', 'dist', 'angular-app'),
  path.join(__dirname, '..', 'dist'),
];

const rootDir = candidates.find((candidate) => fs.existsSync(candidate));

if (!rootDir) {
  console.error('No se encontró la carpeta de build de Angular. Ejecuta npm run build primero.');
  process.exit(1);
}

const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.ico': 'image/x-icon',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

function serveFile(res, filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const contentType = mimeTypes[ext] || 'application/octet-stream';

  fs.readFile(filePath, (error, data) => {
    if (error) {
      res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Error leyendo el archivo');
      return;
    }

    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
}

http
  .createServer((req, res) => {
    const requestUrl = new URL(req.url, `http://${req.headers.host}`);
    let filePath = path.join(rootDir, decodeURIComponent(requestUrl.pathname));

    if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
      filePath = path.join(filePath, 'index.html');
    }

    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      serveFile(res, filePath);
      return;
    }

    const indexPath = path.join(rootDir, 'index.html');
    if (fs.existsSync(indexPath)) {
      serveFile(res, indexPath);
      return;
    }

    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('No se encontró index.html');
  })
  .listen(port, () => {
    console.log(`Frontend servido en http://0.0.0.0:${port}`);
  });