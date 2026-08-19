let canvas;
let context;
let map;
let frames = [];

self.onmessage = ({ data }) => {
  if (data.type === 'init') {
    canvas = new OffscreenCanvas(1, 1);
    context = canvas.getContext('2d', { alpha: true, desynchronized: true });
    self.postMessage({ type: 'ready' });
    return;
  }
  if (data.type === 'map') {
    map = data; canvas.width = map.width; canvas.height = map.height; frames = [];
    return;
  }
  if (data.type !== 'points' || !(data.points instanceof Float32Array)) return;
  if (!map) { self.postMessage({ type: 'frame-skipped' }); return; }
  const now = Number(data.receivedAt) || performance.now();
  frames.push({ receivedAt: now, points: data.points });
  frames = frames.filter((frame) => now - frame.receivedAt <= map.historyMs);
  context.clearRect(0, 0, canvas.width, canvas.height);
  for (const frame of frames) {
    const age = Math.max(0, 1 - (now - frame.receivedAt) / map.historyMs);
    context.fillStyle = `rgba(128,88,255,${0.16 + age * 0.64})`;
    for (let index = 0; index < frame.points.length; index += 2) {
      const x = (frame.points[index] - map.origin.x) / map.resolution;
      const y = map.height - (frame.points[index + 1] - map.origin.y) / map.resolution;
      if (x >= 0 && x < map.width && y >= 0 && y < map.height) context.fillRect(x - .35, y - .35, .7, .7);
    }
  }
  const bitmap = canvas.transferToImageBitmap();
  self.postMessage({ type: 'frame', width: map.width, height: map.height, bitmap }, [bitmap]);
};
