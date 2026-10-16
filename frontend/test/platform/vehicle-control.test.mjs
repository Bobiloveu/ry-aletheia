import assert from "node:assert/strict";
import test from "node:test";

import { RequestError } from "../../../autodrive_console/web/platform/http.js";
import { requestVehicleControl } from "../../../autodrive_console/web/platform/vehicle-control.js";

function response({ ok = true, status = 200, body = {} } = {}) {
  return { ok, status, json: async () => body };
}

test("requestVehicleControl preserves GET and no-store request semantics", async () => {
  let receivedOptions;

  const payload = await requestVehicleControl("/api/vehicle-control", undefined, false, {
    fetchImpl: async (_url, options) => {
      receivedOptions = options;
      return response({ body: { actual_source: "navigation" } });
    },
  });

  assert.deepEqual(payload, { actual_source: "navigation" });
  assert.equal(receivedOptions.method, "GET");
  assert.equal(receivedOptions.cache, "no-store");
  assert.equal(receivedOptions.body, undefined);
});

test("requestVehicleControl exposes a rejected vehicle state without masking HTTP status", async () => {
  const vehicleState = {
    actual_source: "miniapp",
    display_mode: "手动控制",
    emergency_stop: { state: "normal" },
  };

  await assert.rejects(
    () => requestVehicleControl("/api/vehicle-control/enter", {}, false, {
      fetchImpl: async () => response({
        ok: false,
        status: 409,
        body: { error: "当前控制会话不可用", status: vehicleState },
      }),
    }),
    (error) => {
      assert.ok(error instanceof RequestError);
      assert.equal(error.status, 409);
      assert.equal(error.message, "当前控制会话不可用");
      assert.deepEqual(error.vehicleState, vehicleState);
      return true;
    },
  );
});

test("requestVehicleControl does not invent a vehicle state for ordinary API errors", async () => {
  await assert.rejects(
    () => requestVehicleControl("/api/vehicle-control/heartbeat", { session_id: "session-1" }, false, {
      fetchImpl: async () => response({ ok: false, status: 503, body: { error: "车辆控制节点不可用" } }),
    }),
    (error) => error instanceof RequestError && error.status === 503 && error.vehicleState === undefined,
  );
});

test("requestVehicleControl preserves the legacy HTTP-status fallback copy", async () => {
  await assert.rejects(
    () => requestVehicleControl("/api/vehicle-control/command", {}, false, {
      fetchImpl: async () => response({ ok: false, status: 503, body: {} }),
    }),
    (error) => error instanceof RequestError && error.message === "请求失败（503）",
  );
});

test('control request deadline aborts even a transport that never resolves', async () => {
  let signal;
  await assert.rejects(requestVehicleControl('/api/vehicle-control/vector', {session_id:'a'}, false, {
    timeoutMs: 10, fetchImpl: async (_url, options) => {
      signal=options.signal;
      return new Promise(()=>{});
    },
  }), /超时/);
  assert.equal(signal.aborted,true);
});

test('control deadline also covers a stalled JSON response body', async () => {
  let signal;
  await assert.rejects(requestVehicleControl('/api/vehicle-control', undefined, false, {
    timeoutMs: 10, fetchImpl: async (_url, options) => {
      signal=options.signal;
      return {ok:true,status:200,json:()=>new Promise(()=>{})};
    },
  }), /超时/);
  assert.equal(signal.aborted,true);
});

test('explicit session invalidation survives aggregate status with other active sessions', async () => {
  await assert.rejects(requestVehicleControl('/api/vehicle-control/heartbeat', {session_id:'expired'}, false, {
    fetchImpl: async () => response({ok:false,status:409,body:{
      error:'会话已失效',code:'session_invalid',status:{session:{present:true,state:'active'}},
    }}),
  }), error => error.sessionInvalid===true && error.vehicleState.session.present===true);
});
