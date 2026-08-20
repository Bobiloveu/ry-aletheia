import { FoxgloveClient } from '@foxglove/ws-protocol';
import { parse } from '@foxglove/rosmsg';
import { MessageReader } from '@foxglove/rosmsg2-serialization';
import '../../autodrive_console/web/styles.css';
import '../../autodrive_console/web/refinement.css';
import '../../autodrive_console/web/page_views.css';
import './liveObservation.css';

// 只订阅二维观测必要的话题。TF 仅用于将雷达点云投影到地图坐标，不做三维场景渲染。
// /map 的历史样本在本车上只对 TRANSIENT_LOCAL 订阅可见。底图由轨迹记录器
// 安全缓存后通过 HTTP 提供；浏览器直连 Aletheia 私有 Bridge 获取实时数据。
// /map 必须进入白名单：它是 TRANSIENT_LOCAL 话题，浏览器仅在短订阅窗口内
// 接收一次当前栅格；遗漏它会导致 Bridge 已连接但地图永远无法开始加载。
const TOPICS = new Set(['/map', '/amcl_pose', '/aletheia/live_pose', '/livox/points', '/aletheia/live_points', '/tf', '/tf_static']);
// ros-humble-foxglove-bridge 3.x 采用 Foxglove SDK 的握手标识。@foxglove/ws-protocol
// 仍负责兼容的消息帧编解码，但其旧常量 foxglove.websocket.v1 不能通过 3.x Bridge。
const FOXGLOVE_BRIDGE_SUBPROTOCOL = 'foxglove.sdk.v1';
// 3000 点足以保留室内墙面和门洞的结构感；仍在前端限频解析，避免以原始全量
// 点云的频率占用浏览器主线程。
const POINT_LIMIT = 3000;
// 私有预处理节点已经在小车端限点、转换到 map 坐标并保持 depth=1，可按更高
// 刷新率消费；回退到原始点云时仍保持保守限速，避免浏览器主线程被抢占。
const PREPROCESSED_CLOUD_MIN_INTERVAL_MS = 100;
const RAW_CLOUD_MIN_INTERVAL_MS = 250;
// 实时观测只关心“现在”。页面短暂忙碌或网络抖动后，宁可跳过旧扫描也不能
// 按顺序补绘导致画面落后实车。两个队列均为单槽 latest-wins。
const CLOUD_PACKET_MAX_AGE_MS = 180;
const POSE_PACKET_MAX_AGE_MS = 120;
// 实测 /tf 可稳定高频到达。仅消费约 30 Hz 已足够让车体连续运动，同时避免把
// 数百 Hz 的 TF 批量解析和整图重绘带入浏览器主线程。
const TF_MIN_INTERVAL_MS = 33;
// 地图旋转、栅格缩放与高密度点云合成是最重的浏览器操作。数据接收可更快，
// 但画布只按可见效果需要合成，避免每一帧 TF 都触发整图重绘。
// 整幅地图、虚拟墙与点云采用同一 Canvas。持续 60 FPS 重绘会抢占浏览器主线程
// 并反而积压位姿；限制为 30 FPS 可保持可见连续性且为 ROS/WebSocket 留出余量。
const MAP_RENDER_INTERVAL_MS = 33;
// 雷达原始扫描约 10 Hz；保留极短的历史帧并淡化，能消除“整帧替换”导致的
// 点云闪断。所有历史都已在 map 坐标系，窗口很短，不会形成明显拖影。
const CLOUD_HISTORY_MS = 90;
// 地图源本身约为千级像素；限制到 CSS 像素级可避免在高 DPI 电脑上反复旋转
// 超采样的大画布，显著降低主视图卡顿，同时不压缩或修改原始地图数据。
// 图像是观测页中带宽和解码开销最大的内容。实时查看应优先展示最新状态，
// 而不是让浏览器逐帧补完历史画面；否则延迟会持续累积并明显落后于 RViz2。
// 压缩图像由浏览器异步解码，直接调度最新帧；原始图像需要逐像素转换，
// 因此保守限速以免抢占地图和点云的主线程时间。两者均只绘制最新帧。
const COMPRESSED_CAMERA_RENDER_INTERVAL_MS = 0;
const RAW_CAMERA_RENDER_INTERVAL_MS = 200;
// OccupancyGrid 通常为 transient-local；首次接收后立即取消订阅，定期用短订阅
// 探测 map_server 是否已经切图。避免持续传输大栅格占用无线带宽和浏览器主线程。
const MAP_PROBE_INTERVAL_MS = 5000;
const MAP_PROBE_TIMEOUT_MS = 1800;
// 点云和动态 TF 只在实时观测页打开且地图已就绪后订阅。此前短脉冲订阅会在
// Bridge 创建 ROS 订阅或 TF 尚未到达时错过样本，表现为点云冻结；改为持续订阅，
// 再在浏览器端限频解码最新帧，避免重复创建订阅和积压旧帧。
const STATIC_TF_WINDOW_MS = 1400;
const DEFAULT_VIEW_METERS = 16;
const MIN_PIXELS_PER_METER = 8;
const MAX_PIXELS_PER_METER = 420;
const INITIAL_OVERVIEW_MOVEMENT_M = 0.12;
// 实际定位会有厘米级位置与航向抖动。视角采用慢跟随而非逐帧硬锁定，
// 使驾驶观察稳定，同时保留明显转弯/位移的响应。
const FOLLOW_CENTER_ALPHA = 0.40;
const FOLLOW_CENTER_SNAP_DISTANCE_M = 1.5;
// 地图不需要随车体的小幅摆动连续旋转。仅当累计航向变化达到 90°，才切换
// 到新的驾驶朝向；车体仍实时移动，显著减少大幅栅格旋转造成的掉帧。
const MAP_REORIENT_THRESHOLD_RAD = Math.PI / 2;
// 平滑接近目标后必须停止补帧。否则静止小车持续发布的 TF 会不断延长动画窗口，
// 使页面在没有可见变化时仍维持高频重绘。
const FOLLOW_CENTER_SETTLE_DISTANCE_M = 0.008;
// 静止定位仍会有毫米级浮动。显示层使用 2.5 cm 滞回，累计位移超过阈值才更新，
// 不修改 ROS 原始位姿；缓慢真实移动会自然越过阈值而继续显示。
const VEHICLE_POSITION_DEADBAND_M = 0.025;
const VEHICLE_VELOCITY_DEADBAND_MPS = 0.05;
const $ = (id) => document.getElementById(id);
let client;
let cloudUpdatedAt = 0;
let tfUpdatedAt = 0;
let livePoseUpdatedAt = 0;
let vehicleUpdatedAt = 0;
let mapInfo;
let mapRaster;
let cloudRasterQueued = false;
let cloudWorker;
let cloudWorkerReady = false;
let cloudWorkerBusy = false;
let pendingCloudFrame;
let cloudWorkerFailed = false;
let cloudWorkerOwnsCanvas = false;
let pendingCloudPacket;
let cloudPacketQueued = false;
let pendingPosePacket;
let posePacketQueued = false;
let pose;
let tfVehiclePose;
let renderedVehiclePose;
let renderedVehicleAt = 0;
let cloud;
let cloudFrames = [];
let virtualWalls = [];
let wallStatus = '等待虚拟墙匹配';
let loadedWallMapId;
let loadedMapId;
const transforms = new Map();
// 不同车型/定位栈对底盘坐标系的命名可能不同。/amcl_pose 暂时不可用时，
// 直接从 TF 的 map -> base_* 链路绘制车体，不能因单一定位话题短暂缺帧而消失。
const VEHICLE_BASE_FRAMES = ['base_footprint', 'base_link', 'base_footprint_link'];
const cameraChannels = new Map();
const cameraSlots = { A: {}, B: {} };
let readers;
let subscriptions;
let mapChannel;
let mapProbeTimer;
let mapProbeTimeout;
let mapProbeSubscriptionId;
let mapFingerprint;
let resolvedWallFingerprint;
let tfChannel;
let staticTfChannel;
let livePoseChannel;
let cloudChannel;
let cloudTopic = '/livox/points';
let staticTfSubscriptionId;
let staticTfStopTimer;
let tfFallbackTimer;
const visualizationStreams = {
  tf: { channel: undefined, subscriptionId: undefined },
  livePose: { channel: undefined, subscriptionId: undefined },
  cloud: { channel: undefined, subscriptionId: undefined },
};
let drawQueued = false;
let drawDeferredTimer;
let drawAnimationFrame;
let lastMapDrawAt = 0;
let lastMapLayout;
let vehicleAnimationFrame;
let mapInteractionActive = false;
let mapInteractionTimer;
let cloudRasterPending = false;
let vehicleModel = { id: 'ry-standard', name: 'RY 标准小车', length_m: 1.0, width_m: 0.68 };
const mapView = { pixelsPerMeter: undefined, followVehicle: true, followOffset: { x: 0, y: 0 }, center: undefined };
let overviewUntilMovement = true;
let overviewPoseAnchor;
let lockedMapYaw;
const LAYOUT_KEY = 'ry-aletheia-live-workspace-v2';
const DEFAULT_LAYOUT = { mapRatio: 76, imageRatio: 50, cameraA: true, cameraB: true, cameraPriority: false };
let workspaceLayout;
let lastDiagnosticsAt = 0;

function setText(id, value) { $(id).textContent = value; }
function request(url, options = {}) {
  return fetch(url, { cache: 'no-store', ...options }).then(async (response) => {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `请求失败（HTTP ${response.status}）`);
    return body;
  });
}
function reportObservation(level, message) {
  const body = JSON.stringify({ level, message: String(message || '').slice(0, 800) });
  // 诊断日志是辅助功能：浏览器无法写入时不能反过来影响只读观测。
  fetch('/api/observation/client-log', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }).catch(() => {});
}
function normalizeFrame(value) { return String(value || '').replace(/^\/+|\/+$/g, ''); }
function yawOf(quaternion = {}) {
  const { x = 0, y = 0, z = 0, w = 1 } = quaternion;
  return Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
}
function compose(first, second) {
  // 先应用 first、再应用 second。
  const cosine = Math.cos(second.yaw); const sine = Math.sin(second.yaw);
  return { yaw: first.yaw + second.yaw, x: cosine * first.x - sine * first.y + second.x, y: sine * first.x + cosine * first.y + second.y };
}
function invert(transform) {
  const yaw = -transform.yaw; const cosine = Math.cos(yaw); const sine = Math.sin(yaw);
  return { yaw, x: -(cosine * transform.x - sine * transform.y), y: -(sine * transform.x + cosine * transform.y) };
}

