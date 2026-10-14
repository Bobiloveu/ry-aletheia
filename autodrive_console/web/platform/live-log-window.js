function cloneLog(log) {
  return { ...log };
}

export function liveLogWindowLayout(logs, focusedId = null) {
  const knownFocusedId = logs.some((log) => log.id === focusedId && !log.minimized) ? focusedId : null;
  return {
    focusedId: knownFocusedId,
    visibleIds: logs.filter((log) => !log.minimized).map((log) => log.id),
    minimizedIds: logs.filter((log) => log.minimized).map((log) => log.id),
  };
}

export function applyLiveLogWindowAction(logs, focusedId = null, action) {
  const nextLogs = logs.map(cloneLog);
  const target = nextLogs.find((log) => log.id === action?.id);
  if (!target) return { logs: nextLogs, focusedId: liveLogWindowLayout(nextLogs, focusedId).focusedId };

  if (action.type === "minimize") target.minimized = true;
  if (action.type === "restore") target.minimized = false;
  const nextFocusedId = action.type === "maximize"
    ? (target.minimized ? null : target.id)
    : action.type === "restore-size"
      ? null
    : focusedId === target.id && (action.type === "minimize" || action.type === "close")
      ? null
      : focusedId;
  return { logs: nextLogs, focusedId: liveLogWindowLayout(nextLogs, nextFocusedId).focusedId };
}
