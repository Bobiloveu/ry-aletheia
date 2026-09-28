export function createEraseFrameMask({
  capture,
  show,
  hide,
  requestFrame = requestAnimationFrame,
}) {
  let revealScheduled = false;

  return {
    cover() {
      capture();
      show();
    },
    revealAfterPaint() {
      if (revealScheduled) return;
      revealScheduled = true;
      // A rAF callback runs before a paint.  Waiting twice therefore keeps the
      // captured erase result on screen while the replacement canvas has a
      // full frame to become visible underneath it.
      requestFrame(() => {
        requestFrame(() => {
          revealScheduled = false;
          hide();
        });
      });
    },
  };
}