function initializeTheme() {
  const key = 'ry-aletheia-theme';
  const apply = () => {
    const light = localStorage.getItem(key) === 'light';
    document.body.classList.toggle('theme-light', light);
    document.documentElement.style.colorScheme = light ? 'light' : 'dark';
  };
  document.querySelector('.mark')?.addEventListener('click', () => {
    localStorage.setItem(key, document.body.classList.contains('theme-light') ? 'dark' : 'light'); apply();
  });
  apply();
}
function isImageChannel(channel) {
  return channel.encoding === 'cdr' && ['sensor_msgs/msg/Image', 'sensor_msgs/msg/CompressedImage'].includes(channel.schemaName);
}
function isDepthTransport(channel) { return /\/compressedDepth$/i.test(String(channel.topic || '')); }
function isCompressedCamera(channel) { return channel.schemaName === 'sensor_msgs/msg/CompressedImage' && !isDepthTransport(channel); }
function isCameraCandidate(channel) { return isImageChannel(channel) && !isDepthTransport(channel); }
function setCameraState(slot, value) { setText(`cameraState${slot}`, value); }
function clearCamera(slot) {
  const canvas = $(`cameraCanvas${slot}`); const context = canvas.getContext('2d');
  context.fillStyle = '#02070d'; context.fillRect(0, 0, canvas.width, canvas.height);
}
function refreshCameraOptions() {
  const candidates = [...cameraChannels.values()].sort((left, right) => {
    const leftCompressed = isCompressedCamera(left) ? 0 : 1;
    const rightCompressed = isCompressedCamera(right) ? 0 : 1;
    return leftCompressed - rightCompressed || left.topic.localeCompare(right.topic);
  });
  for (const slot of ['A', 'B']) {
    const select = $(`cameraSelect${slot}`); const selected = cameraSlots[slot].channelId || '';
    select.replaceChildren(new Option('不订阅图像', ''));
    candidates.forEach((channel) => select.add(new Option(`${channel.topic} · ${isCompressedCamera(channel) ? '压缩图像（低延迟推荐）' : '原始图像（高带宽，可能增加延迟）'}`, String(channel.id))));
    select.value = String(selected);
    if (!select.value) { cameraSlots[slot].channelId = undefined; setCameraState(slot, candidates.length ? '请选择图像话题' : '未发现 sensor_msgs 图像话题'); }
  }
}
function selectCamera(slot, selectedId) {
  const state = cameraSlots[slot];
  if (state.subscriptionId !== undefined) { client?.unsubscribe(state.subscriptionId); subscriptions?.delete(state.subscriptionId); }
  state.subscriptionId = undefined; state.channelId = selectedId ? Number(selectedId) : undefined;
  state.pendingFrame = undefined; state.renderQueued = false; state.rendering = false; state.nextRenderAt = 0;
  clearCamera(slot);
  subscribeCamera(slot);
  activateVisualizationStreams();
}
function subscribeCamera(slot) {
  const state = cameraSlots[slot];
  if (state.subscriptionId !== undefined) { client?.unsubscribe(state.subscriptionId); subscriptions?.delete(state.subscriptionId); state.subscriptionId = undefined; }
  if (!state.channelId) { setCameraState(slot, '未订阅图像'); return; }
  const channel = cameraChannels.get(state.channelId);
  if (!channel || !client || !readers?.has(channel.id)) { setCameraState(slot, '图像话题暂不可用'); return; }
  state.subscriptionId = client.subscribe(channel.id); subscriptions.set(state.subscriptionId, { topic: channel.topic, channelId: channel.id, cameraSlot: slot });
  setCameraState(slot, isCompressedCamera(channel) ? `订阅中 · ${channel.topic}` : `订阅原始图像 · ${channel.topic}（高带宽）`);
}
function setupCameraSelectors() {
  for (const slot of ['A', 'B']) {
    clearCamera(slot);
    $(`cameraSelect${slot}`).addEventListener('change', (event) => selectCamera(slot, event.target.value));
  }
}
function validLayout(value) {
  if (!value || !Number.isFinite(value.mapRatio) || !Number.isFinite(value.imageRatio)) return undefined;
  return { mapRatio: Math.max(55, Math.min(88, value.mapRatio)), imageRatio: Math.max(25, Math.min(75, value.imageRatio)), cameraA: value.cameraA !== false, cameraB: value.cameraB !== false, cameraPriority: value.cameraPriority === true };
}
function loadWorkspaceLayout() {
  try { return validLayout(JSON.parse(localStorage.getItem(LAYOUT_KEY))) || structuredClone(DEFAULT_LAYOUT); } catch (_) { return structuredClone(DEFAULT_LAYOUT); }
}
function saveWorkspaceLayout() { localStorage.setItem(LAYOUT_KEY, JSON.stringify(workspaceLayout)); }
function applyWorkspaceLayout() {
  const workspace = $('viewerWorkspace'); const visible = [workspaceLayout.cameraA, workspaceLayout.cameraB].filter(Boolean).length;
  workspace.style.setProperty('--map-ratio', `${workspaceLayout.mapRatio}%`); workspace.style.setProperty('--image-ratio', `${workspaceLayout.imageRatio}%`);
  workspace.dataset.imageMode = visible === 0 ? 'none' : (visible === 1 ? (workspaceLayout.cameraA ? 'single-a' : 'single-b') : 'dual');
  document.querySelector('[data-widget="cameraA"]').hidden = !workspaceLayout.cameraA; document.querySelector('[data-widget="cameraB"]').hidden = !workspaceLayout.cameraB;
  $('showCameraA').checked = workspaceLayout.cameraA; $('showCameraB').checked = workspaceLayout.cameraB; $('cameraPriority').checked = workspaceLayout.cameraPriority; drawMap();
}
function setupWorkspace() {
  workspaceLayout = loadWorkspaceLayout(); applyWorkspaceLayout();
  const workspace = $('viewerWorkspace'); let operation;
  const finish = () => { if (!operation) return; $(operation).classList.remove('dragging'); operation = undefined; saveWorkspaceLayout(); };
  for (const splitter of ['verticalSplitter', 'horizontalSplitter']) $(splitter).addEventListener('pointerdown', (event) => { operation = splitter; $(splitter).classList.add('dragging'); event.preventDefault(); });
  window.addEventListener('pointermove', (event) => {
    if (!operation) return; const rect = workspace.getBoundingClientRect();
    if (operation === 'verticalSplitter') workspaceLayout.mapRatio = Math.max(55, Math.min(88, (event.clientX - rect.left) / rect.width * 100));
    else workspaceLayout.imageRatio = Math.max(25, Math.min(75, (event.clientY - rect.top) / rect.height * 100));
    applyWorkspaceLayout();
  });
  window.addEventListener('pointerup', finish); window.addEventListener('pointercancel', finish);
  $('toggleWorkspaceControls').addEventListener('click', () => { const body = $('workspaceControlsBody'); body.hidden = !body.hidden; });
  for (const slot of ['A', 'B']) {
    $(`showCamera${slot}`).addEventListener('change', (event) => {
      const key = `camera${slot}`; workspaceLayout[key] = event.target.checked;
      if (event.target.checked) subscribeCamera(slot);
      else {
        const state = cameraSlots[slot];
        if (state.subscriptionId !== undefined) { client?.unsubscribe(state.subscriptionId); subscriptions?.delete(state.subscriptionId); state.subscriptionId = undefined; }
        clearCamera(slot); setCameraState(slot, '窗口已隐藏，已停止订阅');
      }
      activateVisualizationStreams(); applyWorkspaceLayout(); saveWorkspaceLayout();
    });
  }
  $('cameraPriority').addEventListener('change', (event) => {
    workspaceLayout.cameraPriority = event.target.checked;
    activateVisualizationStreams(); saveWorkspaceLayout(); updateDiagnostics();
  });
  $('resetWorkspace').addEventListener('click', () => { workspaceLayout = structuredClone(DEFAULT_LAYOUT); applyWorkspaceLayout(); for (const slot of ['A', 'B']) subscribeCamera(slot); activateVisualizationStreams(); saveWorkspaceLayout(); });
}
function setupMapInteraction() {
  const canvas = $('mapCanvas');
  const wrap = canvas.parentElement;
  const resizeCanvas = () => {
    const wrap = canvas.parentElement; const rect = wrap?.getBoundingClientRect();
    if (!rect?.width || !rect?.height) return;
    // 交互 Canvas 不承担绘制，必须严格使用 CSS 像素；世界层也是 CSS 坐标。
    // 若这里混入 devicePixelRatio，滚轮锚点会与地图/车体层落在不同坐标系。
    const width = Math.max(1, Math.round(rect.width)); const height = Math.max(1, Math.round(rect.height));
    if (canvas.width === width && canvas.height === height) return;
    canvas.width = width; canvas.height = height;
    // 像素坐标系变化后让布局根据当前容器重算，避免窗口大小变化造成模糊或跳变。
    mapView.pixelsPerMeter = undefined;
    scheduleMapDraw();
  };
  new ResizeObserver(resizeCanvas).observe(canvas.parentElement);
  resizeCanvas();
  let pan;
  const setInteractionActive = (active) => {
    mapInteractionActive = active;
    if (mapInteractionTimer) { window.clearTimeout(mapInteractionTimer); mapInteractionTimer = undefined; }
    if (!active && cloudRasterPending) {
      cloudRasterPending = false;
      scheduleCloudRasterBuild();
    }
  };
  const deferInteractionEnd = () => {
    if (mapInteractionTimer) window.clearTimeout(mapInteractionTimer);
    mapInteractionTimer = window.setTimeout(() => setInteractionActive(false), 140);
  };
  const eventCanvasPoint = (event) => {
    const rect = canvas.getBoundingClientRect();
    return { x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height };
  };
  const worldAtCanvasPoint = (target, layout) => {
    const dx = target.x - canvas.width / 2; const dy = target.y - canvas.height / 2;
    const cosine = Math.cos(layout.rotation); const sine = Math.sin(layout.rotation);
    return {
      x: layout.center.x + (cosine * dx + sine * dy) / layout.pixelsPerMeter,
      y: layout.center.y - (-sine * dx + cosine * dy) / layout.pixelsPerMeter,
    };
  };
  const onWheel = (event) => {
    if (!mapInfo) return;
    event.preventDefault();
    event.stopPropagation();
    setInteractionActive(true);
    deferInteractionEnd();
    overviewUntilMovement = false;
    const before = currentMapLayout(); const cursor = eventCanvasPoint(event); const anchor = worldAtCanvasPoint(cursor, before);
    // 对鼠标滚轮和触控板使用相同的连续比例，而不是每一条事件只跳一个固定档位。
    // 这使放大/缩小响应立即且不会被浏览器的滚动节流吞掉。
    const factor = Math.exp(Math.max(-0.32, Math.min(0.32, -event.deltaY * 0.0022)));
    mapView.pixelsPerMeter = Math.max(MIN_PIXELS_PER_METER, Math.min(MAX_PIXELS_PER_METER, (mapView.pixelsPerMeter || canvas.width / DEFAULT_VIEW_METERS) * factor));
    // 光标下的世界坐标在缩放前后不变；保存相对车辆偏移后，车辆仍保持连续跟随。
    const dx = cursor.x - canvas.width / 2; const dy = cursor.y - canvas.height / 2;
    const cosine = Math.cos(before.rotation); const sine = Math.sin(before.rotation);
    const desiredCenter = {
      x: anchor.x - (cosine * dx + sine * dy) / mapView.pixelsPerMeter,
      y: anchor.y + (-sine * dx + cosine * dy) / mapView.pixelsPerMeter,
    };
    const vehicle = vehiclePoseInMap();
    if (vehicle?.position) {
      mapView.followVehicle = true;
      mapView.followOffset = { x: desiredCenter.x - vehicle.position.x, y: desiredCenter.y - vehicle.position.y };
    } else mapView.center = desiredCenter;
    scheduleMapDraw(true);
  };
  // 监听整个地图容器，避免覆盖图层或图例改变后吞掉滚轮事件。
  wrap.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('dblclick', () => {
    overviewUntilMovement = false;
    mapView.followVehicle = true; mapView.followOffset = { x: 0, y: 0 };
    const vehicle = vehiclePoseInMap();
    if (vehicle?.position) mapView.center = { x: vehicle.position.x, y: vehicle.position.y };
    scheduleMapDraw(true);
  });
  const finishPan = (event) => {
    if (!pan || (event && event.pointerId !== pan.pointerId)) return;
    if (canvas.hasPointerCapture(pan.pointerId)) canvas.releasePointerCapture(pan.pointerId);
    pan = undefined; canvas.classList.remove('is-panning');
  };
  canvas.addEventListener('pointerdown', (event) => {
    // 同时支持左键和中键拖拽；中键仍保留，左键避免操作者误以为地图不能拖动。
    if ((event.button !== 0 && event.button !== 1) || !mapInfo) return;
    event.preventDefault();
    setInteractionActive(true);
    pan = { pointerId: event.pointerId, point: eventCanvasPoint(event) };
    canvas.setPointerCapture(event.pointerId); canvas.classList.add('is-panning');
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!pan || event.pointerId !== pan.pointerId || !mapInfo) return;
    const next = eventCanvasPoint(event); const dx = next.x - pan.point.x; const dy = next.y - pan.point.y;
    pan.point = next;
    if (!dx && !dy) return;
    const layout = currentMapLayout(); const cosine = Math.cos(layout.rotation); const sine = Math.sin(layout.rotation);
    // 屏幕位移逆变换回地图坐标；拖动的是地图本身，因此中心向反方向平移。
    const localX = (cosine * dx + sine * dy) / layout.pixelsPerMeter;
    const localY = (-sine * dx + cosine * dy) / layout.pixelsPerMeter;
    mapView.center = { x: layout.center.x - localX, y: layout.center.y + localY };
    mapView.followVehicle = false; overviewUntilMovement = false;
    scheduleMapDraw(true);
  });
  canvas.addEventListener('pointerup', (event) => { finishPan(event); deferInteractionEnd(); });
  canvas.addEventListener('pointercancel', (event) => { finishPan(event); setInteractionActive(false); });
  canvas.addEventListener('lostpointercapture', () => { finishPan(); setInteractionActive(false); });
}
function drawRawImage(slot, message) {
  const width = Number(message.width); const height = Number(message.height); const encoding = String(message.encoding || '').toLowerCase(); const source = message.data;
  if (!width || !height || !source || !['rgb8', 'bgr8', 'rgba8', 'bgra8', 'mono8'].includes(encoding)) { setCameraState(slot, `暂不支持编码：${encoding || '未知'}`); return; }
  const channels = encoding === 'mono8' ? 1 : (encoding === 'rgb8' || encoding === 'bgr8' ? 3 : 4); const step = Number(message.step) || width * channels;
  if (source.byteLength < step * height) { setCameraState(slot, '图像数据不完整'); return; }
  const canvas = $(`cameraCanvas${slot}`); const context = canvas.getContext('2d'); const state = cameraSlots[slot];
  if (!state.scratch || state.scratch.width !== width || state.scratch.height !== height) {
    state.scratch = document.createElement('canvas'); state.scratch.width = width; state.scratch.height = height;
    state.imageData = state.scratch.getContext('2d').createImageData(width, height);
  }
  const image = state.imageData;
  for (let row = 0; row < height; row += 1) for (let column = 0; column < width; column += 1) {
    const from = row * step + column * channels; const to = (row * width + column) * 4;
    if (encoding === 'mono8') image.data[to] = image.data[to + 1] = image.data[to + 2] = source[from];
    else if (encoding === 'bgr8' || encoding === 'bgra8') { image.data[to] = source[from + 2]; image.data[to + 1] = source[from + 1]; image.data[to + 2] = source[from]; }
    else { image.data[to] = source[from]; image.data[to + 1] = source[from + 1]; image.data[to + 2] = source[from + 2]; }
    image.data[to + 3] = channels === 4 ? source[from + 3] : 255;
  }
  const scale = Math.min(canvas.width / width, canvas.height / height); const drawWidth = width * scale; const drawHeight = height * scale;
  state.scratch.getContext('2d').putImageData(image, 0, 0);
  context.fillStyle = '#02070d'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(state.scratch, (canvas.width - drawWidth) / 2, (canvas.height - drawHeight) / 2, drawWidth, drawHeight);
  setCameraState(slot, `${width} × ${height} · ${encoding}`);
}
async function drawCompressedImage(slot, message, sequence) {
  const bytes = message.data; if (!bytes?.byteLength) { setCameraState(slot, '压缩图像为空'); return; }
  const format = String(message.format || '').toLowerCase(); const mime = format.includes('png') ? 'image/png' : 'image/jpeg';
  try {
    const bitmap = await createImageBitmap(new Blob([bytes], { type: mime })); const state = cameraSlots[slot];
    // 解码期间如果已有更新帧到达，旧帧直接丢弃。此前旧帧仍会绘制，造成
    // 画面看起来稳定落后于 RViz2；这里确保浏览器只展示最新可解码画面。
    if (state.latestSequence !== sequence) { bitmap.close(); return; }
    const canvas = $(`cameraCanvas${slot}`); const context = canvas.getContext('2d'); const width = bitmap.width; const height = bitmap.height;
    const scale = Math.min(canvas.width / width, canvas.height / height); const drawWidth = width * scale; const drawHeight = height * scale;
    context.fillStyle = '#02070d'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(bitmap, (canvas.width - drawWidth) / 2, (canvas.height - drawHeight) / 2, drawWidth, drawHeight); bitmap.close();
    setCameraState(slot, `${message.format || 'compressed'} · ${width} × ${height}`);
  } catch (_) { setCameraState(slot, '压缩图像解码失败'); }
}
function queueCameraFrame(slot, channel, data) {
  if (!channel) { setCameraState(slot, '图像话题已移除'); return; }
  const state = cameraSlots[slot];
  // 不解析、也不复制已经过期的帧：新的帧会直接替换待渲染帧。
  state.latestSequence = (state.latestSequence || 0) + 1;
  state.pendingFrame = { channel, data, sequence: state.latestSequence };
  if (state.rendering || state.renderQueued) return;
  state.renderQueued = true;
  window.setTimeout(() => renderLatestCameraFrame(slot), Math.max(0, (state.nextRenderAt || 0) - performance.now()));
}
function renderLatestCameraFrame(slot) {
  const state = cameraSlots[slot]; state.renderQueued = false;
  if (state.rendering || !state.pendingFrame) return;
  const frame = state.pendingFrame; state.pendingFrame = undefined; state.rendering = true;
  try {
    const reader = readers?.get(frame.channel.id);
    if (!reader) throw new Error('图像类型定义不可用');
    const message = reader.readMessage(frame.data);
    const compressed = frame.channel.schemaName.endsWith('CompressedImage');
    const render = compressed ? drawCompressedImage(slot, message, frame.sequence) : drawRawImage(slot, message);
    Promise.resolve(render).catch(() => {}).finally(() => {
      state.rendering = false;
      state.nextRenderAt = performance.now() + (compressed ? COMPRESSED_CAMERA_RENDER_INTERVAL_MS : RAW_CAMERA_RENDER_INTERVAL_MS);
      if (state.pendingFrame) queueCameraFrame(slot, state.pendingFrame.channel, state.pendingFrame.data);
    });
  } catch (_) {
    const compressed = frame.channel.schemaName.endsWith('CompressedImage');
    state.rendering = false; state.nextRenderAt = performance.now() + (compressed ? COMPRESSED_CAMERA_RENDER_INTERVAL_MS : RAW_CAMERA_RENDER_INTERVAL_MS);
    setCameraState(slot, '图像帧解析失败');
    if (state.pendingFrame) queueCameraFrame(slot, state.pendingFrame.channel, state.pendingFrame.data);
  }
}

