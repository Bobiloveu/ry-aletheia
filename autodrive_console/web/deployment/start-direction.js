const OUTER_GAP_PX = 4;
const ARROW_LENGTH_PX = 20;
const ARROW_HEAD_LENGTH_PX = 8;
const ARROW_HEAD_HALF_WIDTH_PX = 5;

export function isDirectionalTaskAnchor(kind) {
  return kind === "start" || kind === "target";
}

export function startDirectionGeometry({ x, y, yaw = 0, radius }) {
  const forwardX = Math.cos(yaw);
  const forwardY = -Math.sin(yaw);
  const lineStart = {
    x: x + forwardX * (radius + OUTER_GAP_PX),
    y: y + forwardY * (radius + OUTER_GAP_PX),
  };
  const tip = {
    x: lineStart.x + forwardX * ARROW_LENGTH_PX,
    y: lineStart.y + forwardY * ARROW_LENGTH_PX,
  };
  const headBase = {
    x: tip.x - forwardX * ARROW_HEAD_LENGTH_PX,
    y: tip.y - forwardY * ARROW_HEAD_LENGTH_PX,
  };
  const leftWing = {
    x: headBase.x + forwardY * ARROW_HEAD_HALF_WIDTH_PX,
    y: headBase.y - forwardX * ARROW_HEAD_HALF_WIDTH_PX,
  };
  const rightWing = {
    x: headBase.x - forwardY * ARROW_HEAD_HALF_WIDTH_PX,
    y: headBase.y + forwardX * ARROW_HEAD_HALF_WIDTH_PX,
  };
  return { lineStart, tip, leftWing, rightWing };
}
