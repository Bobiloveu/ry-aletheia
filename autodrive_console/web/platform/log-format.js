const ANSI_ESCAPE = /\u001B(?:\][^\u0007]*(?:\u0007|\u001B\\)|\[[0-?]*[ -/]*[@-~])/g;
const LOG_LEVEL = /\b(DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR|FATAL)\b/i;
const TIMESTAMP = /\b(?:20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?|1\d{9}(?:\.\d{1,9})?)\b/;

/** Remove terminal control sequences while leaving the human log message intact. */
export function sanitizeLogText(value) {
  return String(value ?? '').replace(ANSI_ESCAPE, '').replace(/\r/g, '').trimEnd();
}

/** Return the strongest semantic level visible in a single log line. */
export function classifyLogLevel(value) {
  const level = sanitizeLogText(value).match(LOG_LEVEL)?.[1]?.toUpperCase() || '';
  if (level === 'ERROR' || level === 'FATAL') return 'error';
  if (level === 'WARN' || level === 'WARNING') return 'warning';
  if (level === 'INFO') return 'info';
  if (level === 'DEBUG' || level === 'TRACE') return 'debug';
  return 'plain';
}

/** Split common Supervisor/ROS log fields for readable rendering, never mutation. */
export function splitLogLine(value) {
  const line = sanitizeLogText(value);
  const timestamp = line.match(TIMESTAMP)?.[0] || '';
  const levelMatch = line.match(LOG_LEVEL);
  const level = levelMatch?.[1]?.toUpperCase() || '';
  let message = line;
  if (timestamp) message = message.replace(timestamp, '');
  if (levelMatch) message = message.replace(levelMatch[0], '');
  message = message.replace(/^\s*[\[\](){}:|-]+\s*/, '').trim();
  return { timestamp, level, message: message || line, tone: classifyLogLevel(line) };
}
