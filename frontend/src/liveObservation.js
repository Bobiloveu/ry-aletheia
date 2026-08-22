import { FoxgloveClient } from '@foxglove/ws-protocol';
import { parse } from '@foxglove/rosmsg';
import { MessageReader } from '@foxglove/rosmsg2-serialization';
import { Application, BufferImageSource, Container, Graphics, Sprite, Texture } from 'pixi.js';
import '../../autodrive_console/web/styles.css';
import '../../autodrive_console/web/refinement.css';
import '../../autodrive_console/web/page_views.css';
import './liveObservation.css';

// 只订阅二维观测必要的话题。TF 仅用于将雷达点云投影到地图坐标，不做三维场景渲染。
// /map 的历史样本在本车上只对 TRANSIENT_LOCAL 订阅可见。底图由轨迹记录器
// 安全缓存后通过 HTTP 提供；浏览器直连 Aletheia 私有 Bridge 获取实时数据。
// /map 必须进入白名单：它是 TRANSIENT_LOCAL 话题，浏览器仅在短订阅窗口内
// 接收一次当前栅格；遗漏它会导致 Bridge 已连接但地图永远无法开始加载。
const LIVE_CLOUD_TOPIC = '/_aletheia/live_points';
const LIVE_POSE_TOPIC = '/_aletheia/live_pose';
const DEFAULT_LIVE_CLOUD_SOURCE_TOPIC = '/collision_voxel_layer/points';
const TOPICS = new Set(['/map', '/amcl_pose', LIVE_POSE_TOPIC, DEFAULT_LIVE_CLOUD_SOURCE_TOPIC, LIVE_CLOUD_TOPIC, '/tf', '/tf_static']);
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
const CLOUD_PACKET_MAX_AGE_MS = 100;
// 点云保持 latest-wins，但不必与激光每一帧等速合成。8 Hz 已足够观察环境
// 结构，并避免频繁更新点云几何抢占车体 CSS 合成。
const CLOUD_COMPOSITE_MIN_INTERVAL_MS = 125;
// 位姿包远小于点云，但在浏览器刚完成一次地图合成时可能恰好错过 120 ms
// 窗口。保留 250 ms 仍是当前画面，不会形成历史回放，却能避免车体偶发断流。
const POSE_PACKET_MAX_AGE_MS = 250;
const LIVE_POSE_FALLBACK_MS = 450;
// 实测 /tf 可稳定高频到达。仅消费约 30 Hz 已足够让车体连续运动，同时避免把
// 数百 Hz 的 TF 批量解析和整图重绘带入浏览器主线程。
const TF_MIN_INTERVAL_MS = 33;
// 地图旋转、栅格缩放与高密度点云合成是最重的浏览器操作。数据接收可更快，
// 但 PixiJS 只按可见效果提交，避免每一帧 TF 都触发整图重绘。
// 地图世界层只更新 PixiJS 变换，不重新上传地图纹理或点云几何；因此可按显示器
// 刷新率合成，避免 30 FPS 相机跟随让车体看似一卡一顿。
const MAP_RENDER_INTERVAL_MS = 16;
// 地图源本身约为千级像素；限制到 CSS 像素级可避免在高 DPI 电脑上反复旋转
// 超采样的渲染目标，显著降低主视图卡顿，同时不压缩或修改原始地图数据。
// 图像是观测页中带宽和解码开销最大的内容。实时查看应优先展示最新状态，
// 而不是让浏览器逐帧补完历史画面；否则延迟会持续累积并明显落后于 RViz2。
// 压缩图像由浏览器异步解码，直接调度最新帧；原始图像需要逐像素转换，
// 因此保守限速以免抢占地图和点云的主线程时间。两者均只绘制最新帧。
const COMPRESSED_CAMERA_RENDER_INTERVAL_MS = 0;
const RAW_CAMERA_RENDER_INTERVAL_MS = 200;
// /map 是 transient-local 的静态资产。保持一个订阅即可收到首次地图以及
// map_server 切图时发布的新地图，不能用定时退订/重订来“探测”切图：那会把
// 完整 OccupancyGrid 周期性塞回主线程，造成点云和车体同时掉帧。
// 点云和动态 TF 只在实时观测页打开且地图已就绪后订阅。此前短脉冲订阅会在
// Bridge 创建 ROS 订阅或 TF 尚未到达时错过样本，表现为点云冻结；改为持续订阅，
// 再在浏览器端限频解码最新帧，避免重复创建订阅和积压旧帧。
const STATIC_TF_WINDOW_MS = 1400;
// /map 本身始终是持久订阅。此轻量标记只读取 active_map.json 中的 ID，用来
// 发现部分 map_server 在生命周期切换时未向既有 Bridge 订阅及时重放栅格的情况。
// 确认切图后才重订阅一次 /map，绝不轮询大 OccupancyGrid。
const ACTIVE_MAP_SYNC_MS = 1000;
// 地图服务切换时，/map 栅格可能先到而 map_server 参数或同目录墙文件稍后才
// 可读。未匹配不是最终状态：有限重试既能补画虚拟墙，又不在运行中持续扫描磁盘。
const LIVE_WALL_RETRY_DELAYS_MS = [800, 2000, 5000];
const DEFAULT_VIEW_METERS = 16;
const MIN_PIXELS_PER_METER = 8;
const MAX_PIXELS_PER_METER = 420;
const INITIAL_OVERVIEW_MOVEMENT_M = 0.12;
// 实际定位会有厘米级位置与航向抖动。视角采用慢跟随而非逐帧硬锁定，
// 使驾驶观察稳定，同时保留明显转弯/位移的响应。
const FOLLOW_CENTER_ALPHA = 0.24;
const FOLLOW_CENTER_SNAP_DISTANCE_M = 1.5;
// 平滑接近目标后必须停止补帧。否则静止小车持续发布的 TF 会不断延长动画窗口，
// 使页面在没有可见变化时仍维持高频重绘。
const FOLLOW_CENTER_SETTLE_DISTANCE_M = 0.008;
// 静止定位仍会有毫米级浮动。显示层使用 2.5 cm 滞回，累计位移超过阈值才更新，
// 不修改 ROS 原始位姿；缓慢真实移动会自然越过阈值而继续显示。
const VEHICLE_POSITION_DEADBAND_M = 0.006;
const VEHICLE_VELOCITY_DEADBAND_MPS = 0.05;
const VEHICLE_STILL_HOLD_DISTANCE_M = 0.025;
const VEHICLE_STILL_RELEASE_DISTANCE_M = 0.045;
const VEHICLE_STILL_HOLD_YAW_RAD = 0.025;
const VEHICLE_STILL_RELEASE_YAW_RAD = 0.05;
const VEHICLE_STILL_SETTLE_MS = 220;
const MAX_VEHICLE_PREDICTION_MS = 300;
const ALPHA_BETA_POSITION_GAIN = 0.72;
const ALPHA_BETA_VELOCITY_GAIN = 0.12;
const MAX_VEHICLE_YAW_RATE_RADPS = 2.8;
const $ = (id) => document.getElementById(id);
let client;
// 位姿使用独立 TCP/WebSocket。即使点云连接正在传输大帧，也不会在浏览器
// 或 TCP 的有序字节流中阻塞这个小而高频的控制台状态流。
let poseClient;
let poseReaders;
let poseSubscriptions;
let poseLaneChannel;
let cloudUpdatedAt = 0;
let tfUpdatedAt = 0;
let livePoseUpdatedAt = 0;
let vehicleUpdatedAt = 0;
let mapInfo;
let mapTexture;
let cloudRasterQueued = false;
let pendingCloudFrame;
let cloudRenderTimer;
let lastCloudRenderAt = 0;
let mapGeneration = 0;
let pixiApp;
let pixiWorld;
let pixiMapLayer;
let pixiWallLayer;
let pixiCloudLayer;
let pixiMapSprite;
let pixiMapTexture;
let pixiReady = false;
let pixiInitialization;
const mapViewport = { width: 1, height: 1 };
let pendingCloudPacket;
let cloudPacketQueued = false;
let pendingPosePacket;
let posePacketQueued = false;
let pose;
let tfVehiclePose;
let renderedVehiclePose;
let renderedVehicleAt = 0;
let livePoseSourceAgeMs = 0;
let liveCloudSourceAgeMs = 0;
const clientPerformance = { startedAt: performance.now(), posePackets: 0, poseApplied: 0, cloudPackets: 0, vehicleFrames: 0, vehicleLongFrames: 0, vehicleFrameIntervalMs: 0, lastVehicleFrameAt: 0 };
let vehicleStillAnchor;
let vehicleStillCandidate;
let vehicleStillCandidateAt = 0;
let cloud;
let virtualWalls = [];
let wallStatus = '等待虚拟墙匹配';
let loadedWallMapId;
let loadedMapId;
let requestedActiveMapId;
const transforms = new Map();
// 不同车型/定位栈对底盘坐标系的命名可能不同。/amcl_pose 暂时不可用时，
// 直接从 TF 的 map -> base_* 链路绘制车体，不能因单一定位话题短暂缺帧而消失。
const VEHICLE_BASE_FRAMES = ['base_footprint', 'base_link', 'base_footprint_link'];
const cameraChannels = new Map();
const cameraSlots = { A: {}, B: {} };
let readers;
let subscriptions;
let mapChannel;
let mapProbeSubscriptionId;
let mapFingerprint;
let resolvedWallFingerprint;
let liveWallRetryTimer;
let liveWallRetryCount = 0;
let tfChannel;
let staticTfChannel;
let livePoseChannel;
let cloudChannel;
let cloudTopic = DEFAULT_LIVE_CLOUD_SOURCE_TOPIC;
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
function reportClientMetrics() {
  const now = performance.now(); const elapsedSeconds = Math.max(0.001, (now - clientPerformance.startedAt) / 1000);
  const body = JSON.stringify({
    pose_packet_rate_hz: clientPerformance.posePackets / elapsedSeconds,
    pose_applied_rate_hz: clientPerformance.poseApplied / elapsedSeconds,
    pose_message_age_ms: livePoseUpdatedAt ? now - livePoseUpdatedAt : 5000,
    pose_source_age_ms: livePoseSourceAgeMs,
    vehicle_render_rate_hz: clientPerformance.vehicleFrames / elapsedSeconds,
    vehicle_frame_interval_ms: clientPerformance.vehicleFrameIntervalMs,
    vehicle_long_frames: clientPerformance.vehicleLongFrames,
    cloud_packet_rate_hz: clientPerformance.cloudPackets / elapsedSeconds,
    cloud_source_age_ms: liveCloudSourceAgeMs,
  });
  fetch('/api/observation/client-metrics', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }).catch(() => {});
  clientPerformance.startedAt = now; clientPerformance.posePackets = 0; clientPerformance.poseApplied = 0; clientPerformance.cloudPackets = 0; clientPerformance.vehicleFrames = 0; clientPerformance.vehicleLongFrames = 0;
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
function createRgbaTexture(pixels, width, height) {
  return new Texture({ source: new BufferImageSource({ resource: pixels, width, height, format: 'rgba8unorm' }) });
}
function layoutCameraSprite(state) {
  if (!state.sprite || !state.viewport || !state.frameWidth || !state.frameHeight) return;
  const scale = Math.min(state.viewport.width / state.frameWidth, state.viewport.height / state.frameHeight);
  state.sprite.width = state.frameWidth * scale; state.sprite.height = state.frameHeight * scale;
  state.sprite.position.set((state.viewport.width - state.sprite.width) / 2, (state.viewport.height - state.sprite.height) / 2);
}
function clearCameraTexture(state) {
  state.sprite?.destroy(); state.sprite = undefined;
  state.texture?.destroy(true); state.texture = undefined;
  state.imageBitmap?.close(); state.imageBitmap = undefined;
  state.frameWidth = undefined; state.frameHeight = undefined;
}
function presentCameraTexture(slot, texture, width, height, imageBitmap) {
  const state = cameraSlots[slot];
  if (!state.app) { texture.destroy(true); imageBitmap?.close(); return; }
  clearCameraTexture(state);
  state.texture = texture; state.imageBitmap = imageBitmap; state.frameWidth = width; state.frameHeight = height;
  state.sprite = new Sprite(texture); state.app.stage.addChild(state.sprite);
  layoutCameraSprite(state); state.app.render();
}
async function initializeCameraRenderer(slot) {
  const state = cameraSlots[slot]; const host = $(`cameraView${slot}`);
  if (!host || state.initialization) return state.initialization;
  state.initialization = (async () => {
    const rect = host.getBoundingClientRect(); const width = Math.max(1, Math.round(rect.width) || 640); const height = Math.max(1, Math.round(rect.height) || 360);
    const app = new Application();
    await app.init({ width, height, background: 0x02070d, antialias: false, autoDensity: true, resolution: window.devicePixelRatio || 1 });
    app.ticker.stop(); app.canvas.classList.add('pixi-camera-canvas'); app.canvas.setAttribute('aria-hidden', 'true');
    host.replaceChildren(app.canvas); state.app = app; state.viewport = { width, height };
    const resize = () => {
      const next = host.getBoundingClientRect(); const nextWidth = Math.max(1, Math.round(next.width)); const nextHeight = Math.max(1, Math.round(next.height));
      if (state.viewport.width === nextWidth && state.viewport.height === nextHeight) return;
      state.viewport = { width: nextWidth, height: nextHeight }; app.renderer.resize(nextWidth, nextHeight); layoutCameraSprite(state); app.render();
    };
    state.resizeObserver = new ResizeObserver(resize); state.resizeObserver.observe(host); resize();
  })();
  return state.initialization;
}
function clearCamera(slot) {
  const state = cameraSlots[slot]; clearCameraTexture(state); state.app?.render();
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
  const interaction = $('mapInteraction');
  const wrap = interaction.parentElement;
  const resizeMapViewport = () => {
    const wrap = interaction.parentElement; const rect = wrap?.getBoundingClientRect();
    if (!rect?.width || !rect?.height) return;
    // 交互层和 Pixi 世界层均严格使用 CSS 像素；渲染器自行处理高 DPI，不能
    // 把 devicePixelRatio 混入视图坐标，否则滚轮锚点会与车体层错位。
    const width = Math.max(1, Math.round(rect.width)); const height = Math.max(1, Math.round(rect.height));
    if (mapViewport.width === width && mapViewport.height === height) return;
    mapViewport.width = width; mapViewport.height = height;
    pixiApp?.renderer.resize(width, height);
    // 坐标系变化后让布局根据当前容器重算，避免窗口大小变化造成模糊或跳变。
    mapView.pixelsPerMeter = undefined;
    scheduleMapDraw();
  };
  new ResizeObserver(resizeMapViewport).observe(interaction.parentElement);
  resizeMapViewport();
  let pan;
  const touchPoints = new Map();
  let pinch;
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
  const eventViewportPoint = (event) => {
    const rect = interaction.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const worldAtViewportPoint = (target, layout) => {
    const dx = target.x - mapViewport.width / 2; const dy = target.y - mapViewport.height / 2;
    const cosine = Math.cos(layout.rotation); const sine = Math.sin(layout.rotation);
    return {
      x: layout.center.x + (cosine * dx + sine * dy) / layout.pixelsPerMeter,
      y: layout.center.y - (-sine * dx + cosine * dy) / layout.pixelsPerMeter,
    };
  };
  const midpoint = () => {
    const points = [...touchPoints.values()];
    return { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 };
  };
  const distanceBetweenTouches = () => {
    const points = [...touchPoints.values()];
    return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  };
  const beginPinch = () => {
    if (touchPoints.size !== 2 || !mapInfo) return;
    const layout = currentMapLayout(); const point = midpoint();
    pinch = { distance: Math.max(1, distanceBetweenTouches()), pixelsPerMeter: layout.pixelsPerMeter, anchor: worldAtViewportPoint(point, layout) };
    pan = undefined; interaction.classList.remove('is-panning');
  };
  const applyPinch = () => {
    if (!pinch || touchPoints.size !== 2 || !mapInfo) return;
    const point = midpoint(); const factor = distanceBetweenTouches() / pinch.distance;
    mapView.pixelsPerMeter = Math.max(MIN_PIXELS_PER_METER, Math.min(MAX_PIXELS_PER_METER, pinch.pixelsPerMeter * factor));
    const before = currentMapLayout(); const dx = point.x - mapViewport.width / 2; const dy = point.y - mapViewport.height / 2;
    const cosine = Math.cos(before.rotation); const sine = Math.sin(before.rotation);
    const desiredCenter = {
      x: pinch.anchor.x - (cosine * dx + sine * dy) / mapView.pixelsPerMeter,
      y: pinch.anchor.y + (-sine * dx + cosine * dy) / mapView.pixelsPerMeter,
    };
    const vehicle = vehiclePoseInMap();
    if (vehicle?.position) {
      mapView.followVehicle = true;
      mapView.followOffset = { x: desiredCenter.x - vehicle.position.x, y: desiredCenter.y - vehicle.position.y };
    } else mapView.center = desiredCenter;
    overviewUntilMovement = false;
    scheduleMapDraw(true);
  };
  const onWheel = (event) => {
    if (!mapInfo) return;
    event.preventDefault();
    event.stopPropagation();
    setInteractionActive(true);
    deferInteractionEnd();
    overviewUntilMovement = false;
    const before = currentMapLayout(); const cursor = eventViewportPoint(event); const anchor = worldAtViewportPoint(cursor, before);
    // 对鼠标滚轮和触控板使用相同的连续比例，而不是每一条事件只跳一个固定档位。
    // 这使放大/缩小响应立即且不会被浏览器的滚动节流吞掉。
    const factor = Math.exp(Math.max(-0.32, Math.min(0.32, -event.deltaY * 0.0022)));
    mapView.pixelsPerMeter = Math.max(MIN_PIXELS_PER_METER, Math.min(MAX_PIXELS_PER_METER, (mapView.pixelsPerMeter || mapViewport.width / DEFAULT_VIEW_METERS) * factor));
    // 光标下的世界坐标在缩放前后不变；保存相对车辆偏移后，车辆仍保持连续跟随。
    const dx = cursor.x - mapViewport.width / 2; const dy = cursor.y - mapViewport.height / 2;
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
  interaction.addEventListener('dblclick', () => {
    overviewUntilMovement = false;
    mapView.followVehicle = true; mapView.followOffset = { x: 0, y: 0 };
    const vehicle = vehiclePoseInMap();
    if (vehicle?.position) mapView.center = { x: vehicle.position.x, y: vehicle.position.y };
    scheduleMapDraw(true);
  });
  const finishPan = (event) => {
    if (!pan || (event && event.pointerId !== pan.pointerId)) return;
    if (interaction.hasPointerCapture(pan.pointerId)) interaction.releasePointerCapture(pan.pointerId);
    pan = undefined; interaction.classList.remove('is-panning');
  };
  interaction.addEventListener('pointerdown', (event) => {
    // 同时支持左键和中键拖拽；中键仍保留，左键避免操作者误以为地图不能拖动。
    if ((event.button !== 0 && event.button !== 1) || !mapInfo) return;
    event.preventDefault();
    setInteractionActive(true);
    if (event.pointerType === 'touch') {
      touchPoints.set(event.pointerId, eventViewportPoint(event));
      interaction.setPointerCapture(event.pointerId);
      if (touchPoints.size === 2) beginPinch();
      else if (touchPoints.size > 2) pinch = undefined;
      else { pan = { pointerId: event.pointerId, point: eventViewportPoint(event) }; interaction.classList.add('is-panning'); }
      return;
    }
    pan = { pointerId: event.pointerId, point: eventViewportPoint(event) };
    interaction.setPointerCapture(event.pointerId); interaction.classList.add('is-panning');
  });
  interaction.addEventListener('pointermove', (event) => {
    if (event.pointerType === 'touch' && touchPoints.has(event.pointerId)) {
      touchPoints.set(event.pointerId, eventViewportPoint(event));
      if (pinch) { event.preventDefault(); applyPinch(); return; }
    }
    if (!pan || event.pointerId !== pan.pointerId || !mapInfo) return;
    const next = eventViewportPoint(event); const dx = next.x - pan.point.x; const dy = next.y - pan.point.y;
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
  const finishTouch = (event, cancelled = false) => {
    touchPoints.delete(event.pointerId);
    if (touchPoints.size >= 2) beginPinch();
    else if (touchPoints.size === 1 && !cancelled) {
      const [pointerId, point] = touchPoints.entries().next().value;
      pinch = undefined; pan = { pointerId, point }; interaction.classList.add('is-panning');
    } else { pinch = undefined; finishPan(); }
  };
  interaction.addEventListener('pointerup', (event) => { if (event.pointerType === 'touch') finishTouch(event); else finishPan(event); deferInteractionEnd(); });
  interaction.addEventListener('pointercancel', (event) => { if (event.pointerType === 'touch') finishTouch(event, true); else finishPan(event); if (!touchPoints.size) setInteractionActive(false); });
  interaction.addEventListener('lostpointercapture', (event) => {
    if (event.pointerType === 'touch') touchPoints.delete(event.pointerId);
    if (!touchPoints.size) { pinch = undefined; finishPan(event); setInteractionActive(false); }
  });
}
function drawRawImage(slot, message) {
  const width = Number(message.width); const height = Number(message.height); const encoding = String(message.encoding || '').toLowerCase(); const source = message.data;
  if (!width || !height || !source || !['rgb8', 'bgr8', 'rgba8', 'bgra8', 'mono8'].includes(encoding)) { setCameraState(slot, `暂不支持编码：${encoding || '未知'}`); return; }
  const channels = encoding === 'mono8' ? 1 : (encoding === 'rgb8' || encoding === 'bgr8' ? 3 : 4); const step = Number(message.step) || width * channels;
  if (source.byteLength < step * height) { setCameraState(slot, '图像数据不完整'); return; }
  const pixels = new Uint8Array(width * height * 4);
  for (let row = 0; row < height; row += 1) for (let column = 0; column < width; column += 1) {
    const from = row * step + column * channels; const to = (row * width + column) * 4;
    if (encoding === 'mono8') pixels[to] = pixels[to + 1] = pixels[to + 2] = source[from];
    else if (encoding === 'bgr8' || encoding === 'bgra8') { pixels[to] = source[from + 2]; pixels[to + 1] = source[from + 1]; pixels[to + 2] = source[from]; }
    else { pixels[to] = source[from]; pixels[to + 1] = source[from + 1]; pixels[to + 2] = source[from]; }
    pixels[to + 3] = channels === 4 ? source[from + 3] : 255;
  }
  presentCameraTexture(slot, createRgbaTexture(pixels, width, height), width, height);
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
    const width = bitmap.width; const height = bitmap.height;
    presentCameraTexture(slot, Texture.from(bitmap), width, height, bitmap);
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
async function initializePixiRenderer() {
  const host = $('mapWorld');
  if (!host || pixiInitialization) return pixiInitialization;
  pixiInitialization = (async () => {
    const app = new Application();
    await app.init({
      width: mapViewport.width,
      height: mapViewport.height,
      backgroundAlpha: 0,
      antialias: false,
      autoDensity: true,
      resolution: window.devicePixelRatio || 1,
    });
    // 原页面只在状态变化时合成。停掉 PixiJS 默认 ticker 后仍沿用既有的
    // rAF/节流边界，不能因引擎替换而空转重绘。
    app.ticker.stop();
    app.canvas.classList.add('pixi-map-canvas');
    app.canvas.setAttribute('aria-hidden', 'true');
    host.replaceChildren(app.canvas);
    pixiApp = app;
    pixiWorld = new Container();
    pixiMapLayer = new Container();
    pixiWallLayer = new Container();
    pixiCloudLayer = new Container();
    pixiWorld.addChild(pixiMapLayer, pixiWallLayer, pixiCloudLayer);
    app.stage.addChild(pixiWorld);
    pixiReady = true;
    renderStaticWorld();
    rebuildCloudRaster();
    scheduleMapDraw();
  })().catch((error) => {
    reportObservation('ERROR', `PixiJS 渲染器初始化失败：${error?.message || '未知错误'}`);
    throw error;
  });
  return pixiInitialization;
}
function queueCloudRender(frame) {
  if (!pixiReady) return false;
  // 单槽覆盖。新的扫描永远替代尚未提交的旧扫描，不能形成视觉或网络回放。
  pendingCloudFrame = frame;
  flushCloudRenderer();
  return true;
}
function flushCloudRenderer() {
  if (!pendingCloudFrame || !pixiReady) return;
  const delay = CLOUD_COMPOSITE_MIN_INTERVAL_MS - (performance.now() - lastCloudRenderAt);
  if (delay > 0) {
    if (!cloudRenderTimer) cloudRenderTimer = window.setTimeout(() => {
      cloudRenderTimer = undefined; flushCloudRenderer();
    }, delay);
    return;
  }
  const frame = pendingCloudFrame; pendingCloudFrame = undefined;
  lastCloudRenderAt = performance.now();
  if (frame.generation === mapGeneration) renderCloudPoints(frame.points);
  if (pendingCloudFrame) flushCloudRenderer();
}
function packCloudPoints(points) {
  const packed = new Float32Array(points.length * 2);
  for (let index = 0; index < points.length; index += 1) { packed[index * 2] = points[index].x; packed[index * 2 + 1] = points[index].y; }
  return packed;
}
function predictVehicleMotion(pose, seconds) {
  const horizon = Math.max(0, Math.min(MAX_VEHICLE_PREDICTION_MS / 1000, seconds));
  const rawVelocity = pose.velocity || { x: 0, y: 0 };
  const velocity = { x: Number(rawVelocity.x) || 0, y: Number(rawVelocity.y) || 0 };
  const yawRate = Number.isFinite(pose.yawRate) ? pose.yawRate : 0;
  let x = pose.position.x + velocity.x * horizon;
  let y = pose.position.y + velocity.y * horizon;
  // CTRV：速度主要沿车体前向、且正在转弯时按圆弧外推。低速/横移时退回
  // 笛卡尔恒速模型，避免定位噪声把静止车体画成小圆圈。
  const forwardSpeed = velocity.x * Math.cos(pose.yaw) + velocity.y * Math.sin(pose.yaw);
  if (Math.abs(forwardSpeed) >= VEHICLE_VELOCITY_DEADBAND_MPS && Math.abs(yawRate) >= 0.03) {
    const nextYaw = pose.yaw + yawRate * horizon;
    x = pose.position.x + forwardSpeed / yawRate * (Math.sin(nextYaw) - Math.sin(pose.yaw));
    y = pose.position.y - forwardSpeed / yawRate * (Math.cos(nextYaw) - Math.cos(pose.yaw));
  }
  return { position: { x, y }, yaw: normalizeAngle(pose.yaw + yawRate * horizon), velocity, yawRate, source: pose.source };
}
function renderedVehiclePoseInMap() {
  const target = vehiclePoseInMap();
  if (!target?.position) return undefined;
  const now = performance.now();
  // 预测窗口包含 ROS 源时间到浏览器的已测年龄及本显示帧等待时间。它不缓存
  // 历史样本，始终朝“现在”外推，因而不会用流畅换取额外显示延迟。
  const predictionSeconds = Math.min(MAX_VEHICLE_PREDICTION_MS / 1000, Math.max(0, now - Number(target.receivedAt || now)) / 1000 + (target.sourceAgeMs || 0) / 1000);
  const desired = predictVehicleMotion(target, predictionSeconds);
  if (!renderedVehiclePose || now - renderedVehicleAt > 1200
    || Math.hypot(desired.position.x - renderedVehiclePose.position.x, desired.position.y - renderedVehiclePose.position.y) > 2.5) {
    renderedVehiclePose = desired;
    renderedVehicleAt = now;
    return renderedVehiclePose;
  }
  // α-β 预测—校正：每个显示帧先按自身速度前推，再用最新真实观测的残差校正。
  // 比单纯低通更贴近实车，同时对定位的厘米级高频抖动保持稳定。
  const deltaSeconds = Math.min(0.08, Math.max(0.001, (now - renderedVehicleAt) / 1000));
  const predicted = predictVehicleMotion(renderedVehiclePose, deltaSeconds);
  const errorX = desired.position.x - predicted.position.x;
  const errorY = desired.position.y - predicted.position.y;
  const displacement = Math.hypot(errorX, errorY);
  const gain = displacement < VEHICLE_POSITION_DEADBAND_M ? 0.32 : ALPHA_BETA_POSITION_GAIN;
  renderedVehiclePose.position.x = predicted.position.x + errorX * gain;
  renderedVehiclePose.position.y = predicted.position.y + errorY * gain;
  const correctedVelocity = {
    x: predicted.velocity.x + errorX * ALPHA_BETA_VELOCITY_GAIN / deltaSeconds,
    y: predicted.velocity.y + errorY * ALPHA_BETA_VELOCITY_GAIN / deltaSeconds,
  };
  renderedVehiclePose.velocity = {
    x: correctedVelocity.x * 0.28 + (desired.velocity.x || 0) * 0.72,
    y: correctedVelocity.y * 0.28 + (desired.velocity.y || 0) * 0.72,
  };
  renderedVehiclePose.yaw = normalizeAngle(predicted.yaw + normalizeAngle(desired.yaw - predicted.yaw) * gain);
  renderedVehiclePose.yawRate = desired.yawRate || 0;
  renderedVehiclePose.source = desired.source;
  renderedVehicleAt = now;
  return renderedVehiclePose;
}
function requestVehicleAnimation() {
  if (vehicleAnimationFrame || document.hidden || !vehiclePoseInMap()?.position) return;
  const render = (frameAt) => {
    vehicleAnimationFrame = undefined;
    if (document.hidden || !lastMapLayout) return;
    if (clientPerformance.lastVehicleFrameAt) {
      const interval = frameAt - clientPerformance.lastVehicleFrameAt;
      clientPerformance.vehicleFrameIntervalMs = clientPerformance.vehicleFrameIntervalMs ? clientPerformance.vehicleFrameIntervalMs * 0.85 + interval * 0.15 : interval;
      if (interval > 34) clientPerformance.vehicleLongFrames += 1;
    }
    clientPerformance.lastVehicleFrameAt = frameAt; clientPerformance.vehicleFrames += 1;
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
  return centerPending;
}
function requestFollowAnimation() {
  // 每次轻量位姿到达只申请一次相机变换。PixiJS 仅更新世界容器矩阵，
  // 不重绘地图纹理或点云几何，因而不会抢占后续位姿消息。
  if (!mapInfo || document.hidden || !hasPendingFollowAdjustment()) return;
  scheduleMapDraw();
}

function currentMapLayout() {
  if (!mapInfo) return undefined;
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
    const fullMapScale = Math.min(mapViewport.width / (mapInfo.width * mapInfo.resolution), mapViewport.height / (mapInfo.height * mapInfo.resolution)) * 0.92;
    mapView.pixelsPerMeter = overviewUntilMovement
      // 初始概览必须完整容纳地图；不能套用近景视图的最小缩放限制，
      // 否则在大地图上仍会出现边缘被裁切的“概览”。
      ? Math.max(1, fullMapScale)
      : Math.max(MIN_PIXELS_PER_METER, Math.min(MAX_PIXELS_PER_METER, mapViewport.width / DEFAULT_VIEW_METERS));
  }
  const ratio = mapInfo.resolution * mapView.pixelsPerMeter;
  const width = mapInfo.width * ratio; const height = mapInfo.height * ratio;
  return {
    ratio, width, height, pixelsPerMeter: mapView.pixelsPerMeter, center: mapView.center, vehicle,
    viewportWidth: mapViewport.width, viewportHeight: mapViewport.height,
    // 地图必须稳定保持其原始 map 坐标朝向。定位航向的零点不一定与地图北向
    // 完全一致，若在进入页面时旋转地图，会让静止小车也看到整张地图倾斜。
    rotation: 0,
    left: mapViewport.width / 2 + (mapInfo.origin.x - mapView.center.x) * mapView.pixelsPerMeter,
    top: mapViewport.height / 2 - (mapInfo.origin.y + mapInfo.height * mapInfo.resolution - mapView.center.y) * mapView.pixelsPerMeter,
  };
}
function scheduleMapDraw(interactive = false) {
  // 拖拽/缩放只改变 CSS 矩阵，必须在下一合成帧执行，不能被实时数据的 60 FPS
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
  if (!mapInfo || !mapTexture || !pixiReady) return;
  // 地图纹理、虚拟墙和点云均由 PixiJS 的同一世界容器渲染。此处只更新
  // GPU 相机矩阵，不重新上传静态地图纹理或重建点云几何。
  const layout = currentMapLayout();
  lastMapLayout = layout;
  pixiWorld.position.set(layout.left, layout.top);
  pixiWorld.scale.set(layout.ratio, layout.ratio);
  pixiWorld.rotation = layout.rotation;
  syncVehicleLayer(layout.vehicle, layout);
  pixiApp.render();
}

function renderStaticWorld() {
  if (!mapInfo || !mapTexture || !pixiReady) return;
  pixiMapSprite?.destroy();
  pixiMapLayer.removeChildren();
  pixiMapTexture = mapTexture;
  pixiMapTexture.source.scaleMode = 'nearest';
  pixiMapSprite = new Sprite(pixiMapTexture);
  pixiMapSprite.width = mapInfo.width;
  pixiMapSprite.height = mapInfo.height;
  pixiMapLayer.addChild(pixiMapSprite);
  pixiWallLayer.removeChildren().forEach((child) => child.destroy());
  const walls = new Graphics();
  const lineWidth = Math.max(1, 0.06 / mapInfo.resolution);
  for (const wall of virtualWalls) {
    const points = Array.isArray(wall.points) ? wall.points : [];
    if (points.length < 2) continue;
    points.forEach((point, index) => {
      const world = wall.coordinate_mode === 'image_relative'
        ? { x: mapInfo.origin.x + Number(point.x), y: mapInfo.origin.y + Number(point.y) }
        : { x: Number(point.x), y: Number(point.y) };
      const targetX = (world.x - mapInfo.origin.x) / mapInfo.resolution;
      const targetY = mapInfo.height - (world.y - mapInfo.origin.y) / mapInfo.resolution;
      if (index === 0) walls.moveTo(targetX, targetY); else walls.lineTo(targetX, targetY);
    });
  }
  walls.stroke({ color: 0xd63142, width: lineWidth, cap: 'round', join: 'round' });
  pixiWallLayer.addChild(walls);
  pixiApp.render();
}
function renderCloudPoints(packedPoints) {
  if (!pixiReady || !mapInfo) return;
  pixiCloudLayer.removeChildren().forEach((child) => child.destroy());
  if (!packedPoints?.length) { pixiApp.render(); return; }
  const points = new Graphics();
  for (let index = 0; index < packedPoints.length; index += 2) {
    const x = (packedPoints[index] - mapInfo.origin.x) / mapInfo.resolution;
    const y = mapInfo.height - (packedPoints[index + 1] - mapInfo.origin.y) / mapInfo.resolution;
    if (x >= 0 && x < mapInfo.width && y >= 0 && y < mapInfo.height) points.rect(x - 0.35, y - 0.35, 0.7, 0.7);
  }
  points.fill(0x8058ff);
  pixiCloudLayer.addChild(points);
  pixiApp.render();
}
function syncVehicleLayer(vehicle, layout) {
  const element = $('vehicleLayer');
  if (!vehicle?.position || !mapInfo || !Number.isFinite(Number(vehicle.position.x)) || !Number.isFinite(Number(vehicle.position.y))) { element.hidden = true; return; }
  const nativeX = (vehicle.position.x - mapInfo.origin.x) / mapInfo.resolution;
  const nativeY = mapInfo.height - (vehicle.position.y - mapInfo.origin.y) / mapInfo.resolution;
  const baseX = layout.left + nativeX * layout.ratio;
  const baseY = layout.top + nativeY * layout.ratio;
  const centerX = layout.viewportWidth / 2; const centerY = layout.viewportHeight / 2;
  const cosine = Math.cos(layout.rotation); const sine = Math.sin(layout.rotation);
  const x = centerX + cosine * (baseX - centerX) - sine * (baseY - centerY);
  const y = centerY + sine * (baseX - centerX) + cosine * (baseY - centerY);
  const length = Math.max(0.2, Number(vehicleModel.length_m) || 1.0) * layout.pixelsPerMeter;
  const width = Math.max(0.15, Number(vehicleModel.width_m) || 0.68) * layout.pixelsPerMeter;
  element.hidden = false;
  if (element.style.width !== `${width}px`) element.style.width = `${width}px`;
  if (element.style.height !== `${length}px`) element.style.height = `${length}px`;
  // 车体每帧只写 transform，进入独立合成层。禁止写 left/top，否则浏览器可能
  // 重新计算绝对定位布局，形成“数据很新但视觉一卡一卡”的假延迟。
  // ROS yaw 以 +X 为零、逆时针增加；屏幕 Y 轴向下而车体图标默认朝上，故须
  // 转换为 pi/2 - yaw。只旋转车体，底图、点云和虚拟墙始终保持 map 朝向。
  const localYaw = Math.PI / 2 - vehicle.yaw;
  const transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%) rotate(${localYaw}rad)`;
  if (element.style.transform !== transform) element.style.transform = transform;
}
function vehiclePoseInMap() {
  // map->odom->base_* 通常比 /amcl_pose 频率高得多。优先使用最近 TF，才能让
  // 车体连续跟随实际运动；TF 短暂缺失时自动回退至定位话题，不改变安全边界。
  if (tfVehiclePose) {
    const maximumAge = tfVehiclePose.source === 'live' ? LIVE_POSE_FALLBACK_MS : 1500;
    if (performance.now() - tfVehiclePose.receivedAt < maximumAge) return tfVehiclePose;
  }
  if (pose?.position) return { ...pose, yaw: yawOf(pose.orientation), source: 'pose' };
  return undefined;
}
function armTfFallback() {
  // 位姿流可达 60 Hz。不能每帧 clear/setTimeout，否则会不断制造定时器任务，
  // 在 GC 或浏览器调度时表现为周期性的轻微闪顿。始终只保留一个到期检查。
  if (tfFallbackTimer) return;
  const check = () => {
    tfFallbackTimer = undefined;
    const age = livePoseUpdatedAt ? Math.max(0, performance.now() - livePoseUpdatedAt) : Infinity;
    if (age < LIVE_POSE_FALLBACK_MS) {
      tfFallbackTimer = window.setTimeout(check, Math.max(1, LIVE_POSE_FALLBACK_MS - age));
      return;
    }
    requestStaticTransforms(); subscribeVisualizationStream('tf', tfChannel);
  };
  const age = livePoseUpdatedAt ? Math.max(0, performance.now() - livePoseUpdatedAt) : 0;
  tfFallbackTimer = window.setTimeout(check, Math.max(1, LIVE_POSE_FALLBACK_MS - age));
}
function leaveOverviewAfterMovement(position) {
  if (!overviewUntilMovement || !position) return;
  if (!overviewPoseAnchor) { overviewPoseAnchor = { x: position.x, y: position.y }; return; }
  if (Math.hypot(position.x - overviewPoseAnchor.x, position.y - overviewPoseAnchor.y) < INITIAL_OVERVIEW_MOVEMENT_M) return;
  overviewUntilMovement = false;
  mapView.pixelsPerMeter = undefined;
  mapView.followOffset = { x: 0, y: 0 };
}
function sourcePoseAge(message) {
  const stamp = message?.header?.stamp;
  const seconds = Number(stamp?.sec); const nanoseconds = Number(stamp?.nanosec);
  if (!Number.isFinite(seconds) || !Number.isFinite(nanoseconds) || seconds <= 0) return 0;
  const age = Date.now() - (seconds * 1000 + nanoseconds / 1e6);
  // ROS 时间可能使用仿真时钟或与浏览器主机不同步；仅接纳可信的正向年龄。
  return age >= 0 && age <= 2000 ? age : 0;
}
function stabilizeStationaryVehicle(position, yaw, now) {
  const raw = { position: { x: Number(position.x), y: Number(position.y) }, yaw };
  if (vehicleStillAnchor) {
    const distance = Math.hypot(raw.position.x - vehicleStillAnchor.position.x, raw.position.y - vehicleStillAnchor.position.y);
    const yawDelta = Math.abs(normalizeAngle(raw.yaw - vehicleStillAnchor.yaw));
    if (distance < VEHICLE_STILL_RELEASE_DISTANCE_M && yawDelta < VEHICLE_STILL_RELEASE_YAW_RAD) return { ...vehicleStillAnchor, stationary: true };
    vehicleStillAnchor = undefined;
    vehicleStillCandidate = raw;
    vehicleStillCandidateAt = now;
    return { ...raw, stationary: false };
  }
  if (!vehicleStillCandidate) {
    vehicleStillCandidate = raw;
    vehicleStillCandidateAt = now;
    return { ...raw, stationary: false };
  }
  const distance = Math.hypot(raw.position.x - vehicleStillCandidate.position.x, raw.position.y - vehicleStillCandidate.position.y);
  const yawDelta = Math.abs(normalizeAngle(raw.yaw - vehicleStillCandidate.yaw));
  if (distance >= VEHICLE_STILL_HOLD_DISTANCE_M || yawDelta >= VEHICLE_STILL_HOLD_YAW_RAD) {
    vehicleStillCandidate = raw;
    vehicleStillCandidateAt = now;
    return { ...raw, stationary: false };
  }
  if (now - vehicleStillCandidateAt >= VEHICLE_STILL_SETTLE_MS) vehicleStillAnchor = vehicleStillCandidate;
  return vehicleStillAnchor ? { ...vehicleStillAnchor, stationary: true } : { ...raw, stationary: false };
}
function updateLivePose(message) {
  const position = message?.pose?.position;
  const orientation = message?.pose?.orientation;
  if (!position || !orientation || !Number.isFinite(Number(position.x)) || !Number.isFinite(Number(position.y))) return;
  // C++ 已完成 map->base 的查找；浏览器只处理一个极小 PoseStamped，避免解析完整 /tf。
  livePoseUpdatedAt = performance.now();
  clientPerformance.poseApplied += 1;
  vehicleUpdatedAt = livePoseUpdatedAt;
  // 轻量流恢复后立即卸载兼容 TF，避免浏览器继续接收大批量变换消息。
  if (visualizationStreams.tf.subscriptionId !== undefined) stopStreamProbe('tf');
  const previous = tfVehiclePose?.source === 'live' ? tfVehiclePose : undefined;
  const elapsedSeconds = previous ? (livePoseUpdatedAt - previous.receivedAt) / 1000 : 0;
  const stabilized = stabilizeStationaryVehicle(position, yawOf(orientation), livePoseUpdatedAt);
  const stablePosition = stabilized.position;
  const yaw = stabilized.yaw;
  let velocity = { x: 0, y: 0 };
  let yawRate = 0;
  if (!stabilized.stationary && elapsedSeconds >= 0.01 && elapsedSeconds <= 0.3) {
    const vx = (stablePosition.x - previous.position.x) / elapsedSeconds;
    const vy = (stablePosition.y - previous.position.y) / elapsedSeconds;
    // 室内小车的显示预测绝不接受异常跳点或不现实的高速值。
    if (Math.hypot(vx, vy) <= 3.0) velocity = { x: vx, y: vy };
    const candidateYawRate = normalizeAngle(yaw - previous.yaw) / elapsedSeconds;
    if (Math.abs(candidateYawRate) <= MAX_VEHICLE_YAW_RATE_RADPS) yawRate = candidateYawRate;
  }
  const measuredAge = sourcePoseAge(message);
  livePoseSourceAgeMs = measuredAge > 0 ? livePoseSourceAgeMs * 0.82 + measuredAge * 0.18 : livePoseSourceAgeMs * 0.82;
  tfVehiclePose = { position: stablePosition, orientation, yaw, source: 'live', receivedAt: livePoseUpdatedAt, velocity, yawRate, sourceAgeMs: livePoseSourceAgeMs };
  // 轻量位姿是当前性能路径；它也必须能驱动概览 -> 随车视图，不能依赖
  // /amcl_pose 恰好同时到达，否则小车会一直缩在大地图中，看似“消失”。
  leaveOverviewAfterMovement(stablePosition);
  armTfFallback();
  updateDiagnostics(); scheduleMapDraw(); requestFollowAnimation(); requestVehicleAnimation();
}
function scheduleLatestCloudPacket(reader, data) {
  clientPerformance.cloudPackets += 1;
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
  clientPerformance.posePackets += 1;
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
  // 诊断文字不需要随 TF 的十几 Hz 刷新；频繁修改 DOM 会与 PixiJS 渲染争用
  // 主线程，反而造成地图“跟不上”。重要状态可传 force 立即展示。
  if (!force && now - lastDiagnosticsAt < 500) return;
  lastDiagnosticsAt = now;
  const mapText = mapInfo ? `${mapInfo.width} × ${mapInfo.height} 地图` : '等待地图';
  const vehicle = vehiclePoseInMap();
  const inMap = vehicle?.position && mapInfo && vehicle.position.x >= mapInfo.origin.x && vehicle.position.x <= mapInfo.origin.x + mapInfo.width * mapInfo.resolution && vehicle.position.y >= mapInfo.origin.y && vehicle.position.y <= mapInfo.origin.y + mapInfo.height * mapInfo.resolution;
  const source = vehicle?.source === 'live' ? '实时位姿' : (vehicle?.source === 'tf' ? 'TF' : '定位');
  const poseText = vehicle ? (inMap ? `${source} x ${vehicle.position.x.toFixed(2)} · y ${vehicle.position.y.toFixed(2)} · 小车已绘制` : `${source}不在当前地图范围`) : '等待定位/TF';
  const cloudAge = cloud ? Math.max(0, (performance.now() - cloudUpdatedAt) / 1000) : 0;
  const cloudCount = cloud?.mapPointCount ?? cloud?.mapPoints?.length ?? 0;
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
    state.client?.unsubscribe(state.subscriptionId); state.subscriptions?.delete(state.subscriptionId); state.subscriptionId = undefined;
  }
  state.client = undefined; state.subscriptions = undefined;
}
function subscribeVisualizationStream(kind, channel, streamClient = client, streamReaders = readers, streamSubscriptions = subscriptions) {
  const state = visualizationStreams[kind]; if (!state || !channel || !streamClient || !streamReaders?.has(channel.id)) return;
  if (state.channel?.id === channel.id && state.client === streamClient && state.subscriptionId !== undefined) return;
  stopStreamProbe(kind); state.channel = channel;
  try {
    state.subscriptionId = streamClient.subscribe(channel.id);
    state.client = streamClient; state.subscriptions = streamSubscriptions;
    streamSubscriptions.set(state.subscriptionId, { topic: channel.topic, channelId: channel.id, visualizationKind: kind });
  } catch (error) {
    state.subscriptionId = undefined;
    // 不能让单个频道的订阅失败静默地表现为“等待点云”。诊断记录只包含
    // 话题和简短错误，不上传任何实时数据。
    reportObservation('WARNING', `实时流订阅失败：${channel.topic}；${error?.message || '未知错误'}`);
  }
}
function subscribeLivePoseStream() {
  // 专线短暂不可用时自动回退主连接，保留既有 TF watchdog 的兼容性；专线一旦
  // 广播到位姿通道，会立即替换主连接订阅，不会让两个连接重复解码同一位姿。
  if (poseClient && poseLaneChannel && poseReaders?.has(poseLaneChannel.id)) {
    subscribeVisualizationStream('livePose', poseLaneChannel, poseClient, poseReaders, poseSubscriptions);
  } else {
    subscribeVisualizationStream('livePose', livePoseChannel);
  }
}
function hasActiveCameraSubscription() {
  return ['A', 'B'].some((slot) => workspaceLayout?.[`camera${slot}`] && cameraSlots[slot].channelId);
}
function pauseCloudForCamera() {
  return Boolean(workspaceLayout?.cameraPriority && hasActiveCameraSubscription());
}
function activateVisualizationStreams() {
  const usePreprocessedStream = cloudTopic === LIVE_CLOUD_TOPIC && livePoseChannel;
  subscribeLivePoseStream();
  // 预处理流已经把点云投影至 map，且轻量位姿已由 C++ 计算，不再把完整 /tf
  // 送到浏览器。原始点云或轻量位姿暂不可用时，保留历史兼容回退链路。
  if (usePreprocessedStream) {
    stopStreamProbe('tf'); stopStaticTfSubscription();
    // advertise 并不代表轻量位姿已有数据；每次新位姿都会重置 watchdog，
    // 因而运行中的偶发断流也能迅速回退到兼容 TF 链路。
    armTfFallback();
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
function beginMapProbe() {
  // 正常行驶期间只创建一次 ROS /map 订阅。确认 map_server 已切图时，
  // reassertMapProbe() 才会进行一次定向重订阅以取得新 publisher 的瞬态栅格。
  if (mapProbeSubscriptionId !== undefined) return;
  if (!client || !mapChannel || !readers?.has(mapChannel.id)) return;
  try {
    mapProbeSubscriptionId = client.subscribe(mapChannel.id);
    subscriptions.set(mapProbeSubscriptionId, { topic: '/map', channelId: mapChannel.id, mapProbe: true });
  } catch (_) { /* Bridge 短暂不可用时由频道重新广播或页面重连恢复。 */ }
}
function reassertMapProbe() {
  // 不把重订阅放到定时器里：仅 active_map_id 确认变化才执行一次，避免静态
  // OccupancyGrid 在运行中反复进入浏览器主线程。
  stopMapProbeSubscription(); beginMapProbe();
}
function invalidateMapScopedCloud() {
  // map 坐标系在切图时会重置。丢弃旧图的待解码/待绘制扫描，并给渲染器加
  // generation 栅栏，杜绝上一张图的异步点云在新图就绪后闪现一帧。
  mapGeneration += 1;
  cloud = undefined; pendingCloudPacket = undefined; pendingCloudFrame = undefined;
  if (cloudRenderTimer) { window.clearTimeout(cloudRenderTimer); cloudRenderTimer = undefined; }
  renderCloudPoints();
}
function resetLiveWallRetry() {
  if (liveWallRetryTimer) { window.clearTimeout(liveWallRetryTimer); liveWallRetryTimer = undefined; }
  liveWallRetryCount = 0;
}
function scheduleLiveWallRetry(info, fingerprint) {
  if (liveWallRetryTimer || liveWallRetryCount >= LIVE_WALL_RETRY_DELAYS_MS.length) return;
  const delay = LIVE_WALL_RETRY_DELAYS_MS[liveWallRetryCount++];
  liveWallRetryTimer = window.setTimeout(() => {
    liveWallRetryTimer = undefined;
    // 地图已切换时不能把上一张图的异步补偿结果画到新图上。
    if (mapFingerprint !== fingerprint || !mapInfo) return;
    resolveLiveWalls(mapInfo, fingerprint, true);
  }, delay);
}
function updateMap(message) {
  const info = message.info; if (!info?.width || !info?.height || !message.data || !(info.resolution > 0)) return;
  const signature = mapSignature(info, message.data);
  const changed = signature !== mapFingerprint;
  mapFingerprint = signature;
  if (!changed && mapTexture) { $('mapEmpty').hidden = true; return; }
  // 切图时旧图坐标系的扫描绝不能投影到新图上；等待下一帧最新点云即可。
  invalidateMapScopedCloud();
  mapInfo = { width: info.width, height: info.height, resolution: info.resolution, origin: info.origin.position, frameId: normalizeFrame(message.header?.frame_id) || 'map' };
  // 地图本身由浏览器直连 Bridge 接收；只把必要元数据交给控制台解析同目录虚拟墙。
  // 地图切换才会调用一次，不上传栅格，不增加 ROS /map 订阅，也不持续扫描磁盘。
  resetLiveWallRetry();
  virtualWalls = []; wallStatus = '正在匹配当前地图的虚拟墙';
  resolveLiveWalls(mapInfo, signature);
  const pixels = new Uint8Array(info.width * info.height * 4);
  for (let row = 0; row < info.height; row += 1) for (let col = 0; col < info.width; col += 1) {
    const occupancy = message.data[(info.height - 1 - row) * info.width + col];
    const color = occupancy < 0 ? 174 : occupancy >= 65 ? 36 : 245;
    const index = (row * info.width + col) * 4; pixels[index] = color; pixels[index + 1] = color; pixels[index + 2] = color; pixels[index + 3] = 255;
  }
  mapTexture?.destroy(true); mapTexture = createRgbaTexture(pixels, info.width, info.height); $('mapEmpty').hidden = true; renderStaticWorld(); scheduleCloudRasterBuild(); updateDiagnostics(); scheduleMapDraw();
  activateVisualizationStreams();
}

async function resolveLiveWalls(info, fingerprint, retry = false) {
  if (resolvedWallFingerprint === fingerprint && !retry) return;
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
    if (layers.map_id) loadedMapId = layers.map_id;
    if (layers.matched) resetLiveWallRetry();
    else scheduleLiveWallRetry(info, fingerprint);
  } catch (_) {
    if (resolvedWallFingerprint === fingerprint) {
      virtualWalls = []; wallStatus = '虚拟墙读取失败'; scheduleLiveWallRetry(info, fingerprint);
    }
  }
  renderStaticWorld(); updateDiagnostics(); scheduleMapDraw();
}
function updatePose(message) {
  const source = message.pose?.pose; if (!source) return;
  const x = Number(source.position?.x); const y = Number(source.position?.y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) { pose = undefined; updateDiagnostics(); return; }
  pose = { position: { x, y }, orientation: source.orientation || { x: 0, y: 0, z: 0, w: 1 } };
  leaveOverviewAfterMovement(pose.position);
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
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength); const count = Math.floor(view.byteLength / step); const stride = Math.max(1, Math.ceil(count / POINT_LIMIT));
  const frameId = normalizeFrame(message.header?.frame_id);
  const isMapFrame = frameId && frameId === normalizeFrame(mapInfo?.frameId);
  // 预处理器的常规输出已在 map 坐标系。直接填充可转移的连续缓冲区，避免
  // 每帧创建数千个 {x,y,z} 对象、再复制为 Float32Array 所导致的周期性 GC。
  const packedMapPoints = isMapFrame ? new Float32Array(Math.ceil(count / stride) * 2) : undefined;
  const points = isMapFrame ? undefined : [];
  let pointOffset = 0;
  for (let index = 0; index < count; index += stride) {
    const offset = index * step; const x = view.getFloat32(offset + xOffset, !message.is_bigendian); const y = view.getFloat32(offset + yOffset, !message.is_bigendian); const z = view.getFloat32(offset + zOffset, !message.is_bigendian);
    if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z) && Math.abs(x) < 50 && Math.abs(y) < 50 && Math.abs(z) < 5) {
      if (packedMapPoints) { packedMapPoints[pointOffset] = x; packedMapPoints[pointOffset + 1] = y; pointOffset += 2; }
      else points.push({ x, y, z });
    }
  }
  cloudUpdatedAt = performance.now();
  const measuredAge = sourcePoseAge(message);
  liveCloudSourceAgeMs = measuredAge > 0 ? liveCloudSourceAgeMs * 0.7 + measuredAge * 0.3 : liveCloudSourceAgeMs * 0.7;
  cloud = isMapFrame
    ? { frameId, packedMapPoints: packedMapPoints.subarray(0, pointOffset), mapPointCount: pointOffset / 2 }
    : { frameId, points, mapPoints: [], mapPointCount: 0 };
  if (isMapFrame) recordCloudFrame(); else projectCloud(true);
  // 点云只更新独立 PixiJS 点云层；不能反向触发地图相机/车体同步，
  // 否则 10~12 Hz 点云会拖慢 30 Hz 位姿视图。
  updateDiagnostics();
}
function recordCloudFrame() {
  const now = performance.now();
  // 仅保留最新扫描。渲染间隔内覆盖尚未处理的帧，禁止形成延迟积压或透明拖影。
  const packedPoints = cloud.packedMapPoints || packCloudPoints(cloud.mapPoints || []);
  if (queueCloudRender({ receivedAt: now, points: packedPoints, generation: mapGeneration })) return;
  scheduleCloudRasterBuild();
}
function projectCloud(recordFrame = false) {
  if (!cloud || !mapInfo) return;
  const transform = transformToMap(cloud.frameId, mapInfo.frameId);
  if (!transform) { cloud.mapPoints = []; cloud.mapPointCount = 0; scheduleCloudRasterBuild(); return; }
  const cosine = Math.cos(transform.yaw); const sine = Math.sin(transform.yaw);
  cloud.mapPoints = (cloud.points || []).map((point) => ({ x: cosine * point.x - sine * point.y + transform.x, y: sine * point.x + cosine * point.y + transform.y }));
  cloud.mapPointCount = cloud.mapPoints.length;
  if (recordFrame) recordCloudFrame(); else scheduleCloudRasterBuild();
}
function scheduleCloudRasterBuild() {
  // 拖拽和缩放时点云并不需要重新投影；保留最新数据，交互结束后再一次性刷新。
  // 这样大点云的 PixiJS 图形更新不会抢走鼠标事件和 CSS 合成帧。
  if (mapInteractionActive) { cloudRasterPending = true; return; }
  if (cloudRasterQueued) return;
  cloudRasterQueued = true;
  requestAnimationFrame(() => {
    cloudRasterQueued = false;
    rebuildCloudRaster();
  });
}
function rebuildCloudRaster() {
  const packedPoints = cloud?.packedMapPoints;
  const mapPoints = cloud?.mapPoints;
  if (!mapInfo) { renderCloudPoints(); return; }
  renderCloudPoints(packedPoints || packCloudPoints(mapPoints || []));
}
async function refreshActiveMap(observation) {
  // active_map.json 由轨迹记录器在确认真实 /map 后写入；它是切图的轻量可靠
  // 信号。直接 /map 更新仍优先显示原始栅格，这里仅在其缺席时立即回退缓存图。
  const mapId = observation.active_map_id;
  if (!mapId || mapId === loadedMapId || mapId === requestedActiveMapId) return;
  requestedActiveMapId = mapId;
  try {
    const layers = await request(`/api/observation/maps/${encodeURIComponent(mapId)}/layers`);
    virtualWalls = Array.isArray(layers.virtual_walls) ? layers.virtual_walls : []; loadedWallMapId = mapId;
    // 新的 active_map_id 已由运行时确认；对 /map 定向重订阅一次即可请求新
    // publisher 的 TRANSIENT_LOCAL 栅格，后续仍保持单一订阅。
    reassertMapProbe();
    loadCachedMap(mapId, layers.map);
  } catch (_) {
    // 网络短暂失败不能把这次切图永久标为“已处理”；下一次轻量标记检查会
    // 重试，但不会在请求仍进行时重复触发 /map 重订阅。
    requestedActiveMapId = undefined;
    virtualWalls = []; loadedWallMapId = mapId;
  }
  updateDiagnostics(); scheduleMapDraw();
}
function loadCachedMap(mapId, metadata) {
  if (mapId === loadedMapId || !metadata?.width || !metadata?.height || !(metadata.resolution > 0) || !Array.isArray(metadata.origin)) return;
  loadedMapId = mapId;
  const image = new Image();
  image.decoding = 'async';
  image.onload = () => {
    if (loadedMapId !== mapId) return;
    invalidateMapScopedCloud();
    mapInfo = {
      width: Number(metadata.width), height: Number(metadata.height), resolution: Number(metadata.resolution),
      origin: { x: Number(metadata.origin[0]) || 0, y: Number(metadata.origin[1]) || 0 }, frameId: normalizeFrame(metadata.frame_id) || 'map',
    };
    mapTexture?.destroy(true); mapTexture = Texture.from(image); mapFingerprint = `cache:${mapId}`; $('mapEmpty').hidden = true;
    // 进入观测页且车辆尚未提供定位时，优先展示完整地图；运行中切图则延续随车视角。
    if (!vehiclePoseInMap()?.position) {
      overviewUntilMovement = true; overviewPoseAnchor = undefined; mapView.pixelsPerMeter = undefined;
      mapView.center = undefined; mapView.followOffset = { x: 0, y: 0 };
    }
    renderStaticWorld(); scheduleCloudRasterBuild(); updateDiagnostics(); scheduleMapDraw();
  };
  image.onerror = () => {
    if (loadedMapId === mapId) { loadedMapId = undefined; setText('mapDiagnostics', '当前地图缓存读取失败；请在测试任务中重新开启轨迹记录。'); }
  };
  image.src = `/api/observation/maps/${encodeURIComponent(mapId)}/preview.png`;
}

function connectPoseLane(url) {
  const ws = new WebSocket(url, [FOXGLOVE_BRIDGE_SUBPROTOCOL]); ws.binaryType = 'arraybuffer';
  poseClient = new FoxgloveClient({ ws }); poseReaders = new Map(); poseSubscriptions = new Map();
  poseClient.on('open', () => {
    reportObservation('INFO', `位姿专线已连接：${url}`);
    if (mapInfo) activateVisualizationStreams();
  });
  poseClient.on('error', (error) => {
    // 主连接仍可消费位姿/TF；专线故障不应中断实时观测页面。
    reportObservation('WARNING', `位姿专线连接异常：${error.message || url}；将使用兼容链路`);
  });
  poseClient.on('close', (event) => {
    const wasActive = visualizationStreams.livePose.client === poseClient;
    poseLaneChannel = undefined; poseReaders = undefined; poseSubscriptions = undefined; poseClient = undefined;
    reportObservation('WARNING', `位姿专线已关闭（代码 ${event.code || '未知'}）；将使用兼容链路`);
    if (wasActive && mapInfo) activateVisualizationStreams();
  });
  poseClient.on('advertise', (channels) => channels.forEach((channel) => {
    if (channel.topic !== LIVE_POSE_TOPIC) return;
    try {
      poseReaders.set(channel.id, new MessageReader(parse(channel.schema, { ros2: true })));
      poseLaneChannel = channel;
      // 不依赖地图先到达。部分 Bridge 会先广播轻量频道、后发送 /map；若在
      // 此处等待 mapInfo，后续地图重放缺失时页面将永远没有位姿订阅。
      subscribeLivePoseStream();
      if (mapInfo) activateVisualizationStreams();
    } catch (error) { reportObservation('WARNING', `位姿专线频道解析失败：${error?.message || '未知错误'}`); }
  }));
  poseClient.on('unadvertise', (channelIds) => {
    if (!channelIds.includes(poseLaneChannel?.id)) return;
    poseLaneChannel = undefined;
    if (mapInfo) activateVisualizationStreams();
  });
  poseClient.on('message', ({ subscriptionId, data }) => {
    const subscription = poseSubscriptions?.get(subscriptionId); const reader = poseReaders?.get(subscription?.channelId);
    if (subscription?.topic === LIVE_POSE_TOPIC && reader) scheduleLatestPosePacket(reader, data);
  });
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
      else if (channel.topic === LIVE_POSE_TOPIC) {
        livePoseChannel = channel;
        // 实时流不能以地图作为订阅前置条件。这样即使 /map 因切图、瞬态重放
        // 或网络时序晚到，车体和点云频道仍立即建立、只保留最新帧。
        subscribeLivePoseStream();
        if (mapInfo) activateVisualizationStreams();
      }
      else if (channel.topic === '/tf') { tfChannel = channel; if (mapInfo) activateVisualizationStreams(); }
      else if (channel.topic === '/tf_static') { staticTfChannel = channel; if (mapInfo) activateVisualizationStreams(); }
      else if (channel.topic === cloudTopic) {
        cloudChannel = channel;
        if (!pauseCloudForCamera()) subscribeVisualizationStream('cloud', cloudChannel);
        if (mapInfo) activateVisualizationStreams();
      }
    } catch (error) {
      reportObservation('WARNING', `Bridge 频道解析失败：${channel.topic}；${error?.message || '未知错误'}`);
    }
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
    if (topic === LIVE_POSE_TOPIC) { scheduleLatestPosePacket(reader, data); return; }
    const now = performance.now();
    if (topic === '/tf' && now - tfUpdatedAt < TF_MIN_INTERVAL_MS) return;
    try {
      const message = reader.readMessage(data);
      if (topic === '/map') updateMap(message); else if (topic === '/amcl_pose') updatePose(message); else { if (topic === '/tf') tfUpdatedAt = now; updateTransforms(message); }
    } catch (_) { /* 单帧损坏或字段变化不能中断观测。 */ }
  });
  // 连接在服务器端仍共享同一 ROS 图，但浏览器到 Bridge 使用第二条 TCP 流。
  // 因而点云或相机的瞬时大帧不会产生位姿的 TCP 队头阻塞。
  connectPoseLane(url);
}
async function main() {
  initializeTheme(); setupCameraSelectors(); setupWorkspace(); setupMapInteraction(); await initializePixiRenderer(); await Promise.all(['A', 'B'].map(initializeCameraRenderer));
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
    cloudTopic = ready.bridge?.cloud_topic === LIVE_CLOUD_TOPIC ? LIVE_CLOUD_TOPIC : DEFAULT_LIVE_CLOUD_SOURCE_TOPIC;
    await refreshActiveMap(ready); connect(ready);
    window.setInterval(() => { reportClientMetrics(); request('/api/observation/heartbeat', { method: 'POST' }).then(refreshActiveMap).catch(() => {}); }, 5000);
    window.setInterval(() => { request('/api/observation/active-map').then(refreshActiveMap).catch(() => {}); }, ACTIVE_MAP_SYNC_MS);
  } catch (error) { setText('connectionState', '不可用'); setText('connectionDetail', error.message); reportObservation('ERROR', `实时观测初始化失败：${error.message}`); }
}
window.addEventListener('beforeunload', () => { stopRenderScheduling(); stopMapProbeSubscription(); stopVisualizationStreams(); poseClient?.close(); client?.close(); });
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopRenderScheduling();
  else if (mapInfo) scheduleMapDraw();
});
main();