function normalizeAngle(value) {
  let angle = value;
  while (angle > Math.PI) angle -= Math.PI * 2;
  while (angle <= -Math.PI) angle += Math.PI * 2;
  return angle;
}
function initializeCloudWorker() {
  // 将动态点云 Canvas 的控制权一次性交给 Worker。旧实现每帧都需要
  // Worker -> ImageBitmap -> 主线程 drawImage，恰好会堵住位姿与交互事件。
  // 静态地图/墙体和车体仍是独立层，Worker 不会接触它们。
  if (!window.Worker || !window.OffscreenCanvas || !window.ImageBitmap) return;
  try {
    cloudWorker = new Worker(new URL('./liveCloudWorker.js', import.meta.url), { type: 'module' });
    cloudWorker.onmessage = ({ data }) => {
      if (data?.type === 'ready') { cloudWorkerReady = true; configureCloudWorker(); return; }
      if (data?.type === 'frame-skipped') { cloudWorkerBusy = false; flushCloudWorker(); return; }
      if (data?.type !== 'rendered' && data?.type !== 'frame') return;
      cloudWorkerBusy = false;
      // 兼容不支持 transferControlToOffscreen 的旧浏览器；现代浏览器中
      // Worker 已直接画到屏幕，不再做主线程 ImageBitmap 复制。
      if (data?.type === 'frame' && !cloudWorkerOwnsCanvas) {
        const canvas = $('cloudCanvas'); const context = canvas.getContext('2d');
        if (canvas.width !== data.width || canvas.height !== data.height) { canvas.width = data.width; canvas.height = data.height; }
        context.clearRect(0, 0, canvas.width, canvas.height); context.drawImage(data.bitmap, 0, 0); data.bitmap.close?.();
      }
      flushCloudWorker();
    };
    cloudWorker.onerror = () => { cloudWorkerFailed = true; cloudWorkerReady = false; cloudWorkerBusy = false; pendingCloudFrame = undefined; reportObservation('WARNING', cloudWorkerOwnsCanvas ? '点云 Worker 异常，已停止动态点云以保障小车位姿和地图交互。请刷新页面重试。' : '点云 Worker 不可用，已自动回退至兼容渲染。'); };
    const canvas = $('cloudCanvas');
    if (canvas?.transferControlToOffscreen) {
      const offscreen = canvas.transferControlToOffscreen();
      cloudWorkerOwnsCanvas = true;
      cloudWorker.postMessage({ type: 'init', canvas: offscreen }, [offscreen]);
    } else cloudWorker.postMessage({ type: 'init' });
  } catch (_) { cloudWorkerFailed = true; cloudWorker = undefined; }
}
function configureCloudWorker() {
  if (!cloudWorkerReady || !mapInfo) return;
  cloudWorker.postMessage({ type: 'map', width: mapInfo.width, height: mapInfo.height, resolution: mapInfo.resolution, origin: mapInfo.origin, historyMs: CLOUD_HISTORY_MS });
}
function sendCloudWorker(frame) {
  if (!cloudWorkerReady || cloudWorkerFailed || !cloudWorker) return false;
  if (cloudWorkerBusy) { pendingCloudFrame = frame; return true; }
  cloudWorkerBusy = true;
  cloudWorker.postMessage({ type: 'points', points: frame.points, receivedAt: frame.receivedAt }, [frame.points.buffer]);
  return true;
}
function flushCloudWorker() {
  if (!pendingCloudFrame || cloudWorkerBusy) return;
  const frame = pendingCloudFrame; pendingCloudFrame = undefined; sendCloudWorker(frame);
}
function packCloudPoints(points) {
  const packed = new Float32Array(points.length * 2);
  for (let index = 0; index < points.length; index += 1) { packed[index * 2] = points[index].x; packed[index * 2 + 1] = points[index].y; }
  return packed;
}
function mapHeadingForVehicle(yaw) {
  if (!Number.isFinite(yaw)) return 0;
  if (!Number.isFinite(lockedMapYaw) || Math.abs(normalizeAngle(yaw - lockedMapYaw)) >= MAP_REORIENT_THRESHOLD_RAD) lockedMapYaw = yaw;
  return lockedMapYaw;
}
function renderedVehiclePoseInMap() {
  const target = vehiclePoseInMap();
  if (!target?.position) return undefined;
  const now = performance.now();
  // 仅在 C++ 轻量位姿流提供了可信速度时，向前预测最多 90 ms。这样可抵消
  // WebSocket、浏览器事件循环与画布帧合成造成的固定展示延迟；预测严格限时，
  // 断流或急停时不会持续漂移。
  const predictionSeconds = Math.min(0.09, Math.max(0, now - Number(target.receivedAt || now)) / 1000);
  const velocity = target.velocity || { x: 0, y: 0 };
  const desiredPosition = {
    x: target.position.x + (Number.isFinite(velocity.x) ? velocity.x * predictionSeconds : 0),
    y: target.position.y + (Number.isFinite(velocity.y) ? velocity.y * predictionSeconds : 0),
  };
  if (!renderedVehiclePose || now - renderedVehicleAt > 1200
    || Math.hypot(desiredPosition.x - renderedVehiclePose.position.x, desiredPosition.y - renderedVehiclePose.position.y) > 2.5) {
    renderedVehiclePose = { position: desiredPosition, yaw: target.yaw, source: target.source };
    renderedVehicleAt = now;
    return renderedVehiclePose;
  }
  // 位姿由 C++ 节点以约 45 Hz 输出。较短时间常数只填补两个样本之间的间隔，
  // 不再给操作者造成“车已走、画面数秒后才动”的视觉滞后。
  const displacement = Math.hypot(desiredPosition.x - renderedVehiclePose.position.x, desiredPosition.y - renderedVehiclePose.position.y);
  const speed = Math.hypot(velocity.x || 0, velocity.y || 0);
  const alpha = 1 - Math.exp(-Math.min(80, Math.max(1, now - renderedVehicleAt)) / 20);
  if (displacement >= VEHICLE_POSITION_DEADBAND_M || speed >= VEHICLE_VELOCITY_DEADBAND_MPS) {
    renderedVehiclePose.position.x += (desiredPosition.x - renderedVehiclePose.position.x) * alpha;
    renderedVehiclePose.position.y += (desiredPosition.y - renderedVehiclePose.position.y) * alpha;
  }
  renderedVehiclePose.yaw = normalizeAngle(renderedVehiclePose.yaw + normalizeAngle(target.yaw - renderedVehiclePose.yaw) * alpha);
  renderedVehiclePose.source = target.source;
  renderedVehicleAt = now;
  return renderedVehiclePose;
}
function requestVehicleAnimation() {
  if (vehicleAnimationFrame || document.hidden || !vehiclePoseInMap()?.position) return;
  const render = () => {
    vehicleAnimationFrame = undefined;
    if (document.hidden || !lastMapLayout) return;
    const vehicle = renderedVehiclePoseInMap();
    if (vehicle?.position) syncVehicleLayer(vehicle, lastMapLayout);
    // 仅更新独立 DOM 车体层；不重新绘制地图、虚拟墙或点云。
    if (vehiclePoseInMap()?.position && performance.now() - vehicleUpdatedAt < 1500) vehicleAnimationFrame = requestAnimationFrame(render);
  };
  vehicleAnimationFrame = requestAnimationFrame(render);
}
function followVehicleCenter(vehicle) {
  const desired = {
    x: vehicle.position.x + (mapView.followOffset?.x || 0),
    y: vehicle.position.y + (mapView.followOffset?.y || 0),
  };
  if (!mapView.center || Math.hypot(desired.x - mapView.center.x, desired.y - mapView.center.y) > FOLLOW_CENTER_SNAP_DISTANCE_M) {
    mapView.center = desired;
    return;
  }
  mapView.center = {
    x: mapView.center.x + (desired.x - mapView.center.x) * FOLLOW_CENTER_ALPHA,
    y: mapView.center.y + (desired.y - mapView.center.y) * FOLLOW_CENTER_ALPHA,
  };
}
function hasPendingFollowAdjustment() {
  const vehicle = renderedVehiclePoseInMap();
  if (!vehicle?.position || overviewUntilMovement || !mapView.followVehicle) return false;
  const desiredX = vehicle.position.x + (mapView.followOffset?.x || 0);
  const desiredY = vehicle.position.y + (mapView.followOffset?.y || 0);
  const centerPending = !mapView.center || Math.hypot(desiredX - mapView.center.x, desiredY - mapView.center.y) > FOLLOW_CENTER_SETTLE_DISTANCE_M;
  return centerPending || !Number.isFinite(lockedMapYaw)
    || Math.abs(normalizeAngle(vehicle.yaw - lockedMapYaw)) >= MAP_REORIENT_THRESHOLD_RAD;
}
function requestFollowAnimation() {
  // 每次轻量位姿到达只申请一次合成。禁止运动时额外启动 60 FPS 全图循环，
  // 否则地图旋转、栅格与点云会压住后续位姿消息，形成“车已动、网页数秒后才动”。
  if (!mapInfo || document.hidden || !hasPendingFollowAdjustment()) return;
  scheduleMapDraw();
}

