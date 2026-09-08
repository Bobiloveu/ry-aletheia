import { RequestError, requestJson } from "../platform/http.js";

export async function requestWorkbenchJson(path, payload, keepalive = false, dependencies = {}) {
  const options = {
    method: payload === undefined ? "GET" : "POST",
    headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    keepalive,
  };
  try {
    return await requestJson(path, options, dependencies);
  } catch (error) {
    if (error instanceof RequestError && error.payload?.status && typeof error.payload.status === "object") {
      error.vehicleState = error.payload.status;
    }
    throw error;
  }
}
