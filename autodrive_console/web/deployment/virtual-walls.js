import { mapPointToCanvas } from "./canvas-geometry.js";

const squaredDistance = (left, right) => {
  const x = left.x - right.x;
  const y = left.y - right.y;
  return x * x + y * y;
};

function pointToSegmentDistance(point, start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  if (!lengthSquared) return Math.sqrt(squaredDistance(point, start));
  const ratio = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared));
  return Math.hypot(point.x - (start.x + ratio * dx), point.y - (start.y + ratio * dy));
}

function wallPoints(wall) {
  return Array.isArray(wall.points) ? wall.points : [wall.start, wall.end];
}

export function polylineSegments(wall) {
  const points = wallPoints(wall);
  return points.slice(1).map((end, index) => ({
    start: points[index],
    end,
  }));
}

export function wallsForDisplay(walls, previewWall = null) {
  if (!previewWall?.id) return walls;
  return walls.map((wall) => wall.id === previewWall.id ? previewWall : wall);
}

export function wallHitTest(wall, map, view, point, tolerancePx = 8) {
  const points = wallPoints(wall).map((item) => mapPointToCanvas(item, map, view));
  const toleranceSquared = tolerancePx * tolerancePx;
  for (const [index, vertex] of points.entries()) {
    if (squaredDistance(point, vertex) <= toleranceSquared)
      return Array.isArray(wall.points)
        ? `vertex:${index}`
        : index === 0 ? "start" : "end";
  }
  for (const [index, start] of points.entries()) {
    const end = points[index + 1];
    if (end && pointToSegmentDistance(point, start, end) <= tolerancePx)
      return Array.isArray(wall.points) ? `segment:${index}` : "segment";
  }
  return null;
}

export function moveWallEndpoint(wall, endpoint, point) {
  if (endpoint !== "start" && endpoint !== "end") return wall;
  return { ...wall, [endpoint]: { x: point.x, y: point.y } };
}

export function moveWallVertex(wall, index, point) {
  if (!Array.isArray(wall.points) || index < 0 || index >= wall.points.length) return wall;
  return {
    ...wall,
    points: wall.points.map((vertex, vertexIndex) =>
      vertexIndex === index ? { x: point.x, y: point.y } : { ...vertex },
    ),
  };
}

export function translateWall(wall, delta) {
  if (Array.isArray(wall.points)) {
    return {
      ...wall,
      points: wall.points.map((point) => ({
        x: point.x + delta.x,
        y: point.y + delta.y,
      })),
    };
  }
  return {
    ...wall,
    start: { x: wall.start.x + delta.x, y: wall.start.y + delta.y },
    end: { x: wall.end.x + delta.x, y: wall.end.y + delta.y },
  };
}
