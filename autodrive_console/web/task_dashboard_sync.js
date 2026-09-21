const activeRunStatuses = new Set([
  "queued",
  "preparing",
  "running",
  "awaiting_recovery",
  "recovering",
  "cancelling",
]);

export function taskDashboardRefreshDelay(run) {
  return activeRunStatuses.has(run?.status) ? 1000 : 3000;
}