function currentMapLayout() {
  if (!mapInfo) return undefined;
  const canvas = $('mapCanvas');
  const fallbackCenter = {
    x: mapInfo.origin.x + mapInfo.width * mapInfo.resolution / 2,
    y: mapInfo.origin.y + mapInfo.height * mapInfo.resolution / 2,
  };
  const vehicle = renderedVehiclePoseInMap();
  if (overviewUntilMovement) mapView.center = fallbackCenter;
  else if (mapView.followVehicle && vehicle?.position) {
    followVehicleCenter(vehicle);
  }
  if (!mapView.center) mapView.center = fallbackCenter;
  if (!mapView.pixelsPerMeter) {
    const fullMapScale = Math.min(canvas.width / (mapInfo.width * mapInfo.resolution), canvas.height / (mapInfo.height * mapInfo.resolution)) * 0.92;
    mapView.pixelsPerMeter = overviewUntilMovement
      // 初始概览必须完整容纳地图；不能套用近景视图的最小缩放限制，
      // 否则在大地图上仍会出现边缘被裁切的“概览”。
      ? Math.max(1, fullMapScale)
      : Math.max(MIN_PIXELS_PER_METER, Math.min(MAX_PIXELS_PER_METER, canvas.width / DEFAULT_VIEW_METERS));
  }
  const ratio = mapInfo.resolution * mapView.pixelsPerMeter;
  const width = mapInfo.width * ratio; const height = mapInfo.height * ratio;
  return {
    ratio, width, height, pixelsPerMeter: mapView.pixelsPerMeter, center: mapView.center, vehicle,
    // Canvas 的 Y 轴向下。将世界画面旋转到“车头向上”，而车体轮廓保持固定，
    // 使操作者获得稳定的驾驶视角；尚未收到定位时仍以北向显示地图。
    rotation: vehicle ? mapHeadingForVehicle(vehicle.yaw) - Math.PI / 2 : 0,
    left: canvas.width / 2 + (mapInfo.origin.x - mapView.center.x) * mapView.pixelsPerMeter,
    top: canvas.height / 2 - (mapInfo.origin.y + mapInfo.height * mapInfo.resolution - mapView.center.y) * mapView.pixelsPerMeter,
  };
}
function scheduleMapDraw(interactive = false) {
  // 拖拽/缩放只改变 CSS 矩阵，必须在下一合成帧执行，不能被实时数据的 30 FPS
  // 节流排队。普通 ROS 更新仍保留限频，避免位姿消息挤占页面主线程。
  if (interactive && drawDeferredTimer) {
    window.clearTimeout(drawDeferredTimer);
    drawDeferredTimer = undefined;
    drawQueued = false;
  }
  if (drawQueued) return;
  drawQueued = true;
  const elapsed = performance.now() - lastMapDrawAt;
  const render = () => {
    drawDeferredTimer = undefined;
    drawAnimationFrame = requestAnimationFrame(() => {
      drawAnimationFrame = undefined; drawQueued = false; lastMapDrawAt = performance.now(); drawMap();
    });
  };
  if (interactive || elapsed >= MAP_RENDER_INTERVAL_MS) render();
  else drawDeferredTimer = window.setTimeout(render, MAP_RENDER_INTERVAL_MS - elapsed);
}
function stopRenderScheduling() {
  if (drawDeferredTimer) window.clearTimeout(drawDeferredTimer);
  if (drawAnimationFrame) window.cancelAnimationFrame(drawAnimationFrame);
  drawDeferredTimer = undefined; drawAnimationFrame = undefined; drawQueued = false;
  if (vehicleAnimationFrame) window.cancelAnimationFrame(vehicleAnimationFrame);
  vehicleAnimationFrame = undefined;
}
function drawMap() {
  if (!mapInfo || !mapRaster) return;
  // 静态地图和虚拟墙均已预绘制到 mapStaticCanvas。此处仅改变世界层的
  // CSS 变换；浏览器合成器可在 GPU 侧完成平移/旋转，不能重新绘制整张地图。
  const layout = currentMapLayout();
  lastMapLayout = layout;
  const stage = $('worldStage'); const world = $('mapWorld'); const cloudWorld = $('cloudWorld');
  const stageTransform = `rotate(${layout.rotation}rad)`;
  if (stage.style.transform !== stageTransform) stage.style.transform = stageTransform;
  // 单一合成变换：不会触发布局或重新栅格化静态地图，只更新 GPU 图层的位置与比例。
  const worldTransform = `translate3d(${layout.left}px, ${layout.top}px, 0) scale(${layout.ratio})`;
  if (world.style.width !== `${mapInfo.width}px`) world.style.width = `${mapInfo.width}px`;
  if (world.style.height !== `${mapInfo.height}px`) world.style.height = `${mapInfo.height}px`;
  if (world.style.transform !== worldTransform) world.style.transform = worldTransform;
  // 动态点云与静态地图是两个独立合成层。更新 cloudCanvas 时不应使地图纹理失效。
  if (cloudWorld.style.width !== `${mapInfo.width}px`) cloudWorld.style.width = `${mapInfo.width}px`;
  if (cloudWorld.style.height !== `${mapInfo.height}px`) cloudWorld.style.height = `${mapInfo.height}px`;
  if (cloudWorld.style.transform !== worldTransform) cloudWorld.style.transform = worldTransform;
  syncVehicleLayer(layout.vehicle, layout);
}

