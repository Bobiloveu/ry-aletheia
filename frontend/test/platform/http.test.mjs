import assert from "node:assert/strict";
import test from "node:test";

import { RequestError, requestJson } from "../../../autodrive_console/web/platform/http.js";

function response({ ok = true, status = 200, body = {} } = {}) {
  return { ok, status, json: async () => body };
}

test("requestJson applies no-store cache policy and returns JSON", async () => {
  let receivedUrl;
  let receivedOptions;
  const payload = await requestJson(
    "/api/example",
    { method: "POST", headers: { "X-Trace": "trace-1" } },
    {
      fetchImpl: async (url, options) => {
        receivedUrl = url;
        receivedOptions = options;
        return response({ body: { ready: true } });
      },
    },
  );

  assert.deepEqual(payload, { ready: true });
  assert.equal(receivedUrl, "/api/example");
  assert.equal(receivedOptions.cache, "no-store");
  assert.equal(receivedOptions.method, "POST");
  assert.equal(receivedOptions.headers["X-Trace"], "trace-1");
});

test("requestJson converts an HTTP JSON error into RequestError", async () => {
  await assert.rejects(
    () => requestJson("/api/example", {}, {
      fetchImpl: async () => response({ ok: false, status: 409, body: { error: "项目冲突" } }),
    }),
    (error) => {
      assert.ok(error instanceof RequestError);
      assert.equal(error.message, "项目冲突");
      assert.equal(error.status, 409);
      assert.equal(error.url, "/api/example");
      assert.deepEqual(error.payload, { error: "项目冲突" });
      return true;
    },
  );
});

test("requestJson keeps the generic error message when an error body is not JSON", async () => {
  await assert.rejects(
    () => requestJson("/api/example", {}, {
      fetchImpl: async () => ({ ok: false, status: 502, json: async () => { throw new SyntaxError("bad json"); } }),
    }),
    (error) => error instanceof RequestError && error.message === "请求失败",
  );
});

test("requestJson allows a page to preserve its own fallback error copy", async () => {
  await assert.rejects(
    () => requestJson("/api/example", {}, {
      errorMessage: "日志读取失败",
      fetchImpl: async () => response({ ok: false, status: 502, body: {} }),
    }),
    (error) => error instanceof RequestError && error.message === "日志读取失败",
  );
});

test("requestJson lets a page retain an HTTP-status-aware fallback error", async () => {
  await assert.rejects(
    () => requestJson("/api/example", {}, {
      errorMessage: (status) => `请求失败（HTTP ${status}）`,
      fetchImpl: async () => response({ ok: false, status: 502, body: {} }),
    }),
    (error) => error instanceof RequestError && error.message === "请求失败（HTTP 502）",
  );
});

test("requestJson does not hide a transport error", async () => {
  const disconnected = new TypeError("Failed to fetch");
  await assert.rejects(
    () => requestJson("/api/example", {}, { fetchImpl: async () => { throw disconnected; } }),
    (error) => error === disconnected,
  );
});
