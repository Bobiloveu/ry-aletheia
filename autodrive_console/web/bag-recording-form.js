export function buildBagRecordingPayload({ enabled, attemptIndex, topics }) {
  if (!enabled) return null;
  const round = Number(attemptIndex);
  const selected = Array.isArray(topics) ? topics.filter((topic) => typeof topic === 'string' && topic.startsWith('/')) : [];
  if (!Number.isInteger(round) || round < 1 || !selected.length || new Set(selected).size !== selected.length) return null;
  return { attemptIndex: round, topics: selected };
}

export function bagAuditLabel(audit) {
  const status = audit?.status;
  return status === 'passed' ? '审查通过' : status === 'warning' ? '审查警告' : status === 'failed' ? '审查失败' : '未审查';
}
