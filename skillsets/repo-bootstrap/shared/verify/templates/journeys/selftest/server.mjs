// Tiny app for exercising journey.fixture.ts: / fetches /api/data; /boom fetches /api/boom (500);
// /third loads a script from a third-party origin. Usage: node server.mjs <port>
import http from 'node:http';
const port = Number(process.argv[2] || 4317);
const page = (body) => `<!doctype html><html><body>${body}</body></html>`;
http
  .createServer((req, res) => {
    const send = (code, type, body) => { res.writeHead(code, { 'content-type': type }); res.end(body); };
    if (req.url === '/api/data') return send(200, 'application/json', '{"items":["real"]}');
    if (req.url === '/api/boom') return send(500, 'application/json', '{"error":"boom"}');
    if (req.url === '/') return send(200, 'text/html', page(`<h1>Home</h1><ul id="l"></ul><script>
      fetch('/api/data').then(r => r.json()).then(d => { for (const i of d.items) { const li = document.createElement('li'); li.textContent = i; document.getElementById('l').append(li); } });
    </script>`));
    if (req.url === '/boom') return send(200, 'text/html', page(`<h1>Boom</h1><script>fetch('/api/boom')</script>`));
    if (req.url === '/third') return send(200, 'text/html', page(`<h1>Third</h1><script src="https://analytics.example.invalid/a.js"></script>`));
    return send(404, 'text/plain', 'not found');
  })
  .listen(port, '127.0.0.1');
