import { RequestError, requestJson } from "./http.js";

export async function requestVehicleControl(path, payload, keepalive = false, dependencies = {}) {
  const {
    errorMessage = (status) => `请求失败（${status}）`,
    timeoutMs = 2000,
    ...requestDependencies
  } = dependencies;
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([requestJson(path, {
      method: payload === undefined ? "GET" : "POST",
      headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      keepalive,
      signal: controller.signal,
    }, { ...requestDependencies, errorMessage }), new Promise((_, reject) => {
      timer = globalThis.setTimeout(() => {
        reject(new Error("控制请求超时，请检查连接后重新操作"));
        controller.abort();
      }, timeoutMs);
    })]);
  } catch (error) {
    if (error instanceof RequestError && error.payload?.status && typeof error.payload.status === "object") error.vehicleState = error.payload.status;
    if (error instanceof RequestError && error.status === 409 && error.payload?.code === "session_invalid") error.sessionInvalid = true;
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
  }
}
