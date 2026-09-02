

const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = 8000;
const DASHBOARD_FILE = path.join(__dirname, "dashboard", "index.html");

const server = http.createServer((req, res) => {
  fs.readFile(DASHBOARD_FILE, (err, content) => {
    if (err) {
      res.writeHead(500);
      res.end("Could not load dashboard/index.html — check the file exists.");
      return;
    }
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(content);
  });
});

server.listen(PORT, () => {
  console.log(`LedgerLens dashboard running at http://localhost:${PORT}`);
});