function renderStaticWorld() {
  if (!mapInfo || !mapRaster) return;
  const canvas = $('mapStaticCanvas');
  if (canvas.width !== mapInfo.width || canvas.height !== mapInfo.height) { canvas.width = mapInfo.width; canvas.height = mapInfo.height; }
  const context = canvas.getContext('2d'); context.clearRect(0, 0, canvas.width, canvas.height); context.imageSmoothingEnabled = false;
  context.drawImage(mapRaster, 0, 0, mapInfo.width, mapInfo.height);
  context.strokeStyle = '#d63142'; context.lineWidth = Math.max(1, 0.06 / mapInfo.resolution); context.lineCap = 'round'; context.lineJoin = 'round';
  for (const wall of virtualWalls) {
    const points = Array.isArray(wall.points) ? wall.points : [];
    if (points.length < 2) continue;
    context.beginPath();
    points.forEach((point, index) => {
      const world = wall.coordinate_mode === 'image_relative'
        ? { x: mapInfo.origin.x + Number(point.x), y: mapInfo.origin.y + Number(point.y) }
        : { x: Number(point.x), y: Number(point.y) };
      const targetX = (world.x - mapInfo.origin.x) / mapInfo.resolution;
      const targetY = mapInfo.height - (world.y - mapInfo.origin.y) / mapInfo.resolution;
      if (index === 0) context.moveTo(targetX, targetY); else context.lineTo(targetX, targetY);
    });
    context.stroke();
  }
}
function syncVehicleLayer(vehicle, layout) {
  const element = $('vehicleLayer');
  if (!vehicle?.position || !mapInfo || !Number.isFinite(Number(vehicle.position.x)) || !Number.isFinite(Number(vehicle.position.y))) { element.hidden = true; return; }
  const nativeX = (vehicle.position.x - mapInfo.origin.x) / mapInfo.resolution;
  const nativeY = mapInfo.height - (vehicle.position.y - mapInfo.origin.y) / mapInfo.resolution;
  const baseX = layout.left + nativeX * layout.ratio;
  const baseY = layout.top + nativeY * layout.ratio;
  const centerX = $('mapCanvas').width / 2; const centerY = $('mapCanvas').height / 2;
  const cosine = Math.cos(layout.rotation); const sine = Math.sin(layout.rotation);
  const x = centerX + cosine * (baseX - centerX) - sine * (baseY - centerY);
  const y = centerY + sine * (baseX - centerX) + cosine * (baseY - centerY);
  const length = Math.max(0.2, Number(vehicleModel.length_m) || 1.0) * layout.pixelsPerMeter;
  const width = Math.max(0.15, Number(vehicleModel.width_m) || 0.68) * layout.pixelsPerMeter;
  element.hidden = false; element.style.left = `${x}px`; element.style.top = `${y}px`;
  element.style.width = `${width}px`; element.style.height = `${length}px`;
  // 小车在独立屏幕层中绘制；地图已按锁定航向旋转，故只显示相对航向。
  const localYaw = (Number.isFinite(lockedMapYaw) ? lockedMapYaw : vehicle.yaw) - vehicle.yaw;
  element.style.transform = `translate(-50%, -50%) rotate(${localYaw}rad)`;
}
function vehiclePoseInMap() {
  // map->odom->base_* 通常比 /amcl_pose 频率高得多。优先使用最近 TF，才能让
  // 车体连续跟随实际运动；TF 短暂缺失时自动回退至定位话题，不改变安全边界。
  if (tfVehiclePose && performance.now() - tfVehiclePose.receivedAt < 1500) return tfVehiclePose;
  if (pose?.position) return { ...pose, yaw: yawOf(pose.orientation), source: 'pose' };
  return undefined;
}
function updateLivePose(message) {
  const position = message?.pose?.position;
  const orientation = message?.pose?.orientation;
  if (!position || !orientation || !Number.isFinite(Number(position.x)) || !Number.isFinite(Number(position.y))) return;
  // C++ 已完成 map->base 的查找；浏览器只处理一个极小 PoseStamped，避免解析完整 /tf。
  livePoseUpdatedAt = performance.now();
  vehicleUpdatedAt = livePoseUpdatedAt;
  if (tfFallbackTimer) { window.clearTimeout(tfFallbackTimer); tfFallbackTimer = undefined; }
  // 轻量流恢复后立即卸载兼容 TF，避免浏览器继续接收大批量变换消息。
  if (visualizationStreams.tf.subscriptionId !== undefined) stopStreamProbe('tf');
  const previous = tfVehiclePose?.source === 'live' ? tfVehiclePose : undefined;
  const elapsedSeconds = previous ? (livePoseUpdatedAt - previous.receivedAt) / 1000 : 0;
  let velocity = { x: 0, y: 0 };
  if (elapsedSeconds >= 0.01 && elapsedSeconds <= 0.3) {
    const vx = (Number(position.x) - previous.position.x) / elapsedSeconds;
    const vy = (Number(position.y) - previous.position.y) / elapsedSeconds;
    // 室内小车的显示预测绝不接受异常跳点或不现实的高速值。
    if (Math.hypot(vx, vy) <= 3.0) velocity = { x: vx, y: vy };
  }
  tfVehiclePose = { position, orientation, yaw: yawOf(orientation), source: 'live', receivedAt: livePoseUpdatedAt, velocity };
  updateDiagnostics(); scheduleMapDraw(); requestFollowAnimation(); requestVehicleAnimation();
}
function scheduleLatestCloudPacket(reader, data) {
  pendingCloudPacket = { reader, data, receivedAt: performance.now() };
  if (cloudPacketQueued) return;
  cloudPacketQueued = true;
  requestAnimationFrame(flushLatestCloudPacket);
}
function flushLatestCloudPacket() {
  cloudPacketQueued = false;
  const packet = pendingCloudPacket; pendingCloudPacket = undefined;
  if (packet && performance.now() - packet.receivedAt <= CLOUD_PACKET_MAX_AGE_MS) {
    try { updateCloud(packet.reader.readMessage(packet.data)); } catch (_) { /* 单帧异常不影响下一帧。 */ }
  }
  if (pendingCloudPacket && !cloudPacketQueued) {
    cloudPacketQueued = true;
    requestAnimationFrame(flushLatestCloudPacket);
  }
}
function scheduleLatestPosePacket(reader, data) {
  pendingPosePacket = { reader, data, receivedAt: performance.now() };
  if (posePacketQueued) return;
  posePacketQueued = true;
  requestAnimationFrame(flushLatestPosePacket);
}
function flushLatestPosePacket() {
  posePacketQueued = false;
  const packet = pendingPosePacket; pendingPosePacket = undefined;
  if (packet && performance.now() - packet.receivedAt <= POSE_PACKET_MAX_AGE_MS) {
    try { updateLivePose(packet.reader.readMessage(packet.data)); } catch (_) { /* 保持观测连接可用。 */ }
  }
  if (pendingPosePacket && !posePacketQueued) {
    posePacketQueued = true;
    requestAnimationFrame(flushLatestPosePacket);
  }
}
function updateDiagnostics(force = false) {
  const now = performance.now();
  // 诊断文字不需要随 TF 的十几 Hz 刷新；频繁修改 DOM 会与 Canvas 绘制争用
  // 主线程，反而造成地图“跟不上”。重要状态可传 force 立即展示。
  if (!force && now - lastDiagnosticsAt < 500) return;
  lastDiagnosticsAt = now;
  const mapText = mapInfo ? `${mapInfo.width} × ${mapInfo.height} 地图` : '等待地图';
  const vehicle = vehiclePoseInMap();
  const inMap = vehicle?.position && mapInfo && vehicle.position.x >= mapInfo.origin.x && vehicle.position.x <= mapInfo.origin.x + mapInfo.width * mapInfo.resolution && vehicle.position.y >= mapInfo.origin.y && vehicle.position.y <= mapInfo.origin.y + mapInfo.height * mapInfo.resolution;
  const source = vehicle?.source === 'live' ? '实时位姿' : (vehicle?.source === 'tf' ? 'TF' : '定位');
  const poseText = vehicle ? (inMap ? `${source} x ${vehicle.position.x.toFixed(2)} · y ${vehicle.position.y.toFixed(2)} · 小车已绘制` : `${source}不在当前地图范围`) : '等待定位/TF';
  const cloudAge = cloud ? Math.max(0, (performance.now() - cloudUpdatedAt) / 1000) : 0;
  const cloudCount = cloud?.mapPoints?.length || 0;
  const cloudText = pauseCloudForCamera()
    ? (cloud ? `图像低延迟优先，点云暂停 · 最近 ${cloudCount} 点` : '图像低延迟优先，点云暂停')
    : (cloud ? `${cloudCount} 个地图点 · ${cloudAge.toFixed(1)} 秒前` : '等待点云');
  const wallText = virtualWalls.length ? `${virtualWalls.length} 段虚拟墙` : wallStatus;
  setText('mapDiagnostics', `${mapText} · ${poseText} · ${cloudText} · ${wallText}`);
}

