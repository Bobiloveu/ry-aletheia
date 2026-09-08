export function mapPointToCanvas(point, map, view) {
  return {
    x: view.x + (point.x - map.origin[0]) * view.scale,
    y: view.y + (map.height * map.resolution_m - (point.y - map.origin[1])) * view.scale,
  };
}

export function canvasPointToMap(point, map, view) {
  return {
    x: map.origin[0] + (point.x - view.x) / view.scale,
    y: map.origin[1] + (map.height * map.resolution_m - (point.y - view.y) / view.scale),
  };
}

export function isPointOnMap(point, map) {
  return (
    point.x >= map.origin[0] &&
    point.x <= map.origin[0] + map.width * map.resolution_m &&
    point.y >= map.origin[1] &&
    point.y <= map.origin[1] + map.height * map.resolution_m
  );
}

export function componentDimensions(component, scale) {
  return {
    width: Number(component.attributes?.width_m || 0.8) * scale,
    height: Number(component.attributes?.height_m || 0.8) * scale,
  };
}

export function componentLocalPoint(component, canvasPoint, map, view) {
  const center = mapPointToCanvas(component, map, view);
  const dx = canvasPoint.x - center.x;
  const dy = canvasPoint.y - center.y;
  const yaw = Number(component.yaw || 0);
  return {
    x: Math.cos(yaw) * dx - Math.sin(yaw) * dy,
    y: Math.sin(yaw) * dx + Math.cos(yaw) * dy,
  };
}

export function isComponentHit(component, canvasPoint, map, view) {
  const point = componentLocalPoint(component, canvasPoint, map, view);
  const { width, height } = componentDimensions(component, view.scale);
  return Math.abs(point.x) <= width / 2 && Math.abs(point.y) <= height / 2;
}

export function isResizeHandleHit(component, canvasPoint, map, view) {
  const point = componentLocalPoint(component, canvasPoint, map, view);
  const { width, height } = componentDimensions(component, view.scale);
  return Math.hypot(point.x - width / 2 - 9, point.y - height / 2 - 9) <= 16;
}

export function isRotateHandleHit(component, canvasPoint, map, view) {
  const point = componentLocalPoint(component, canvasPoint, map, view);
  const { width, height } = componentDimensions(component, view.scale);
  return Math.hypot(point.x - width / 2 - 29, point.y - height / 2 - 9) <= 13;
}

export function zoomAt(view, canvasPoint, deltaY) {
  const old = view.scale;
  const scale = Math.max(5, Math.min(500, old * (deltaY < 0 ? 1.12 : 0.89)));
  return {
    scale,
    x: canvasPoint.x - ((canvasPoint.x - view.x) * scale) / old,
    y: canvasPoint.y - ((canvasPoint.y - view.y) * scale) / old,
  };
}
