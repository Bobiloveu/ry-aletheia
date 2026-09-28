/**
 * Coalesce visual mutations made by pointer, wheel, and resize events.
 * Persisting a mutation remains the caller's responsibility; this only bounds
 * canvas paint work to the browser refresh cadence.
 */
export function createCanvasDrawScheduler(draw, requestFrame = requestAnimationFrame) {
  let frame = null;
  return () => {
    if (frame !== null) return;
    frame = requestFrame(() => {
      frame = null;
      draw();
    });
  };
}