function mapSignature(info, data) {
  const stamp = info.map_load_time || {};
  // 只读取少量抽样值，避免每一张大图都额外扫描一遍；足以在 map_server 切图时识别版本。
  const sample = data ? [data[0], data[Math.floor(data.length / 2)], data[data.length - 1]].join(',') : '';
  return [info.width, info.height, info.resolution, info.origin?.position?.x, info.origin?.position?.y, stamp.sec, stamp.nanosec, sample].join('|');
}
function stopMapProbeSubscription() {
  if (mapProbeTimeout) { window.clearTimeout(mapProbeTimeout); mapProbeTimeout = undefined; }
  if (mapProbeSubscriptionId !== undefined) {
    client?.unsubscribe(mapProbeSubscriptionId); subscriptions?.delete(mapProbeSubscriptionId); mapProbeSubscriptionId = undefined;
  }
}

function stopStaticTfSubscription() {
  if (staticTfStopTimer) { window.clearTimeout(staticTfStopTimer); staticTfStopTimer = undefined; }
  if (staticTfSubscriptionId !== undefined) {
    client?.unsubscribe(staticTfSubscriptionId); subscriptions?.delete(staticTfSubscriptionId); staticTfSubscriptionId = undefined;
  }
}
function requestStaticTransforms() {
  if (!staticTfChannel || staticTfSubscriptionId !== undefined || !client || !readers?.has(staticTfChannel.id)) return;
  try {
    staticTfSubscriptionId = client.subscribe(staticTfChannel.id);
    subscriptions.set(staticTfSubscriptionId, { topic: '/tf_static', channelId: staticTfChannel.id, staticTf: true });
    staticTfStopTimer = window.setTimeout(stopStaticTfSubscription, STATIC_TF_WINDOW_MS);
  } catch (_) { /* 静态变换缺失时，点云仅降级为不投影。 */ }
}
function stopStreamProbe(kind) {
  const state = visualizationStreams[kind]; if (!state) return;
  if (state.subscriptionId !== undefined) {
    client?.unsubscribe(state.subscriptionId); subscriptions?.delete(state.subscriptionId); state.subscriptionId = undefined;
  }
}
function subscribeVisualizationStream(kind, channel) {
  const state = visualizationStreams[kind]; if (!state || !channel || !client || !readers?.has(channel.id)) return;
  if (state.channel?.id === channel.id && state.subscriptionId !== undefined) return;
  stopStreamProbe(kind); state.channel = channel;
  try {
    state.subscriptionId = client.subscribe(channel.id);
    subscriptions.set(state.subscriptionId, { topic: channel.topic, channelId: channel.id, visualizationKind: kind });
  } catch (_) { state.subscriptionId = undefined; }
}
function hasActiveCameraSubscription() {
  return ['A', 'B'].some((slot) => workspaceLayout?.[`camera${slot}`] && cameraSlots[slot].channelId);
}
function pauseCloudForCamera() {
  return Boolean(workspaceLayout?.cameraPriority && hasActiveCameraSubscription());
}
function activateVisualizationStreams() {
  const usePreprocessedStream = cloudTopic === '/aletheia/live_points' && livePoseChannel;
  subscribeVisualizationStream('livePose', livePoseChannel);
  // 预处理流已经把点云投影至 map，且轻量位姿已由 C++ 计算，不再把完整 /tf
  // 送到浏览器。原始点云或轻量位姿暂不可用时，保留历史兼容回退链路。
  if (usePreprocessedStream) {
    stopStreamProbe('tf'); stopStaticTfSubscription();
    if (tfFallbackTimer) window.clearTimeout(tfFallbackTimer);
    // advertise 并不代表轻量位姿已有数据；异常时再启用兼容 TF 链路。
    tfFallbackTimer = window.setTimeout(() => {
      if (!livePoseUpdatedAt || performance.now() - livePoseUpdatedAt > 1500) {
        requestStaticTransforms(); subscribeVisualizationStream('tf', tfChannel);
      }
    }, 1600);
  } else {
    if (tfFallbackTimer) { window.clearTimeout(tfFallbackTimer); tfFallbackTimer = undefined; }
    requestStaticTransforms(); subscribeVisualizationStream('tf', tfChannel);
  }
  // 高密度 PointCloud2 会在同一 WebSocket 上挤压相机帧。相机打开且操作者
  // 选择低延迟优先时，仅暂停点云订阅；地图、定位、TF、虚拟墙和车体照常更新。
  if (pauseCloudForCamera()) stopStreamProbe('cloud');
  else subscribeVisualizationStream('cloud', cloudChannel);
}
function stopVisualizationStreams() {
  if (tfFallbackTimer) { window.clearTimeout(tfFallbackTimer); tfFallbackTimer = undefined; }
  stopStaticTfSubscription();
  for (const kind of Object.keys(visualizationStreams)) {
    const state = visualizationStreams[kind]; stopStreamProbe(kind);
    state.channel = undefined;
  }
}
function scheduleMapProbe() {
  if (mapProbeTimer) window.clearTimeout(mapProbeTimer);
  mapProbeTimer = window.setTimeout(beginMapProbe, MAP_PROBE_INTERVAL_MS);
}
function beginMapProbe() {
  mapProbeTimer = undefined; stopMapProbeSubscription();
  if (!client || !mapChannel || !readers?.has(mapChannel.id)) return;
  try {
    mapProbeSubscriptionId = client.subscribe(mapChannel.id);
    subscriptions.set(mapProbeSubscriptionId, { topic: '/map', channelId: mapChannel.id, mapProbe: true });
    mapProbeTimeout = window.setTimeout(() => { stopMapProbeSubscription(); scheduleMapProbe(); }, MAP_PROBE_TIMEOUT_MS);
  } catch (_) { scheduleMapProbe(); }
}
function updateMap(message) {
  const info = message.info; if (!info?.width || !info?.height || !message.data || !(info.resolution > 0)) return;
  const signature = mapSignature(info, message.data);
  const changed = signature !== mapFingerprint;
  mapFingerprint = signature;
  if (!changed && mapRaster) { $('mapEmpty').hidden = true; stopMapProbeSubscription(); scheduleMapProbe(); return; }
  lockedMapYaw = undefined;
  cloudFrames = [];
  mapInfo = { width: info.width, height: info.height, resolution: info.resolution, origin: info.origin.position, frameId: normalizeFrame(message.header?.frame_id) || 'map' };
  // 地图本身由浏览器直连 Bridge 接收；只把必要元数据交给控制台解析同目录虚拟墙。
  // 地图切换才会调用一次，不上传栅格，不增加 ROS /map 订阅，也不持续扫描磁盘。
  virtualWalls = []; wallStatus = '正在匹配当前地图的虚拟墙';
  resolveLiveWalls(mapInfo, signature);
  mapRaster = document.createElement('canvas'); mapRaster.width = info.width; mapRaster.height = info.height;
  const imageContext = mapRaster.getContext('2d'); const pixels = imageContext.createImageData(info.width, info.height);
  for (let row = 0; row < info.height; row += 1) for (let col = 0; col < info.width; col += 1) {
    const occupancy = message.data[(info.height - 1 - row) * info.width + col];
    const color = occupancy < 0 ? 174 : occupancy >= 65 ? 36 : 245;
    const index = (row * info.width + col) * 4; pixels.data[index] = color; pixels.data[index + 1] = color; pixels.data[index + 2] = color; pixels.data[index + 3] = 255;
  }
  imageContext.putImageData(pixels, 0, 0); $('mapEmpty').hidden = true; stopMapProbeSubscription(); scheduleMapProbe(); renderStaticWorld(); configureCloudWorker(); projectCloud(); updateDiagnostics(); scheduleMapDraw();
  activateVisualizationStreams();
}

