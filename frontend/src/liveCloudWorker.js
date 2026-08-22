let canvas;
let context;
let map;

self.onmessage = ({ data }) => {
  if (data.type === 'init') {
    canvas = data.canvas || new OffscreenCanvas(1, 1);
    context = canvas.getContext('2d', { alpha: true, desynchronized: true });
    self.postMessage({ type: 'ready' });
    return;
  }
  if (data.type === 'map') {
    map = data; canvas.width = map.width; canvas.height = map.height;
    // 即使新旧地图像素尺寸相同，也必须清空旧图点云；随后只接受相同
    // generation 的扫描，防止异步 Worker 完成旧帧造成切图闪现。
    context.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  if (data.type !== 'points' || !(data.points instanceof Float32Array)) return;
  if (!map || data.generation !== map.generation) { self.postMessage({ type: 'frame-skipped' }); return; }
  context.clearRect(0, 0, canvas.width, canvas.height);
  // 只绘制最新扫描，所有点使用固定不透明色。既避免历史扫描造成视觉拖影，
  // 也取消 alpha 混合、历史数组和每帧透明度计算。
  context.fillStyle = 'rgb(128,88,255)';
  for (let index = 0; index < data.points.length; index += 2) {
    const x = (data.points[index] - map.origin.x) / map.resolution;
    const y = map.height - (data.points[index + 1] - map.origin.y) / map.resolution;
    if (x >= 0 && x < map.width && y >= 0 && y < map.height) context.fillRect(x - .35, y - .35, .7, .7);
  }
  // transferControlToOffscreen 模式下 Canvas 已经是页面可见图层，直接提交，
  // 不再创建/复制 ImageBitmap 到主线程。
  self.postMessage({ type: 'rendered' });
};
