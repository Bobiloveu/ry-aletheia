import { RequestError, requestJson } from "./http.js";

export async function requestVehicleControl(path, payload, keepalive = false, dependencies = {}) {
  const {
    errorMessage = (status) => `请求失败（${status}）`,
    ...requestDependencies
  } = dependencies;
  try {
    return await requestJson(path, {
      method: payload === undefined ? "GET" : "POST",
      headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      keepalive,
    }, { ...requestDependencies, errorMessage });
  } catch (error) {
    if (error instanceof RequestError && error.payload?.status && typeof error.payload.status === "object") error.vehicleState = error.payload.status;
    throw error;
  }
}