async function resolveLiveWalls(info, fingerprint) {
  if (resolvedWallFingerprint === fingerprint) return;
  resolvedWallFingerprint = fingerprint;
  try {
    const layers = await request('/api/observation/live-layers', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ width: info.width, height: info.height, resolution: info.resolution, origin: [info.origin.x, info.origin.y], frame_id: info.frameId }),
    });
    if (resolvedWallFingerprint !== fingerprint) return;
    virtualWalls = Array.isArray(layers.virtual_walls) ? layers.virtual_walls : [];
    wallStatus = layers.matched ? '当前地图未配置虚拟墙' : '当前地图未匹配虚拟墙';
    loadedWallMapId = layers.map_id;
  } catch (_) {
    if (resolvedWallFingerprint === fingerprint) { virtualWalls = []; wallStatus = '虚拟墙读取失败'; }
  }
  renderStaticWorld(); updateDiagnostics(); scheduleMapDraw();
}
function updatePose(message) {
  const source = message.pose?.pose; if (!source) return;
  const x = Number(source.position?.x); const y = Number(source.position?.y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) { pose = undefined; updateDiagnostics(); return; }
  pose = { position: { x, y }, orientation: source.orientation || { x: 0, y: 0, z: 0, w: 1 } };
  if (overviewUntilMovement) {
    if (!overviewPoseAnchor) overviewPoseAnchor = { x: pose.position.x, y: pose.position.y };
    const movement = Math.hypot(pose.position.x - overviewPoseAnchor.x, pose.position.y - overviewPoseAnchor.y);
    if (movement >= INITIAL_OVERVIEW_MOVEMENT_M) {
      overviewUntilMovement = false; mapView.pixelsPerMeter = undefined; mapView.followOffset = { x: 0, y: 0 };
    }
  }
  updateDiagnostics(); scheduleMapDraw(); requestFollowAnimation();
}
function updateTransforms(message) {
  let affectsVehicleView = false;
  for (const item of message.transforms || []) {
    const parent = normalizeFrame(item.header?.frame_id); const child = normalizeFrame(item.child_frame_id);
    if (!parent || !child || !item.transform?.translation) continue;
    transforms.set(`${parent}>${child}`, { parent, child, x: Number(item.transform.translation.x) || 0, y: Number(item.transform.translation.y) || 0, yaw: yawOf(item.transform.rotation) });
    // /tf 常混有相机、传感器等大量无关变换；只有地图/里程计/车体链路变动才
    // 更新缓存后的车体位姿与画面。
    if (mapInfo && (parent === mapInfo.frameId || child === mapInfo.frameId || parent === 'odom' || child === 'odom' || VEHICLE_BASE_FRAMES.includes(parent) || VEHICLE_BASE_FRAMES.includes(child))) affectsVehicleView = true;
  }
  if (!affectsVehicleView) return;
  for (const frame of VEHICLE_BASE_FRAMES) {
    const transform = transformToMap(frame, mapInfo.frameId);
    if (transform && Number.isFinite(transform.x) && Number.isFinite(transform.y)) {
      tfVehiclePose = { position: { x: transform.x, y: transform.y }, yaw: transform.yaw, source: 'tf', receivedAt: performance.now() };
      vehicleUpdatedAt = tfVehiclePose.receivedAt;
      break;
    }
  }
  updateDiagnostics(); scheduleMapDraw(); requestFollowAnimation(); requestVehicleAnimation();
}
function transformToMap(source, target) {
  source = normalizeFrame(source); target = normalizeFrame(target);
  if (!source || !target) return undefined;
  if (source === target) return { x: 0, y: 0, yaw: 0 };
  const queue = [{ frame: source, transform: { x: 0, y: 0, yaw: 0 } }]; const visited = new Set([source]);
  while (queue.length) {
    const current = queue.shift();
    for (const edge of transforms.values()) {
      let next; let step;
      if (edge.child === current.frame) { next = edge.parent; step = edge; }
      else if (edge.parent === current.frame) { next = edge.child; step = invert(edge); }
      else continue;
      if (visited.has(next)) continue;
      const transformed = compose(current.transform, step);
      if (next === target) return transformed;
      visited.add(next); queue.push({ frame: next, transform: transformed });
    }
  }
  return undefined;
}
function fieldOffset(fields, name) { return fields.find((field) => field.name === name)?.offset; }
function updateCloud(message) {
  const data = message.data; const step = message.point_step; const xOffset = fieldOffset(message.fields || [], 'x'); const yOffset = fieldOffset(message.fields || [], 'y'); const zOffset = fieldOffset(message.fields || [], 'z');
  if (!data || !step || xOffset === undefined || yOffset === undefined || zOffset === undefined) return;
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength); const count = Math.floor(view.byteLength / step); const stride = Math.max(1, Math.ceil(count / POINT_LIMIT)); const points = [];
  for (let index = 0; index < count; index += stride) {
    const offset = index * step; const x = view.getFloat32(offset + xOffset, !message.is_bigendian); const y = view.getFloat32(offset + yOffset, !message.is_bigendian); const z = view.getFloat32(offset + zOffset, !message.is_bigendian);
    if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z) && Math.abs(x) < 50 && Math.abs(y) < 50 && Math.abs(z) < 5) points.push({ x, y, z });
  }
  cloudUpdatedAt = performance.now();
  const frameId = normalizeFrame(message.header?.frame_id);
  // Aletheia 的预处理器已经把点云转换到 map。直接复用数组，避免每帧再创建
  // 数千个坐标对象；这一分支是实时视图的常态路径。
  cloud = { frameId, points, mapPoints: frameId === normalizeFrame(mapInfo?.frameId) ? points : [] };
  if (cloud.mapPoints.length) recordCloudFrame(); else projectCloud(true);
  // 点云只更新独立 cloudCanvas；不能反向触发地图相机/车体同步，
  // 否则 10~12 Hz 点云会拖慢 30 Hz 位姿视图。
  updateDiagnostics();
}
function recordCloudFrame() {
  const now = performance.now();
  cloudFrames.push({ receivedAt: now, points: cloud.mapPoints });
  cloudFrames = cloudFrames.filter((frame) => now - frame.receivedAt <= CLOUD_HISTORY_MS);
  // 单槽最新帧队列：Worker 忙时覆盖尚未处理的帧，禁止实时数据形成延迟积压。
  if (sendCloudWorker({ receivedAt: now, points: packCloudPoints(cloud.mapPoints) })) return;
  scheduleCloudRasterBuild();
}
function projectCloud(recordFrame = false) {
  if (!cloud || !mapInfo) return;
  const transform = transformToMap(cloud.frameId, mapInfo.frameId);
  if (!transform) { cloud.mapPoints = []; scheduleCloudRasterBuild(); return; }
  const cosine = Math.cos(transform.yaw); const sine = Math.sin(transform.yaw);
  cloud.mapPoints = cloud.points.map((point) => ({ x: cosine * point.x - sine * point.y + transform.x, y: sine * point.x + cosine * point.y + transform.y }));
  if (recordFrame) recordCloudFrame(); else scheduleCloudRasterBuild();
}
function scheduleCloudRasterBuild() {
  // 拖拽和缩放时点云并不需要重新投影；保留最新数据，交互结束后再一次性刷新。
  // 这样大点云的 Canvas fillRect 循环不会抢走鼠标事件和 CSS 合成帧。
  if (mapInteractionActive) { cloudRasterPending = true; return; }
  if (cloudRasterQueued) return;
  cloudRasterQueued = true;
  requestAnimationFrame(() => {
    cloudRasterQueued = false;
    rebuildCloudRaster();
  });
}
function rebuildCloudRaster() {
  // Worker 直绘模式下，主线程绝不能再 getContext()；否则既无收益又会抛错。
  if (cloudWorkerOwnsCanvas) return;
  const canvas = $('cloudCanvas');
  if (!mapInfo || !cloud?.mapPoints) { canvas.width = canvas.height = 1; return; }
  if (canvas.width !== mapInfo.width || canvas.height !== mapInfo.height) { canvas.width = mapInfo.width; canvas.height = mapInfo.height; }
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  const now = performance.now();
  const frames = cloudFrames.length ? cloudFrames : [{ receivedAt: now, points: cloud.mapPoints }];
  for (const frame of frames) {
    const ageRatio = Math.max(0, 1 - (now - frame.receivedAt) / CLOUD_HISTORY_MS);
    context.fillStyle = `rgba(128, 88, 255, ${0.16 + ageRatio * 0.64})`;
    for (const point of frame.points) {
      const x = (point.x - mapInfo.origin.x) / mapInfo.resolution;
      const y = mapInfo.height - (point.y - mapInfo.origin.y) / mapInfo.resolution;
      if (x >= 0 && x < mapInfo.width && y >= 0 && y < mapInfo.height) context.fillRect(x - 0.35, y - 0.35, 0.7, 0.7);
    }
  }
}
async function refreshWalls(observation) {
  // 实时 /map 已经可用时，墙体由 resolveLiveWalls() 基于同一份地图元数据加载，
  // 不能再以旧轨迹缓存替换正在显示的实际地图。
  if (mapInfo) return;
  const mapId = observation.active_map_id;
  if (!mapId || (mapId === loadedWallMapId && mapId === loadedMapId)) return;
  try {
    const layers = await request(`/api/observation/maps/${encodeURIComponent(mapId)}/layers`);
    virtualWalls = Array.isArray(layers.virtual_walls) ? layers.virtual_walls : []; loadedWallMapId = mapId;
    loadCachedMap(mapId, layers.map);
  } catch (_) { virtualWalls = []; loadedWallMapId = mapId; }
  updateDiagnostics(); scheduleMapDraw();
}
function loadCachedMap(mapId, metadata) {
  if (mapId === loadedMapId || !metadata?.width || !metadata?.height || !(metadata.resolution > 0) || !Array.isArray(metadata.origin)) return;
  loadedMapId = mapId;
  const image = new Image();
  image.decoding = 'async';
  image.onload = () => {
    if (loadedMapId !== mapId) return;
    mapInfo = {
      width: Number(metadata.width), height: Number(metadata.height), resolution: Number(metadata.resolution),
      origin: { x: Number(metadata.origin[0]) || 0, y: Number(metadata.origin[1]) || 0 }, frameId: normalizeFrame(metadata.frame_id) || 'map',
    };
    mapFingerprint = `cache:${mapId}`; mapRaster = image; $('mapEmpty').hidden = true;
    lockedMapYaw = undefined;
    cloudFrames = [];
    // 进入观测页且车辆尚未提供定位时，优先展示完整地图；运行中切图则延续随车视角。
    if (!pose?.position) {
      overviewUntilMovement = true; overviewPoseAnchor = undefined; mapView.pixelsPerMeter = undefined;
      mapView.center = undefined; mapView.followOffset = { x: 0, y: 0 };
    }
    renderStaticWorld(); configureCloudWorker(); projectCloud(); updateDiagnostics(); scheduleMapDraw();
  };
  image.onerror = () => {
    if (loadedMapId === mapId) { loadedMapId = undefined; setText('mapDiagnostics', '当前地图缓存读取失败；请在测试任务中重新开启轨迹记录。'); }
  };
  image.src = `/api/observation/maps/${encodeURIComponent(mapId)}/preview.png`;
}

