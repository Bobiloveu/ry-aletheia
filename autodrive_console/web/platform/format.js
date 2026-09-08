export function formatFileSize(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}

export function formatUnixSeconds(value, locale = "zh-CN") {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "未知时间";
  const time = new Date(seconds * 1000);
  return Number.isNaN(time.getTime())
    ? "未知时间"
    : time.toLocaleString(locale, { hour12: false });
}
