import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

import { createServer } from "vite";

const listen = (server) => new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(0, "127.0.0.1", () => {
    server.off("error", reject);
    resolve(server.address());
  });
});

const close = (server) => new Promise((resolve, reject) => {
  server.close((error) => (error ? reject(error) : resolve()));
});

test("Vite preview preserves legacy pages, split stylesheets, and the brand asset", async (t) => {
  const expectedAssets = new Map([
    ["/robot-logs.html", { type: "text/html", body: "robot-log-page" }],
    ["/robot_logs.css", { type: "text/css", body: ".robot-log { color: green; }" }],
    ["/deployment/tools.css", { type: "text/css", body: ".tool-icon { fill: none; }" }],
    ["/aletheia.svg", { type: "image/svg+xml", body: "<svg />" }],
  ]);
  const backend = http.createServer((request, response) => {
    const asset = expectedAssets.get(request.url);
    if (!asset) {
      response.writeHead(404);
      response.end("not found");
      return;
    }
    response.writeHead(200, { "Content-Type": asset.type });
    response.end(asset.body);
  });
  const backendAddress = await listen(backend);
  const backendOrigin = `http://127.0.0.1:${backendAddress.port}`;
  const previousOrigin = process.env.RY_ALETHEIA_LEGACY_ORIGIN;
  process.env.RY_ALETHEIA_LEGACY_ORIGIN = backendOrigin;

  let vite;
  try {
    const { default: config } = await import(`../vite.config.js?preview-proxy=${Date.now()}`);
    vite = await createServer({
      ...config,
      configFile: false,
      // `npm run dev` explicitly uses `--base /`; mirror the real preview
      // process instead of the `/vue/` production-build base.
      base: "/",
      logLevel: "error",
      server: {
        ...config.server,
        host: "127.0.0.1",
        port: 0,
        strictPort: false,
        watch: null,
      },
    });
    await vite.listen();
    const viteAddress = vite.httpServer.address();

    const dashboard = await fetch(`http://127.0.0.1:${viteAddress.port}/`);
    assert.equal(dashboard.status, 200, "preview root should load successfully");
    assert.match(
      await dashboard.text(),
      /<title>任务指挥台 · RY Aletheia<\/title>/,
      "preview root should retain the production task-dashboard entry",
    );

    for (const [path, expected] of expectedAssets) {
      const response = await fetch(`http://127.0.0.1:${viteAddress.port}${path}`);
      assert.equal(response.status, 200, `${path} should be served by the legacy backend`);
      assert.equal(response.headers.get("content-type")?.split(";", 1)[0], expected.type, `${path} MIME type`);
      assert.equal(await response.text(), expected.body, `${path} response body`);
    }
  } finally {
    if (vite) {
      vite.httpServer.closeAllConnections();
      await vite.close();
    }
    if (previousOrigin === undefined) delete process.env.RY_ALETHEIA_LEGACY_ORIGIN;
    else process.env.RY_ALETHEIA_LEGACY_ORIGIN = previousOrigin;
    backend.closeAllConnections();
    await close(backend);
  }
});