function connect(payload) {
  const port = Number(payload?.bridge?.port);
  const rawHost = String(location.hostname || '').trim();
  if (!Number.isInteger(port) || !rawHost) throw new Error('未取得 Aletheia Bridge 的直连地址');
  // Bridge 当前以明文 WebSocket 服务于受控测试 Wi-Fi；IPv6 地址需要方括号。
  // 控制台若通过 HTTPS 提供，浏览器会阻止 ws:// 混合内容，直接提示而非反复重连。
  if (location.protocol === 'https:') throw new Error('直连 Bridge 需要通过 HTTP 打开 Aletheia 控制台；当前 HTTPS 页面不能连接明文 ws 服务');
  const host = rawHost.includes(':') ? `[${rawHost}]` : rawHost;
  const url = `ws://${host}:${port}`;
  setText('connectionState', '连接中'); setText('connectionDetail', url);
  const ws = new WebSocket(url, [FOXGLOVE_BRIDGE_SUBPROTOCOL]); ws.binaryType = 'arraybuffer'; client = new FoxgloveClient({ ws });
  readers = new Map(); subscriptions = new Map();
  client.on('open', () => { setText('connectionState', '已连接'); setText('sideState', '本地实时数据'); setText('connectionDetail', `Foxglove Bridge · ${url}`); reportObservation('INFO', `WebSocket 已连接：${url}`); });
  client.on('error', (error) => {
    const detail = error.message || `无法直连 ${url}；请确认小车与浏览器在同一 Wi‑Fi，并放行该端口`;
    setText('connectionState', '连接失败'); setText('connectionDetail', detail); reportObservation('ERROR', `WebSocket 连接错误：${url}；${detail}`);
  });
  client.on('close', (event) => {
    const detail = `WebSocket 已关闭（代码 ${event.code || '未知'}${event.reason ? `，${event.reason}` : ''}）`;
    setText('connectionState', '已断开'); setText('sideState', '观测已断开'); setText('connectionDetail', detail); reportObservation('WARNING', `${url}；${detail}`);
  });
  client.on('advertise', (channels) => channels.forEach((channel) => {
    if (!TOPICS.has(channel.topic) && !isImageChannel(channel)) return;
    try {
      readers.set(channel.id, new MessageReader(parse(channel.schema, { ros2: true })));
      if (isCameraCandidate(channel)) { cameraChannels.set(channel.id, channel); refreshCameraOptions(); }
      else if (channel.topic === '/map') { mapChannel = channel; beginMapProbe(); }
      else if (channel.topic === '/amcl_pose') subscriptions.set(client.subscribe(channel.id), { topic: channel.topic, channelId: channel.id });
      else if (channel.topic === '/aletheia/live_pose') { livePoseChannel = channel; if (mapInfo) activateVisualizationStreams(); }
      else if (channel.topic === '/tf') { tfChannel = channel; if (mapInfo) activateVisualizationStreams(); }
      else if (channel.topic === '/tf_static') { staticTfChannel = channel; if (mapInfo) activateVisualizationStreams(); }
      else if (channel.topic === cloudTopic) { cloudChannel = channel; if (mapInfo) activateVisualizationStreams(); }
    } catch (_) { /* 单一话题类型不兼容时，其余图层继续工作。 */ }
  }));
  client.on('unadvertise', (channelIds) => {
    channelIds.forEach((channelId) => cameraChannels.delete(channelId));
    if (channelIds.includes(tfChannel?.id)) { tfChannel = undefined; stopStreamProbe('tf'); }
    if (channelIds.includes(livePoseChannel?.id)) { livePoseChannel = undefined; stopStreamProbe('livePose'); if (mapInfo) activateVisualizationStreams(); }
    if (channelIds.includes(cloudChannel?.id)) { cloudChannel = undefined; stopStreamProbe('cloud'); }
    if (channelIds.includes(staticTfChannel?.id)) { staticTfChannel = undefined; stopStaticTfSubscription(); }
    if (channelIds.includes(mapChannel?.id)) { mapChannel = undefined; stopMapProbeSubscription(); }
    for (const slot of ['A', 'B']) {
      if (channelIds.includes(cameraSlots[slot].channelId)) selectCamera(slot, '');
    }
    refreshCameraOptions();
  });
  client.on('message', ({ subscriptionId, data }) => {
    const subscription = subscriptions.get(subscriptionId); const topic = subscription?.topic; const reader = readers.get(subscription?.channelId);
    if (!topic || !reader) return;
    if (subscription.cameraSlot) { queueCameraFrame(subscription.cameraSlot, cameraChannels.get(subscription.channelId), data); return; }
    // 先只保留最新二进制帧，延迟到下一个显示帧再反序列化。不能在 WebSocket
    // 回调逐包解码，否则页面一旦落后就会持续处理已经没有价值的旧点云。
    if (topic === cloudTopic) { scheduleLatestCloudPacket(reader, data); return; }
    if (topic === '/aletheia/live_pose') { scheduleLatestPosePacket(reader, data); return; }
    const now = performance.now();
    if (topic === '/tf' && now - tfUpdatedAt < TF_MIN_INTERVAL_MS) return;
    try {
      const message = reader.readMessage(data);
      if (topic === '/map') updateMap(message); else if (topic === '/amcl_pose') updatePose(message); else { if (topic === '/tf') tfUpdatedAt = now; updateTransforms(message); }
    } catch (_) { /* 单帧损坏或字段变化不能中断观测。 */ }
  });
}
async function main() {
  initializeTheme(); setupCameraSelectors(); setupWorkspace(); setupMapInteraction(); initializeCloudWorker();
  try {
    const [settings, upgrade] = await Promise.all([request('/api/settings'), request('/api/system/upgrade')]);
    setText('consoleVersion', upgrade.current_version ? `v${upgrade.current_version}` : '开发版');
    if (!settings.live_observation?.enabled) { setText('connectionState', '未启用'); setText('connectionDetail', '请先在运行配置启用实时运行观测。'); return; }
    const models = Array.isArray(settings.live_observation?.vehicle_models) ? settings.live_observation.vehicle_models : [];
    vehicleModel = models.find((item) => item.id === settings.live_observation?.active_vehicle_model) || models[0] || vehicleModel;
    // 必须由受控接口确认该端口属于 Aletheia；不能因“本机端口可达”而误接入外部 Bridge。
    let ready = await request('/api/observation/start', { method: 'POST' });
    for (let attempt = 0; !ready.bridge?.online && attempt < 12; attempt += 1) {
      setText('connectionState', 'Bridge 启动中'); setText('connectionDetail', `正在等待端口就绪（${attempt + 1}/12）`);
      await new Promise((resolve) => window.setTimeout(resolve, 500)); ready = await request('/api/observation');
    }
    if (!ready.bridge?.online) { setText('connectionState', 'Bridge 未就绪'); setText('connectionDetail', '请在诊断日志中检查 foxglove_bridge 启动记录。'); return; }
    cloudTopic = ready.bridge?.cloud_topic === '/aletheia/live_points' ? '/aletheia/live_points' : '/livox/points';
    await refreshWalls(ready); connect(ready);
    window.setInterval(() => request('/api/observation/heartbeat', { method: 'POST' }).then(refreshWalls).catch(() => {}), 5000);
  } catch (error) { setText('connectionState', '不可用'); setText('connectionDetail', error.message); reportObservation('ERROR', `实时观测初始化失败：${error.message}`); }
}
window.addEventListener('beforeunload', () => { stopRenderScheduling(); stopMapProbeSubscription(); stopVisualizationStreams(); client?.close(); });
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopRenderScheduling();
  else if (mapInfo) scheduleMapDraw();
});
main();
