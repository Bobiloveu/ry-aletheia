const BEIJING_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function mapOrigin(map) {
  if (Array.isArray(map?.origin)) return [Number(map.origin[0]) || 0, Number(map.origin[1]) || 0];
  return [Number(map?.origin_x) || 0, Number(map?.origin_y) || 0];
}

export function mapPointToImage(point, map, evidenceHeight) {
  const resolution = Number(map?.resolution);
  const width = Number(map?.width);
  const height = Number(map?.height);
  if (![resolution, width, height, Number(point?.x), Number(point?.y)].every(Number.isFinite) || resolution <= 0) return null;
  const [originX, originY] = mapOrigin(map);
  return {
    x: (Number(point.x) - originX) / resolution,
    y: Number(evidenceHeight) + height - (Number(point.y) - originY) / resolution,
  };
}

export function mapPointToScreen(point, map, layout) {
  const imagePoint = mapPointToImage(point, map, layout?.evidenceHeight);
  const scale = Number(layout?.scale);
  const imageWidth = Number(layout?.imageWidth);
  const imageHeight = Number(layout?.imageHeight);
  const canvasWidth = Number(layout?.canvasWidth);
  const canvasHeight = Number(layout?.canvasHeight);
  const offsetX = Number(layout?.offsetX) || 0;
  const offsetY = Number(layout?.offsetY) || 0;
  if (!imagePoint || ![scale, imageWidth, imageHeight, canvasWidth, canvasHeight].every(Number.isFinite) || scale <= 0) return null;
  return {
    x: canvasWidth / 2 + offsetX + (imagePoint.x - imageWidth / 2) * scale,
    y: canvasHeight / 2 + offsetY + (imagePoint.y - imageHeight / 2) * scale,
  };
}

export function findNearestTrajectoryPoint(points, map, layout, pointer, maxDistancePx = Infinity) {
  let nearest = null;
  for (const point of Array.isArray(points) ? points : []) {
    const screen = mapPointToScreen(point, map, layout);
    if (!screen) continue;
    const distancePx = Math.hypot(screen.x - Number(pointer?.x), screen.y - Number(pointer?.y));
    if (distancePx <= maxDistancePx && (!nearest || distancePx < nearest.distancePx)) nearest = { point, screen, distancePx };
  }
  return nearest;
}

/**
 * Resolve a pointer to a trajectory sample while keeping horizontal movement
 * forgiving. The returned screen point is the magnetic anchor used by the
 * report overlay; the actual distance is preserved for the diagnostic value.
 */
export function findMagneticTrajectoryPoint(points, map, layout, pointer, options = {}) {
  const verticalWeight = Number.isFinite(Number(options.verticalWeight)) ? Number(options.verticalWeight) : 0.42;
  const maxDistancePx = Number.isFinite(Number(options.maxDistancePx)) ? Number(options.maxDistancePx) : Infinity;
  let nearest = null;
  for (const point of Array.isArray(points) ? points : []) {
    const screen = mapPointToScreen(point, map, layout);
    if (!screen) continue;
    const dx = screen.x - Number(pointer?.x);
    const dy = screen.y - Number(pointer?.y);
    const magneticDistancePx = Math.hypot(dx, dy * verticalWeight);
    if (magneticDistancePx <= maxDistancePx && (!nearest || magneticDistancePx < nearest.magneticDistancePx)) {
      nearest = { point, screen, distancePx: Math.hypot(dx, dy), magneticDistancePx };
    }
  }
  return nearest;
}

export function interpolateCounterValue(from, to, progress) {
  const start = Number(from);
  const end = Number(to);
  const amount = Math.max(0, Math.min(1, Number(progress)));
  if (![start, end, amount].every(Number.isFinite)) return end;
  return start + (end - start) * amount;
}

export function formatBeijingTime(timestampNs) {
  const milliseconds = Number(timestampNs) / 1_000_000;
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "时间未知";
  const parts = Object.fromEntries(BEIJING_TIME_FORMATTER.formatToParts(new Date(milliseconds)).map(({ type, value }) => [type, value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}
