import { strict as assert } from "node:assert";
import test from "node:test";

import { requestWorkbenchJson } from "../../../autodrive_console/web/mapping-workbench/api.js";

test("workbench requests retain JSON post payloads and keepalive", async () => {
  let received;
  const payload = await requestWorkbenchJson(
    "/api/vehicle-control/stop",
    { session_id: "session-1" },
    true,
    {
      fetchImpl: async (_url, options) => {
        received = options;
        return new Response(JSON.stringify({ actual_source: "navigation" }), { status: 200 });
      },
    },
  );
  assert.equal(payload.actual_source, "navigation");
  assert.equal(received.method, "POST");
  assert.equal(received.keepalive, true);
  assert.equal(received.body, '{"session_id":"session-1"}');
});

test("workbench errors preserve server vehicle state separately from HTTP status", async () => {
  await assert.rejects(
    () => requestWorkbenchJson("/api/vehicle-control/enter", {}, false, {
      fetchImpl: async () => new Response(
        JSON.stringify({ error: "控制源未就绪", status: { actual_source: "miniapp", manual_ready: true } }),
        { status: 409 },
      ),
    }),
    (error) => error.status === 409 && error.vehicleState.actual_source === "miniapp",
  );
});
