export class RequestError extends Error {
  constructor(message, { status, payload, url }) {
    super(message);
    this.name = "RequestError";
    this.status = status;
    this.payload = payload;
    this.url = url;
  }
}

export async function requestJson(url, options = {}, { fetchImpl = globalThis.fetch, errorMessage = "请求失败" } = {}) {
  const response = await fetchImpl(url, { cache: "no-store", ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fallback = typeof errorMessage === "function" ? errorMessage(response.status) : errorMessage;
    throw new RequestError(payload.error || fallback, {
      status: response.status,
      payload,
      url,
    });
  }
  return payload;
}
