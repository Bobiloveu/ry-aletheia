export class RequestError extends Error {
  constructor(message, { status, payload, url }) {
    super(message);
    this.name = "RequestError";
    this.status = status;
    this.payload = payload;
    this.url = url;
  }
}

export async function requestJson(url, options = {}, { fetchImpl = globalThis.fetch } = {}) {
  const response = await fetchImpl(url, { cache: "no-store", ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new RequestError(payload.error || "请求失败", {
      status: response.status,
      payload,
      url,
    });
  }
  return payload;
}
