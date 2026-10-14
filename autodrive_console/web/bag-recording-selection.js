const STORAGE_KEY = "ry-aletheia:diagnostic-bag-recording-draft:v1";
const MANUAL_STORAGE_KEY = "ry-aletheia:manual-diagnostic-bag-recording-draft:v1";

function normalize(value) {
  if (!value || typeof value !== "object") return null;
  const attemptIndex = Number(value.attemptIndex);
  const topics = Array.isArray(value.topics)
    ? value.topics.filter((topic) => typeof topic === "string" && topic.startsWith("/"))
    : [];
  if (!Number.isInteger(attemptIndex) || attemptIndex < 1 || !topics.length || new Set(topics).size !== topics.length) return null;
  return { attemptIndex, topics };
}

export function loadBagRecordingDraft(storage = sessionStorage) {
  try {
    return normalize(JSON.parse(storage.getItem(STORAGE_KEY) || "null"));
  } catch (_) {
    return null;
  }
}

export function saveBagRecordingDraft(storage = sessionStorage, draft) {
  const normalized = normalize(draft);
  if (!normalized) throw new Error("请选择录制轮次和至少一个 Topic。");
  storage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  return normalized;
}

export function clearBagRecordingDraft(storage = sessionStorage) {
  storage.removeItem(STORAGE_KEY);
}

function normalizeManual(value) {
  if (!value || typeof value !== "object") return null;
  const topics = Array.isArray(value.topics)
    ? value.topics.filter((topic) => typeof topic === "string" && topic.startsWith("/"))
    : [];
  const durationMinutes = Number(value.durationMinutes);
  const label = typeof value.label === "string" ? value.label.trim().replace(/\s+/g, " ") : "";
  if (!topics.length || topics.length > 32 || new Set(topics).size !== topics.length) return null;
  if (![5, 10, 15, 20].includes(durationMinutes) || label.length > 80) return null;
  return { topics, durationMinutes, label };
}

export function loadManualBagRecordingDraft(storage = sessionStorage) {
  try {
    return normalizeManual(JSON.parse(storage.getItem(MANUAL_STORAGE_KEY) || "null"));
  } catch (_) {
    return null;
  }
}

export function saveManualBagRecordingDraft(storage = sessionStorage, draft) {
  const normalized = normalizeManual(draft);
  if (!normalized) throw new Error("请选择录制时长和至少一个 Topic。");
  storage.setItem(MANUAL_STORAGE_KEY, JSON.stringify(normalized));
  return normalized;
}
