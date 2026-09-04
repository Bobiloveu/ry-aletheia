import {
  Application,
  BufferImageSource,
  Container,
  Graphics,
  Sprite,
  Texture,
} from "pixi.js";
import "../../autodrive_console/web/styles.css";
import "../../autodrive_console/web/refinement.css";
import "../../autodrive_console/web/page_views.css";
import "./liveObservation.css";
import "../../autodrive_console/web/app_shell.css";
import "../../autodrive_console/web/app_shell.js";

// Aletheia 专用遥测帧。地图仍从既有 HTTP 缓存读取；点云已经由小车端 C++
// 投影至 map，仅含紧凑 x/y float32；位姿仅含 x/y/yaw。没有 ROS CDR、TF 或
// 通用 ROS-Web 协议进入浏览器。
const TELEMETRY_MAGIC = "ALTM";
const TELEMETRY_HEADER_BYTES = 20;
const TELEMETRY_CLOUD = 1;
const TELEMETRY_POSE = 2;
const TELEMETRY_COSTMAP = 3;
// 3000 点足以保留室内墙面和门洞的结构感；仍在前端限频解析，避免以原始全量
// 点云的频率占用浏览器主线程。
const POINT_LIMIT = 3000;
// 实时观测只关心“现在”。页面短暂忙碌或网络抖动后，宁可跳过旧扫描也不能
// 按顺序补绘导致画面落后实车。两个队列均为单槽 latest-wins。
const CLOUD_PACKET_MAX_AGE_MS = 100;
// 点云保持 latest-wins，但不必与激光每一帧等速合成。8 Hz 已足够观察环境
// 结构，并避免频繁更新点云几何抢占车体 CSS 合成。
const CLOUD_COMPOSITE_MIN_INTERVAL_MS = 125;
// 位姿包远小于点云，但在浏览器刚完成一次地图合成时可能恰好错过 120 ms
// 窗口。保留 250 ms 仍是当前画面，不会形成历史回放，却能避免车体偶发断流。
const POSE_PACKET_MAX_AGE_MS = 250;
// 实车局部代价地图源约为低频状态流。五秒内保留最后一张有效图，TF 暂时不可用
// 或 source 暂无更新时不会闪烁；超时则主动隐藏，不能把旧障碍物误当成当前环境。
const COSTMAP_PACKET_MAX_AGE_MS = 5000;
const COSTMAP_META_BYTES = 20;
const COSTMAP_MAX_CELLS = 65535;
const LIVE_POSE_FALLBACK_MS = 450;
// 地图旋转、栅格缩放与高密度点云合成是最重的浏览器操作。数据接收可更快，
// 但 PixiJS 只按可见效果提交，避免每一帧 TF 都触发整图重绘。
// 地图世界层只更新 PixiJS 变换，不重新上传地图纹理或点云几何；因此可按显示器
// 刷新率合成，避免 30 FPS 相机跟随让车体看似一卡一顿。
const MAP_RENDER_INTERVAL_MS = 16;
// 地图源本身约为千级像素；限制到 CSS 像素级可避免在高 DPI 电脑上反复旋转
// 超采样的渲染目标，显著降低主视图卡顿，同时不压缩或修改原始地图数据。
// active_map.json 是地图缓存的轻量标记；点云、位姿重构不改变地图加载机制。
const ACTIVE_MAP_SYNC_MS = 1000;
const VIDEO_INPUT_READINESS_TIMEOUT_MS = 8000;
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
// 静止定位仍会有厘米级浮动。实车采样显示 map→base 的自然噪声可接近 2.7 cm
// 和 0.7°；先在显示输入处锁住这一区间，不能把每个 TF 微扰直接交给车体。
// 自动驾驶的正常低速位移会累积越过该阈值，随后由 α-β 显示层连续追上。
const STATIC_POSE_POSITION_HOLD_M = 0.03;
const STATIC_POSE_YAW_HOLD_RAD = 0.02;
const VEHICLE_POSITION_DEADBAND_M = 0.012;
const VEHICLE_VELOCITY_DEADBAND_MPS = 0.05;
const MAX_VEHICLE_PREDICTION_MS = 300;
const ALPHA_BETA_POSITION_GAIN = 0.72;
const ALPHA_BETA_VELOCITY_GAIN = 0.12;
const MAX_VEHICLE_YAW_RATE_RADPS = 2.8;
// 手机地图采用钛灰仪表底色：能量橙只服务机器人与当前焦点，深紫服务
// 实时激光点云，红色仅表示虚拟墙。色彩层级由数据语义决定，而不是装饰效果。
const MAP_PALETTE = {
  unknown: [216, 221, 227],
  free: [246, 247, 248],
  occupied: [105, 116, 126],
  gridMinor: 0xbac2c9,
  gridMajor: 0x8f9ba6,
  // 亮紫色点云与红色虚拟墙在浅色栅格上清晰分离；点尺寸保持原有标定值。
  cloud: 0x8b5cf6,
  virtualWall: 0xd63142,
};
// PC 保持原有高对比观测配色与无格栅画面。点云用更深、饱和度更高的紫色，
// 并将半径从 0.35 调至 0.52 px：大屏与缩放地图中能看清稀疏导航点，仍明显
// 小于手机端，不会遮蔽墙体细节；实际点数、几何边界和传输链路均不改变。
// 手机专用主题和米制格栅只在
// `html.mobile-console` 已由 setupMobileConsole 显式启用时参与渲染。
const DESKTOP_MAP_PALETTE = {
  unknown: [174, 174, 174],
  free: [245, 245, 245],
  occupied: [36, 36, 36],
  cloud: 0x6426d9,
  virtualWall: 0xd63142,
};
const $ = (id) => document.getElementById(id);
// 点云和位姿保持两条独立 Binary WebSocket。点云慢客户端只能阻塞自身 socket，
// 小车端和浏览器端的位姿链路均不复用该队列。
let cloudSocket;
let poseSocket;
let costmapSocket;
// 断网或网关短暂重启时，两条车端数据线独立重连；不重连另一条已经健康的线，
// 也不把任何历史帧保存在浏览器中。
let telemetryConnectionGeneration = 0;
const telemetryReconnectTimers = {
  cloud: undefined,
  pose: undefined,
  costmap: undefined,
};
const telemetryLaneOpen = { cloud: false, pose: false, costmap: false };
const telemetryLaneAttempts = { cloud: 0, pose: 0, costmap: 0 };
let cloudUpdatedAt = 0;
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
let pixiGridLayer;
let pixiCostmapLayer;
let pixiWallLayer;
let pixiCloudLayer;
let pixiMapSprite;
let pixiMapTexture;
let pixiCostmapSprite;
let pixiCostmapTexture;
let pixiCostmapPixels;
let pixiReady = false;
let pixiInitialization;
let metricGridSignature;
const mapViewport = { width: 1, height: 1 };
let pendingCloudPacket;
let cloudPacketQueued = false;
let pendingPosePacket;
let posePacketQueued = false;
let pendingCostmapPacket;
let costmapPacketQueued = false;
let costmapExpiryTimer;
let costmapUpdatedAt = 0;
let costmapVisible = true;
let costmap;
let tfVehiclePose;
let renderedVehiclePose;
let renderedVehicleAt = 0;
let livePoseSourceAgeMs = 0;
let liveCloudSourceAgeMs = 0;
let liveCostmapSourceAgeMs = 0;
const clientPerformance = {
  startedAt: performance.now(),
  posePackets: 0,
  poseApplied: 0,
  cloudPackets: 0,
  costmapPackets: 0,
  vehicleFrames: 0,
  vehicleLongFrames: 0,
  vehicleFrameIntervalMs: 0,
  lastVehicleFrameAt: 0,
};
let latestLiveMotion;
let cloud;
let virtualWalls = [];
let wallStatus = "等待虚拟墙匹配";
let loadedMapId;
let requestedActiveMapId;
// 工业相机不经过实时遥测：每张卡片都由 HTMLVideoElement 接收
// WHEP/WebRTC，再由 PixiJS Video Texture 合成。即便新增流失败，也不会影响
// 现有地图、点云或诊断图像订阅。
const webrtcPlayers = new Map();
let webrtcStatusTimer;
let webrtcVideoEnabled = false;
let webrtcToggleInFlight = false;
const webrtcStreamTogglesInFlight = new Set();
let webrtcConfiguredStreams = [];
let mobilePrimaryWebRtcStream;
let drawQueued = false;
let drawDeferredTimer;
let drawAnimationFrame;
let lastMapDrawAt = 0;
let lastMapLayout;
let vehicleAnimationFrame;
let mapInteractionActive = false;
let mapInteractionTimer;
let cloudRasterPending = false;
let vehicleModel = {
  id: "ry-standard",
  name: "RY 标准小车",
  length_m: 1.0,
  width_m: 0.68,
};
const mapView = {
  pixelsPerMeter: undefined,
  followVehicle: true,
  followOffset: { x: 0, y: 0 },
  center: undefined,
};
let overviewUntilMovement = true;
let overviewPoseAnchor;
let lastDiagnosticsAt = 0;
const MOBILE_VIEW_KEY = "ry-aletheia-mobile-view-v1";
const MOBILE_CONSOLE_QUERY = "(hover: none) and (pointer: coarse)";
const mobileConsoleMedia = window.matchMedia(MOBILE_CONSOLE_QUERY);
const mobileConsoleForced =
  window.location.pathname.startsWith("/m/") ||
  new URLSearchParams(window.location.search).get("mobile") === "1";
let mobileConsoleView = "map";
const activeObservationDiagnostics = new Set();
const videoWaitingSince = new Map();
let videoGatewayOfflineSince = 0;

function mobileConsoleEnabled() {
  return document.documentElement.classList.contains("mobile-console");
}
function mobileWebRtcPlaybackAllowed() {
  return !mobileConsoleEnabled() || mobileConsoleView === "camera";
}
function mirrorMobileConnection(id, value) {
  if (id === "connectionState") {
    setText("mobileConnectionState", value);
    const signal = $("mobileConnectionSignal");
    signal?.classList.toggle("online", value === "已连接");
    signal?.classList.toggle(
      "warning",
      value.includes("连接中") || value.includes("启动中"),
    );
  } else if (id === "connectionDetail")
    setText("mobileConnectionDetail", value);
}
function setText(id, value) {
  const target = $(id);
  if (target) target.textContent = value;
  if (id === "connectionState" || id === "connectionDetail")
    mirrorMobileConnection(id, value);
}
function request(url, options = {}) {
  return fetch(url, { cache: "no-store", ...options }).then(
    async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(body.error || `请求失败（HTTP ${response.status}）`);
      return body;
    },
  );
}
function reportObservation(level, message) {
  const body = JSON.stringify({
    level,
    message: String(message || "").slice(0, 800),
  });
  // 诊断日志是辅助功能：浏览器无法写入时不能反过来影响只读观测。
  fetch("/api/observation/client-log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  }).catch(() => {});
}
function reportObservationOnce(key, level, message) {
  if (activeObservationDiagnostics.has(key)) return;
  activeObservationDiagnostics.add(key);
  reportObservation(level, message);
}
function resolveObservationDiagnostic(key, message) {
  if (!activeObservationDiagnostics.delete(key)) return;
  reportObservation("INFO", message);
}
function reportClientMetrics() {
  const now = performance.now();
  const elapsedSeconds = Math.max(
    0.001,
    (now - clientPerformance.startedAt) / 1000,
  );
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
    costmap_packet_rate_hz: clientPerformance.costmapPackets / elapsedSeconds,
    costmap_source_age_ms: liveCostmapSourceAgeMs,
  });
  fetch("/api/observation/client-metrics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  }).catch(() => {});
  clientPerformance.startedAt = now;
  clientPerformance.posePackets = 0;
  clientPerformance.poseApplied = 0;
  clientPerformance.cloudPackets = 0;
  clientPerformance.costmapPackets = 0;
  clientPerformance.vehicleFrames = 0;
  clientPerformance.vehicleLongFrames = 0;
}
function normalizeFrame(value) {
  return String(value || "").replace(/^\/+|\/+$/g, "");
}
function yawOf(quaternion = {}) {
  const { x = 0, y = 0, z = 0, w = 1 } = quaternion;
  return Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
}

function initializeTheme() {
  const key = "ry-aletheia-theme";
  const apply = () => {
    const light = localStorage.getItem(key) === "light";
    document.body.classList.toggle("theme-light", light);
    document.documentElement.style.colorScheme = light ? "light" : "dark";
  };
  document.querySelector(".mark")?.addEventListener("click", () => {
    localStorage.setItem(
      key,
      document.body.classList.contains("theme-light") ? "dark" : "light",
    );
    apply();
  });
  apply();
}
function updateMobileViewport() {
  if (!mobileConsoleEnabled()) return;
  const viewport = window.visualViewport;
  const width = Math.round(viewport?.width || window.innerWidth);
  const height = Math.round(viewport?.height || window.innerHeight);
  document.documentElement.style.setProperty(
    "--mobile-viewport-width",
    `${width}px`,
  );
  document.documentElement.style.setProperty(
    "--mobile-viewport-height",
    `${height}px`,
  );
  document.documentElement.classList.toggle("mobile-portrait", height >= width);
  if (mapInfo) scheduleMapDraw(true);
}
function setupMobileZoomPolicy() {
  const insideMap = (target) =>
    target instanceof Element && Boolean(target.closest(".local-map-wrap"));
  // Safari 的 gesture* 事件独立于 Pointer Events。始终阻止浏览器缩放，地图
  // 自己通过双 Pointer 的距离和中点完成米制视图缩放，不改变整个页面比例。
  for (const name of ["gesturestart", "gesturechange", "gestureend"]) {
    document.addEventListener(name, (event) => event.preventDefault(), {
      passive: false,
    });
  }
  document.addEventListener(
    "touchmove",
    (event) => {
      if (event.touches.length > 1 && !insideMap(event.target))
        event.preventDefault();
    },
    { passive: false, capture: true },
  );
  // 触控板捏合通常表现为 ctrl+wheel；地图外禁止页面缩放，地图内交给 onWheel。
  window.addEventListener(
    "wheel",
    (event) => {
      if (event.ctrlKey && !insideMap(event.target)) event.preventDefault();
    },
    { passive: false, capture: true },
  );
}
function setMobileConsoleView(view, persist = true) {
  if (!mobileConsoleEnabled() || !["map", "camera"].includes(view)) return;
  mobileConsoleView = view;
  document.documentElement.dataset.mobileView = view;
  document.querySelectorAll("[data-mobile-view-target]").forEach((button) => {
    const active = button.dataset.mobileViewTarget === view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  if (persist) localStorage.setItem(MOBILE_VIEW_KEY, view);
  if (view === "map") {
    for (const state of webrtcPlayers.values())
      closeWebRtcPlayer(state, "相机页未显示，浏览器解码已暂停。");
    if (mapInfo) scheduleMapDraw(true);
  } else {
    stopRenderScheduling();
    refreshWebRtcVideoStatus();
  }
}
function setupMobileConsole() {
  // 真实手机由粗指针能力判定；?mobile=1 只用于工程视觉验收，不改变生产默认。
  const mobile = mobileConsoleForced || mobileConsoleMedia.matches;
  if (!mobile) return;
  document.documentElement.classList.add("mobile-console");
  const savedView = localStorage.getItem(MOBILE_VIEW_KEY);
  setMobileConsoleView(savedView === "camera" ? "camera" : "map", false);
  setupMobileZoomPolicy();
  updateMobileViewport();
  document
    .querySelectorAll("[data-mobile-view-target]")
    .forEach((button) =>
      button.addEventListener("click", () =>
        setMobileConsoleView(button.dataset.mobileViewTarget),
      ),
    );
  window.addEventListener("resize", updateMobileViewport, { passive: true });
  window.visualViewport?.addEventListener("resize", updateMobileViewport, {
    passive: true,
  });
  window.visualViewport?.addEventListener("scroll", updateMobileViewport, {
    passive: true,
  });
  screen.orientation?.addEventListener?.("change", updateMobileViewport);
}
function createRgbaTexture(pixels, width, height) {
  return new Texture({
    source: new BufferImageSource({
      resource: pixels,
      width,
      height,
      format: "rgba8unorm",
    }),
  });
}
function clearCostmapRenderer() {
  pixiCostmapSprite?.destroy();
  pixiCostmapSprite = undefined;
  pixiCostmapTexture?.destroy(true);
  pixiCostmapTexture = undefined;
  pixiCostmapPixels = undefined;
  pixiCostmapLayer?.removeChildren();
}
function costmapIsCurrent() {
  return (
    costmap &&
    performance.now() - costmapUpdatedAt <= COSTMAP_PACKET_MAX_AGE_MS
  );
}
function costmapColor(cell, pixels, offset) {
  // 0 表示自由区，255 是 ROS 的 unknown(-1)：两者都不覆盖静态地图。局部代价
  // 只强调会影响当前导航的区域，不以整块半透明底色抢占虚拟墙/点云的视觉层级。
  if (cell === 0 || cell === 255) {
    pixels[offset + 3] = 0;
    return;
  }
  // 冷暖风险分级：低代价从冷蓝起步，经黄色过渡到橙色；致命障碍保持高对比红。
  // 这样紫色仍专属于点云、红线仍专属于虚拟墙，操作者不会把三种信息混为一层。
  if (cell >= 254) {
    pixels[offset] = 220;
    pixels[offset + 1] = 38;
    pixels[offset + 2] = 38;
    pixels[offset + 3] = 192;
    return;
  }
  if (cell === 253) {
    pixels[offset] = 249;
    pixels[offset + 1] = 115;
    pixels[offset + 2] = 22;
    pixels[offset + 3] = 176;
    return;
  }
  if (cell <= 126) {
    const intensity = cell / 126;
    // #38bdf8 → #facc15：低代价冷蓝，中代价黄色。
    pixels[offset] = Math.round(56 + intensity * 194);
    pixels[offset + 1] = Math.round(189 + intensity * 15);
    pixels[offset + 2] = Math.round(248 - intensity * 227);
    pixels[offset + 3] = Math.round(56 + intensity * 72);
    return;
  }
  if (cell <= 252) {
    const intensity = (cell - 126) / 126;
    // #facc15 → #f97316：中代价黄色，高代价橙色。
    pixels[offset] = Math.round(250 - intensity);
    pixels[offset + 1] = Math.round(204 - intensity * 89);
    pixels[offset + 2] = Math.round(21 + intensity);
    pixels[offset + 3] = Math.round(128 + intensity * 32);
  }
}
function renderCostmap() {
  if (
    !pixiReady ||
    !pixiCostmapLayer ||
    !mapInfo ||
    !costmapVisible ||
    mobileConsoleEnabled() ||
    !costmapIsCurrent()
  ) {
    clearCostmapRenderer();
    return;
  }
  const { width, height, cells, resolution, origin } = costmap;
  const dimensionsChanged =
    !pixiCostmapPixels ||
    pixiCostmapPixels.length !== width * height * 4;
  if (dimensionsChanged) {
    clearCostmapRenderer();
    pixiCostmapPixels = new Uint8Array(width * height * 4);
    pixiCostmapTexture = createRgbaTexture(pixiCostmapPixels, width, height);
    pixiCostmapSprite = new Sprite(pixiCostmapTexture);
    // ROS OccupancyGrid 的 data[0] 是左下角；Pixi texture 的 y=0 是上方。
    // 逐行反写色彩 buffer 后，将 sprite 的下沿锚定到 grid 原点，即可在 y-down
    // 的地图像素坐标内正确应用 map 坐标系 yaw。
    pixiCostmapSprite.anchor.set(0, 1);
    pixiCostmapLayer.addChild(pixiCostmapSprite);
  }
  for (let sourceY = 0; sourceY < height; sourceY += 1) {
    const textureY = height - sourceY - 1;
    for (let x = 0; x < width; x += 1) {
      costmapColor(cells[sourceY * width + x], pixiCostmapPixels, (textureY * width + x) * 4);
    }
  }
  pixiCostmapTexture.source.update();
  const mapScale = resolution / mapInfo.resolution;
  pixiCostmapSprite.width = width * mapScale;
  pixiCostmapSprite.height = height * mapScale;
  pixiCostmapSprite.position.set(
    (origin.x - mapInfo.origin.x) / mapInfo.resolution,
    mapInfo.height - (origin.y - mapInfo.origin.y) / mapInfo.resolution,
  );
  pixiCostmapSprite.rotation = -origin.yaw;
}
function scheduleCostmapExpiry() {
  window.clearTimeout(costmapExpiryTimer);
  costmapExpiryTimer = window.setTimeout(() => {
    if (!costmapIsCurrent()) {
      renderCostmap();
      updateDiagnostics(true);
      if (!document.hidden) scheduleMapDraw(true);
    }
  }, COSTMAP_PACKET_MAX_AGE_MS + 20);
}
function setWebRtcGatewayState(online, detail) {
  const badge = $("webrtcGatewayBadge");
  badge.textContent = online ? "网关在线" : "网关离线";
  badge.className = `badge ${online ? "" : "muted"}`;
  setText(
    "webrtcGatewayState",
    detail || (online ? "MediaMTX 已就绪，等待相机流。" : "MediaMTX 未运行。"),
  );
}
function setWebRtcVideoToggle(enabled, busy = false) {
  const button = $("webrtcVideoToggle");
  if (!button) return;
  button.disabled = busy;
  button.setAttribute("aria-pressed", String(enabled));
  button.textContent = busy
    ? enabled
      ? "正在启用…"
      : "正在关闭…"
    : enabled
      ? "关闭全部视频"
      : "启用视频";
}
function webRtcStreamLabel(stream) {
  const labels = {
    front_camera: "前向相机",
    back_camera: "后向相机",
    left_camera: "左侧相机",
    right_camera: "右侧相机",
    detection_camera: "目标检测",
    segmentation_overlay: "可通行区域分割",
  };
  return labels[stream.name] || stream.name;
}
function preferredMobileWebRtcStream(streams) {
  const preference = [
    "front_camera",
    "detection_camera",
    "segmentation_overlay",
    "back_camera",
    "left_camera",
    "right_camera",
  ];
  return [...streams].sort((left, right) => {
    const leftIndex = preference.indexOf(left.name);
    const rightIndex = preference.indexOf(right.name);
    return (
      (leftIndex < 0 ? preference.length : leftIndex) -
      (rightIndex < 0 ? preference.length : rightIndex)
    );
  })[0]?.name;
}
function setMobilePrimaryWebRtcStream(name) {
  if (!mobileConsoleEnabled() || !webrtcPlayers.has(name)) return;
  mobilePrimaryWebRtcStream = name;
  const grid = $("webrtcVideoGrid");
  grid.dataset.primary = name;
  for (const [streamName, state] of webrtcPlayers)
    state.card.dataset.primary = String(streamName === name);
  document.querySelectorAll(".webrtc-stream-toggle").forEach((button) => {
    button.dataset.primary = String(button.dataset.stream === name);
  });
}
function syncMobilePrimaryWebRtcStream(streams) {
  if (!streams.some((stream) => stream.name === mobilePrimaryWebRtcStream)) {
    mobilePrimaryWebRtcStream = preferredMobileWebRtcStream(streams);
  }
  if (mobilePrimaryWebRtcStream)
    setMobilePrimaryWebRtcStream(mobilePrimaryWebRtcStream);
}
function setWebRtcStreamToggle(button, stream, busy = false) {
  const selected = stream.enabled === true;
  button.disabled = busy || webrtcToggleInFlight;
  button.setAttribute("aria-pressed", String(selected));
  button.innerHTML = "";
  const title = document.createElement("strong");
  title.textContent = webRtcStreamLabel(stream);
  const state = document.createElement("em");
  state.textContent = busy ? "切换中…" : selected ? "已开启" : "已关闭";
  button.append(title, state);
}
function renderWebRtcStreamControls(streams) {
  const root = $("webrtcStreamControls");
  if (!root) return;
  // 手机上每张视频卡都带有自己的开关。把旧的顶部开关容器从布局树中移除，
  // 不只是依赖样式隐藏它，避免浏览器在横竖屏切换时为一个不可见网格预留行高。
  const mobile = mobileConsoleEnabled();
  root.hidden = mobile;
  root.setAttribute("aria-hidden", String(mobile));
  root.replaceChildren();
  for (const stream of streams) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "webrtc-stream-toggle";
    button.dataset.stream = stream.name;
    const busy = webrtcStreamTogglesInFlight.has(stream.name);
    setWebRtcStreamToggle(button, stream, busy);
    button.addEventListener("click", () => toggleWebRtcStream(stream));
    root.append(button);
  }
}
function setWebRtcPlayerState(state, detail) {
  state.detail.textContent = detail;
  state.label.textContent = state.streamStatus || "等待中";
}
function layoutWebRtcSprite(state) {
  if (!state.sprite || !state.viewport) return;
  const width = state.video.videoWidth || 640;
  const height = state.video.videoHeight || 480;
  const scale = Math.min(
    state.viewport.width / width,
    state.viewport.height / height,
  );
  state.sprite.width = width * scale;
  state.sprite.height = height * scale;
  state.sprite.position.set(
    (state.viewport.width - state.sprite.width) / 2,
    (state.viewport.height - state.sprite.height) / 2,
  );
}
async function initializeWebRtcRenderer(state) {
  if (state.initialization) return state.initialization;
  state.initialization = (async () => {
    const rect = state.surface.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width) || 320);
    const height = Math.max(1, Math.round(rect.height) || 240);
    const app = new Application();
    await app.init({
      width,
      height,
      background: 0x02070d,
      antialias: false,
      autoDensity: true,
      resolution: window.devicePixelRatio || 1,
    });
    app.ticker.stop();
    app.canvas.classList.add("pixi-webrtc-canvas");
    app.canvas.setAttribute("aria-hidden", "true");
    state.surface.append(app.canvas);
    state.app = app;
    state.viewport = { width, height };
    state.resizeObserver = new ResizeObserver(() => {
      const next = state.surface.getBoundingClientRect();
      const nextWidth = Math.max(1, Math.round(next.width));
      const nextHeight = Math.max(1, Math.round(next.height));
      if (
        state.viewport.width === nextWidth &&
        state.viewport.height === nextHeight
      )
        return;
      state.viewport = { width: nextWidth, height: nextHeight };
      app.renderer.resize(nextWidth, nextHeight);
      layoutWebRtcSprite(state);
      app.render();
    });
    state.resizeObserver.observe(state.surface);
  })().catch((error) => {
    setWebRtcPlayerState(
      state,
      `PixiJS 初始化失败：${error?.message || "未知错误"}`,
    );
    throw error;
  });
  return state.initialization;
}
function stopWebRtcFramePump(state) {
  if (state.videoFrameRequest && state.video.cancelVideoFrameCallback)
    state.video.cancelVideoFrameCallback(state.videoFrameRequest);
  state.videoFrameRequest = undefined;
}
function startWebRtcFramePump(state) {
  stopWebRtcFramePump(state);
  const render = () => {
    if (!state.pc || state.video.paused || state.video.ended) return;
    // Pixi v8 VideoSource 在这里按实际解码帧更新，而不是启动全局 ticker 空转。
    state.texture?.source?.update?.();
    layoutWebRtcSprite(state);
    state.app?.render();
    if (state.video.requestVideoFrameCallback)
      state.videoFrameRequest = state.video.requestVideoFrameCallback(render);
    else state.videoFrameRequest = requestAnimationFrame(render);
  };
  if (state.video.requestVideoFrameCallback)
    state.videoFrameRequest = state.video.requestVideoFrameCallback(render);
  else state.videoFrameRequest = requestAnimationFrame(render);
}
function clearWebRtcTexture(state) {
  stopWebRtcFramePump(state);
  state.sprite?.destroy();
  state.sprite = undefined;
  state.texture?.destroy(true);
  state.texture = undefined;
}
function closeWebRtcPlayer(state, message) {
  clearWebRtcTexture(state);
  if (state.sessionUrl)
    fetch(state.sessionUrl, { method: "DELETE", keepalive: true }).catch(
      () => {},
    );
  state.sessionUrl = undefined;
  state.pc?.close();
  state.pc = undefined;
  state.video.pause();
  state.video.srcObject = null;
  if (message) setWebRtcPlayerState(state, message);
}
function destroyWebRtcPlayer(name) {
  const state = webrtcPlayers.get(name);
  if (!state) return;
  closeWebRtcPlayer(state);
  state.resizeObserver?.disconnect();
  state.app?.destroy(true, { children: true });
  state.card.remove();
  webrtcPlayers.delete(name);
}
function createWebRtcPlayer(stream) {
  const card = document.createElement("article");
  card.className = "webrtc-video-card";
  card.dataset.stream = stream.name;
  const header = document.createElement("header");
  const title = document.createElement("h3");
  title.textContent = webRtcStreamLabel(stream);
  const label = document.createElement("span");
  const actions = document.createElement("div");
  actions.className = "webrtc-video-card-actions";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "webrtc-video-card-toggle";
  toggle.textContent = "开启";
  actions.append(label, toggle);
  header.append(title, actions);
  const surface = document.createElement("div");
  surface.className = "webrtc-video-surface";
  const video = document.createElement("video");
  video.className = "webrtc-video-source";
  video.autoplay = true;
  video.muted = true;
  video.playsInline = true;
  video.setAttribute("aria-hidden", "true");
  const detail = document.createElement("p");
  detail.textContent = "等待网关状态。";
  surface.append(video);
  card.append(header, surface, detail);
  $("webrtcVideoGrid").append(card);
  const state = {
    card,
    title,
    label,
    toggle,
    surface,
    video,
    detail,
    stream,
    url: undefined,
    retryAfter: 0,
    streamStatus: "等待中",
  };
  toggle.addEventListener("click", () => toggleWebRtcStream(state.stream));
  card.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest("button"))
      return;
    setMobilePrimaryWebRtcStream(stream.name);
  });
  video.addEventListener("loadedmetadata", () => layoutWebRtcSprite(state));
  webrtcPlayers.set(stream.name, state);
  return state;
}
function waitForIceGathering(peer) {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const timeout = window.setTimeout(done, 1200);
    function done() {
      window.clearTimeout(timeout);
      peer.removeEventListener("icegatheringstatechange", onChange);
      resolve();
    }
    function onChange() {
      if (peer.iceGatheringState === "complete") done();
    }
    peer.addEventListener("icegatheringstatechange", onChange);
  });
}
async function connectWebRtcPlayer(state, stream) {
  if (!window.RTCPeerConnection) {
    setWebRtcPlayerState(state, "当前浏览器不支持 WebRTC。");
    reportObservationOnce(
      `webrtc-${stream.name}`,
      "ERROR",
      `视频流无法播放：${stream.name} 的浏览器不支持 WebRTC。`,
    );
    return;
  }
  if (!stream.url || performance.now() < state.retryAfter) return;
  closeWebRtcPlayer(state);
  state.url = stream.url;
  setWebRtcPlayerState(state, "正在建立 WHEP/WebRTC 会话…");
  const peer = new RTCPeerConnection();
  state.pc = peer;
  peer.addTransceiver("video", { direction: "recvonly" });
  peer.ontrack = async (event) => {
    if (state.pc !== peer) return;
    state.video.srcObject = event.streams[0] || new MediaStream([event.track]);
    try {
      await state.video.play();
      await initializeWebRtcRenderer(state);
      if (state.pc !== peer) return;
      if (!state.texture) {
        state.texture = Texture.from(state.video);
        state.sprite = new Sprite(state.texture);
        state.app?.stage.addChild(state.sprite);
      }
      startWebRtcFramePump(state);
      setWebRtcPlayerState(state, `${stream.resolution} · H.264 · WebRTC`);
      resolveObservationDiagnostic(
        `webrtc-${stream.name}`,
        `视频流已恢复播放：${stream.name}（${stream.source_label || stream.source_topic || "视频输入"}）。`,
      );
    } catch (error) {
      const detail = error?.message || "未知原因";
      setWebRtcPlayerState(state, `浏览器播放被阻止：${detail}`);
      reportObservationOnce(
        `webrtc-${stream.name}`,
        "ERROR",
        `视频流浏览器播放失败：${stream.name}；${detail}`,
      );
    }
  };
  peer.onconnectionstatechange = () => {
    if (state.pc !== peer) return;
    if (peer.connectionState === "connected")
      setWebRtcPlayerState(state, `${stream.resolution} · H.264 · WebRTC`);
    if (["failed", "disconnected", "closed"].includes(peer.connectionState)) {
      state.retryAfter = performance.now() + 3000;
      if (peer.connectionState !== "closed")
        reportObservationOnce(
          `webrtc-${stream.name}`,
          "WARNING",
          `视频流 WebRTC 连接中断：${stream.name}；状态=${peer.connectionState}，将自动重连。`,
        );
      if (peer.connectionState !== "closed")
        closeWebRtcPlayer(state, "WebRTC 已断开，等待重连。");
    }
  };
  try {
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    await waitForIceGathering(peer);
    const response = await fetch(stream.url, {
      method: "POST",
      headers: { Accept: "application/sdp", "Content-Type": "application/sdp" },
      body: peer.localDescription?.sdp || "",
    });
    if (!response.ok) throw new Error(`WHEP HTTP ${response.status}`);
    const location = response.headers.get("Location");
    state.sessionUrl = location
      ? new URL(location, stream.url).toString()
      : undefined;
    await peer.setRemoteDescription({
      type: "answer",
      sdp: await response.text(),
    });
  } catch (error) {
    if (state.pc === peer) {
      const detail = error?.message || "未知错误";
      state.retryAfter = performance.now() + 3000;
      closeWebRtcPlayer(state, `WebRTC 连接失败：${detail}`);
      reportObservationOnce(
        `webrtc-${stream.name}`,
        "ERROR",
        `视频流 WHEP/WebRTC 建连失败：${stream.name} (${stream.source_label || stream.source_topic || "视频输入"})；${detail}`,
      );
    }
  }
}
function diagnoseWebRtcStatus(enabled, gateway, streams) {
  const now = performance.now();
  if (enabled && gateway.online !== true) {
    if (!videoGatewayOfflineSince) videoGatewayOfflineSince = now;
    if (now - videoGatewayOfflineSince >= VIDEO_INPUT_READINESS_TIMEOUT_MS) {
      reportObservationOnce(
        "video-gateway",
        "ERROR",
        `视频网关未就绪：${gateway.detail || "MediaMTX API 不可用"}。请查看 logs/video-runtime.log。`,
      );
    }
  } else {
    videoGatewayOfflineSince = 0;
    resolveObservationDiagnostic("video-gateway", "视频网关已恢复就绪。");
  }
  const configured = new Set(streams.map((stream) => stream.name));
  for (const [name] of videoWaitingSince)
    if (!configured.has(name)) videoWaitingSince.delete(name);
  for (const stream of streams) {
    const key = `video-input-${stream.name}`;
    if (!enabled || stream.enabled !== true) {
      videoWaitingSince.delete(stream.name);
      activeObservationDiagnostics.delete(key);
      continue;
    }
    if (stream.status === "online") {
      videoWaitingSince.delete(stream.name);
      resolveObservationDiagnostic(
        key,
        `视频输入已恢复：${stream.name}（${stream.source_label || stream.source_topic || "视频输入"}）已发布到 MediaMTX。`,
      );
      continue;
    }
    if (stream.status === "waiting") {
      const since = videoWaitingSince.get(stream.name) || now;
      videoWaitingSince.set(stream.name, since);
      if (now - since >= VIDEO_INPUT_READINESS_TIMEOUT_MS) {
        reportObservationOnce(
          key,
          "WARNING",
          `视频输入等待超时：${stream.name} 正在等待 ${stream.source_label || stream.source_topic || "视频输入"} 的 ${stream.encoding} ${stream.resolution} 首帧。请查看 logs/video-runtime.log 中该流的来源、编码和分辨率诊断。`,
        );
      }
      continue;
    }
    videoWaitingSince.delete(stream.name);
    reportObservationOnce(
      key,
      "ERROR",
      `视频流不可用：${stream.name}；状态=${stream.status || "unknown"}，网关=${gateway.detail || "未知"}。请查看 logs/video-runtime.log。`,
    );
  }
}
function applyWebRtcVideoStatus(payload) {
  const enabled = payload?.enabled === true;
  const gateway = payload?.gateway || {};
  const configuredStreams = Array.isArray(payload?.streams)
    ? payload.streams
    : [];
  const activeStreams = enabled
    ? configuredStreams.filter((stream) => stream.enabled === true)
    : [];
  // 手机端的每路卡片同时就是独立控制入口：开关不再占据顶部空间。桌面仍只
  // 呈现已启用流及原有控制条，保持其既有工作台节奏。
  const streams = mobileConsoleEnabled() ? configuredStreams : activeStreams;
  webrtcConfiguredStreams = configuredStreams;
  webrtcVideoEnabled = enabled;
  setWebRtcVideoToggle(enabled, webrtcToggleInFlight);
  setText(
    "mobileCameraSummary",
    `视频 ${activeStreams.filter((stream) => stream.status === "online").length} / ${configuredStreams.length}`,
  );
  setWebRtcGatewayState(gateway.online === true, gateway.detail);
  diagnoseWebRtcStatus(enabled, gateway, configuredStreams);
  renderWebRtcStreamControls(configuredStreams);
  const grid = $("webrtcVideoGrid");
  grid.dataset.count = String(streams.length);
  const empty = $("webrtcVideoEmpty");
  empty.hidden = streams.length > 0;
  empty.textContent = enabled ? "未选择任何相机流。" : "视频已关闭。";
  for (const name of [...webrtcPlayers.keys()])
    if (!streams.some((stream) => stream.name === name))
      destroyWebRtcPlayer(name);
  for (const stream of streams) {
    const state = webrtcPlayers.get(stream.name) || createWebRtcPlayer(stream);
    state.stream = stream;
    const active = enabled && stream.enabled === true;
    state.card.dataset.active = String(active);
    state.card.dataset.standby = String(!active);
    state.streamStatus = active
      ? stream.status === "online"
        ? "在线"
        : stream.status === "waiting"
          ? "等待相机"
          : "离线"
      : "待机";
    state.toggle.disabled =
      webrtcToggleInFlight || webrtcStreamTogglesInFlight.has(stream.name);
    state.toggle.textContent = webrtcStreamTogglesInFlight.has(stream.name)
      ? "切换中…"
      : active
        ? "关闭"
        : "开启";
    if (active && stream.status === "online" && mobileWebRtcPlaybackAllowed()) {
      if (
        state.url !== stream.url ||
        !state.pc ||
        ["failed", "closed"].includes(state.pc.connectionState)
      )
        connectWebRtcPlayer(state, stream);
    } else if (active && stream.status === "online")
      closeWebRtcPlayer(state, "相机页未显示，浏览器解码已暂停。");
    else
      closeWebRtcPlayer(
        state,
        active && stream.status === "waiting"
          ? "编码端正在等待 ROS 图像。"
          : active
            ? "MediaMTX 未就绪。"
            : "该路视频处于待机状态。",
      );
  }
  syncMobilePrimaryWebRtcStream(activeStreams.length ? activeStreams : streams);
}
async function refreshWebRtcVideoStatus() {
  try {
    applyWebRtcVideoStatus(await request("/api/video/status"));
  } catch (error) {
    setWebRtcGatewayState(false, `读取视频状态失败：${error.message}`);
    reportObservationOnce(
      "video-status-api",
      "WARNING",
      `读取视频状态失败：${error.message}`,
    );
  }
}
async function toggleWebRtcVideo() {
  if (webrtcToggleInFlight || webrtcStreamTogglesInFlight.size) return;
  const enabled = !webrtcVideoEnabled;
  webrtcToggleInFlight = true;
  setWebRtcVideoToggle(enabled, true);
  try {
    applyWebRtcVideoStatus(
      await request("/api/video/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      }),
    );
  } catch (error) {
    setWebRtcGatewayState(false, `视频切换失败：${error.message}`);
    reportObservation("ERROR", `视频全局开关失败：${error.message}`);
  } finally {
    webrtcToggleInFlight = false;
    setWebRtcVideoToggle(webrtcVideoEnabled, false);
    renderWebRtcStreamControls(webrtcConfiguredStreams);
  }
}
async function toggleWebRtcStream(stream) {
  if (!stream?.name || webrtcToggleInFlight || webrtcStreamTogglesInFlight.size)
    return;
  webrtcStreamTogglesInFlight.add(stream.name);
  renderWebRtcStreamControls(webrtcConfiguredStreams);
  try {
    const payload = await request("/api/video/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stream: stream.name,
        enabled: stream.enabled !== true,
      }),
    });
    applyWebRtcVideoStatus(payload);
  } catch (error) {
    setWebRtcGatewayState(false, `视频流切换失败：${error.message}`);
    reportObservation(
      "ERROR",
      `视频流开关失败：${stream.name}；${error.message}`,
    );
  } finally {
    webrtcStreamTogglesInFlight.delete(stream.name);
    renderWebRtcStreamControls(webrtcConfiguredStreams);
    refreshWebRtcVideoStatus();
  }
}
function startWebRtcVideoStatus() {
  refreshWebRtcVideoStatus();
  webrtcStatusTimer = window.setInterval(refreshWebRtcVideoStatus, 3000);
}
function setupMapInteraction() {
  const interaction = $("mapInteraction");
  const wrap = interaction.parentElement;
  const resizeMapViewport = () => {
    const wrap = interaction.parentElement;
    const rect = wrap?.getBoundingClientRect();
    if (!rect?.width || !rect?.height) return;
    // 交互层和 Pixi 世界层均严格使用 CSS 像素；渲染器自行处理高 DPI，不能
    // 把 devicePixelRatio 混入视图坐标，否则滚轮锚点会与车体层错位。
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    if (mapViewport.width === width && mapViewport.height === height) return;
    mapViewport.width = width;
    mapViewport.height = height;
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
    if (mapInteractionTimer) {
      window.clearTimeout(mapInteractionTimer);
      mapInteractionTimer = undefined;
    }
    if (!active && cloudRasterPending) {
      cloudRasterPending = false;
      scheduleCloudRasterBuild();
    }
  };
  const deferInteractionEnd = () => {
    if (mapInteractionTimer) window.clearTimeout(mapInteractionTimer);
    mapInteractionTimer = window.setTimeout(
      () => setInteractionActive(false),
      140,
    );
  };
  const eventViewportPoint = (event) => {
    const rect = interaction.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const worldAtViewportPoint = (target, layout) => {
    const dx = target.x - mapViewport.width / 2;
    const dy = target.y - mapViewport.height / 2;
    const cosine = Math.cos(layout.rotation);
    const sine = Math.sin(layout.rotation);
    return {
      x: layout.center.x + (cosine * dx + sine * dy) / layout.pixelsPerMeter,
      y: layout.center.y - (-sine * dx + cosine * dy) / layout.pixelsPerMeter,
    };
  };
  const midpoint = () => {
    const points = [...touchPoints.values()];
    return {
      x: (points[0].x + points[1].x) / 2,
      y: (points[0].y + points[1].y) / 2,
    };
  };
  const distanceBetweenTouches = () => {
    const points = [...touchPoints.values()];
    return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  };
  const beginPinch = () => {
    if (touchPoints.size !== 2 || !mapInfo) return;
    const layout = currentMapLayout();
    const point = midpoint();
    pinch = {
      distance: Math.max(1, distanceBetweenTouches()),
      pixelsPerMeter: layout.pixelsPerMeter,
      anchor: worldAtViewportPoint(point, layout),
    };
    pan = undefined;
    interaction.classList.remove("is-panning");
  };
  const applyPinch = () => {
    if (!pinch || touchPoints.size !== 2 || !mapInfo) return;
    const point = midpoint();
    const factor = distanceBetweenTouches() / pinch.distance;
    mapView.pixelsPerMeter = Math.max(
      MIN_PIXELS_PER_METER,
      Math.min(MAX_PIXELS_PER_METER, pinch.pixelsPerMeter * factor),
    );
    const before = currentMapLayout();
    const dx = point.x - mapViewport.width / 2;
    const dy = point.y - mapViewport.height / 2;
    const cosine = Math.cos(before.rotation);
    const sine = Math.sin(before.rotation);
    const desiredCenter = {
      x: pinch.anchor.x - (cosine * dx + sine * dy) / mapView.pixelsPerMeter,
      y: pinch.anchor.y + (-sine * dx + cosine * dy) / mapView.pixelsPerMeter,
    };
    const vehicle = vehiclePoseInMap();
    if (vehicle?.position) {
      mapView.followVehicle = true;
      mapView.followOffset = {
        x: desiredCenter.x - vehicle.position.x,
        y: desiredCenter.y - vehicle.position.y,
      };
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
    const before = currentMapLayout();
    const cursor = eventViewportPoint(event);
    const anchor = worldAtViewportPoint(cursor, before);
    // 对鼠标滚轮和触控板使用相同的连续比例，而不是每一条事件只跳一个固定档位。
    // 这使放大/缩小响应立即且不会被浏览器的滚动节流吞掉。
    const factor = Math.exp(
      Math.max(-0.32, Math.min(0.32, -event.deltaY * 0.0022)),
    );
    mapView.pixelsPerMeter = Math.max(
      MIN_PIXELS_PER_METER,
      Math.min(
        MAX_PIXELS_PER_METER,
        (mapView.pixelsPerMeter || mapViewport.width / DEFAULT_VIEW_METERS) *
          factor,
      ),
    );
    // 光标下的世界坐标在缩放前后不变；保存相对车辆偏移后，车辆仍保持连续跟随。
    const dx = cursor.x - mapViewport.width / 2;
    const dy = cursor.y - mapViewport.height / 2;
    const cosine = Math.cos(before.rotation);
    const sine = Math.sin(before.rotation);
    const desiredCenter = {
      x: anchor.x - (cosine * dx + sine * dy) / mapView.pixelsPerMeter,
      y: anchor.y + (-sine * dx + cosine * dy) / mapView.pixelsPerMeter,
    };
    const vehicle = vehiclePoseInMap();
    if (vehicle?.position) {
      mapView.followVehicle = true;
      mapView.followOffset = {
        x: desiredCenter.x - vehicle.position.x,
        y: desiredCenter.y - vehicle.position.y,
      };
    } else mapView.center = desiredCenter;
    scheduleMapDraw(true);
  };
  // 监听整个地图容器，避免覆盖图层或图例改变后吞掉滚轮事件。
  wrap.addEventListener("wheel", onWheel, { passive: false });
  interaction.addEventListener("dblclick", () => {
    overviewUntilMovement = false;
    mapView.followVehicle = true;
    mapView.followOffset = { x: 0, y: 0 };
    const vehicle = vehiclePoseInMap();
    if (vehicle?.position)
      mapView.center = { x: vehicle.position.x, y: vehicle.position.y };
    scheduleMapDraw(true);
  });
  const finishPan = (event) => {
    if (!pan || (event && event.pointerId !== pan.pointerId)) return;
    if (interaction.hasPointerCapture(pan.pointerId))
      interaction.releasePointerCapture(pan.pointerId);
    pan = undefined;
    interaction.classList.remove("is-panning");
  };
  interaction.addEventListener("pointerdown", (event) => {
    // 同时支持左键和中键拖拽；中键仍保留，左键避免操作者误以为地图不能拖动。
    if ((event.button !== 0 && event.button !== 1) || !mapInfo) return;
    event.preventDefault();
    setInteractionActive(true);
    if (event.pointerType === "touch") {
      touchPoints.set(event.pointerId, eventViewportPoint(event));
      interaction.setPointerCapture(event.pointerId);
      if (touchPoints.size === 2) beginPinch();
      else if (touchPoints.size > 2) pinch = undefined;
      else {
        pan = { pointerId: event.pointerId, point: eventViewportPoint(event) };
        interaction.classList.add("is-panning");
      }
      return;
    }
    pan = { pointerId: event.pointerId, point: eventViewportPoint(event) };
    interaction.setPointerCapture(event.pointerId);
    interaction.classList.add("is-panning");
  });
  interaction.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch" && touchPoints.has(event.pointerId)) {
      touchPoints.set(event.pointerId, eventViewportPoint(event));
      if (pinch) {
        event.preventDefault();
        applyPinch();
        return;
      }
    }
    if (!pan || event.pointerId !== pan.pointerId || !mapInfo) return;
    const next = eventViewportPoint(event);
    const dx = next.x - pan.point.x;
    const dy = next.y - pan.point.y;
    pan.point = next;
    if (!dx && !dy) return;
    const layout = currentMapLayout();
    const cosine = Math.cos(layout.rotation);
    const sine = Math.sin(layout.rotation);
    // 屏幕位移逆变换回地图坐标；拖动的是地图本身，因此中心向反方向平移。
    const localX = (cosine * dx + sine * dy) / layout.pixelsPerMeter;
    const localY = (-sine * dx + cosine * dy) / layout.pixelsPerMeter;
    mapView.center = {
      x: layout.center.x - localX,
      y: layout.center.y + localY,
    };
    mapView.followVehicle = false;
    overviewUntilMovement = false;
    scheduleMapDraw(true);
  });
  const finishTouch = (event, cancelled = false) => {
    touchPoints.delete(event.pointerId);
    if (touchPoints.size >= 2) beginPinch();
    else if (touchPoints.size === 1 && !cancelled) {
      const [pointerId, point] = touchPoints.entries().next().value;
      pinch = undefined;
      pan = { pointerId, point };
      interaction.classList.add("is-panning");
    } else {
      pinch = undefined;
      finishPan();
    }
  };
  interaction.addEventListener("pointerup", (event) => {
    if (event.pointerType === "touch") finishTouch(event);
    else finishPan(event);
    deferInteractionEnd();
  });
  interaction.addEventListener("pointercancel", (event) => {
    if (event.pointerType === "touch") finishTouch(event, true);
    else finishPan(event);
    if (!touchPoints.size) setInteractionActive(false);
  });
  interaction.addEventListener("lostpointercapture", (event) => {
    if (event.pointerType === "touch") touchPoints.delete(event.pointerId);
    if (!touchPoints.size) {
      pinch = undefined;
      finishPan(event);
      setInteractionActive(false);
    }
  });
}
function normalizeAngle(value) {
  let angle = value;
  while (angle > Math.PI) angle -= Math.PI * 2;
  while (angle <= -Math.PI) angle += Math.PI * 2;
  return angle;
}
async function initializePixiRenderer() {
  const host = $("mapWorld");
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
    app.canvas.classList.add("pixi-map-canvas");
    app.canvas.setAttribute("aria-hidden", "true");
    host.replaceChildren(app.canvas);
    pixiApp = app;
    pixiWorld = new Container();
    pixiMapLayer = new Container();
    pixiGridLayer = new Container();
    pixiCostmapLayer = new Container();
    pixiWallLayer = new Container();
    pixiCloudLayer = new Container();
    pixiWorld.addChild(pixiMapLayer, pixiGridLayer, pixiCostmapLayer, pixiWallLayer, pixiCloudLayer);
    app.stage.addChild(pixiWorld);
    pixiReady = true;
    renderStaticWorld();
    rebuildCloudRaster();
    scheduleMapDraw();
  })().catch((error) => {
    reportObservation(
      "ERROR",
      `PixiJS 渲染器初始化失败：${error?.message || "未知错误"}`,
    );
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
  const delay =
    CLOUD_COMPOSITE_MIN_INTERVAL_MS - (performance.now() - lastCloudRenderAt);
  if (delay > 0) {
    if (!cloudRenderTimer)
      cloudRenderTimer = window.setTimeout(() => {
        cloudRenderTimer = undefined;
        flushCloudRenderer();
      }, delay);
    return;
  }
  const frame = pendingCloudFrame;
  pendingCloudFrame = undefined;
  lastCloudRenderAt = performance.now();
  if (frame.generation === mapGeneration) renderCloudPoints(frame.points);
  if (pendingCloudFrame) flushCloudRenderer();
}
function packCloudPoints(points) {
  const packed = new Float32Array(points.length * 2);
  for (let index = 0; index < points.length; index += 1) {
    packed[index * 2] = points[index].x;
    packed[index * 2 + 1] = points[index].y;
  }
  return packed;
}
function predictVehicleMotion(pose, seconds) {
  const horizon = Math.max(
    0,
    Math.min(MAX_VEHICLE_PREDICTION_MS / 1000, seconds),
  );
  const rawVelocity = pose.velocity || { x: 0, y: 0 };
  const velocity = {
    x: Number(rawVelocity.x) || 0,
    y: Number(rawVelocity.y) || 0,
  };
  const yawRate = Number.isFinite(pose.yawRate) ? pose.yawRate : 0;
  let x = pose.position.x + velocity.x * horizon;
  let y = pose.position.y + velocity.y * horizon;
  // CTRV：速度主要沿车体前向、且正在转弯时按圆弧外推。低速/横移时退回
  // 笛卡尔恒速模型，避免定位噪声把静止车体画成小圆圈。
  const forwardSpeed =
    velocity.x * Math.cos(pose.yaw) + velocity.y * Math.sin(pose.yaw);
  if (
    Math.abs(forwardSpeed) >= VEHICLE_VELOCITY_DEADBAND_MPS &&
    Math.abs(yawRate) >= 0.03
  ) {
    const nextYaw = pose.yaw + yawRate * horizon;
    x =
      pose.position.x +
      (forwardSpeed / yawRate) * (Math.sin(nextYaw) - Math.sin(pose.yaw));
    y =
      pose.position.y -
      (forwardSpeed / yawRate) * (Math.cos(nextYaw) - Math.cos(pose.yaw));
  }
  return {
    position: { x, y },
    yaw: normalizeAngle(pose.yaw + yawRate * horizon),
    velocity,
    yawRate,
    source: pose.source,
  };
}
function renderedVehiclePoseInMap() {
  const target = vehiclePoseInMap();
  if (!target?.position) return undefined;
  const now = performance.now();
  // `receivedAt` 表示链路仍活跃：轻量 Pose 节点会以 60 Hz 发送相同坐标的心跳。
  // 它不能作为外推起点，否则每个重复包都会把预测时间归零，并把动画车体拉回
  // 旧的真实测量位置。live 流单独保留最后一次实际位置/航向变化的时刻；兼容
  // TF 路径则仍以接收时刻为准。两者都被 300 ms 硬上限约束，不会用平滑掩盖失联。
  const motionMeasuredAt =
    target.source === "live" ? target.motionMeasuredAt : target.receivedAt;
  const predictionSeconds = Math.min(
    MAX_VEHICLE_PREDICTION_MS / 1000,
    Math.max(0, now - Number(motionMeasuredAt || target.receivedAt || now)) /
      1000 +
      (target.sourceAgeMs || 0) / 1000,
  );
  const desired = predictVehicleMotion(target, predictionSeconds);
  if (
    !renderedVehiclePose ||
    now - renderedVehicleAt > 1200 ||
    Math.hypot(
      desired.position.x - renderedVehiclePose.position.x,
      desired.position.y - renderedVehiclePose.position.y,
    ) > 2.5
  ) {
    renderedVehiclePose = desired;
    renderedVehicleAt = now;
    return renderedVehiclePose;
  }
  // α-β 预测—校正：每个显示帧先按自身速度前推，再用最新真实观测的残差校正。
  // 比单纯低通更贴近实车，同时对定位的厘米级高频抖动保持稳定。
  const deltaSeconds = Math.min(
    0.08,
    Math.max(0.001, (now - renderedVehicleAt) / 1000),
  );
  const predicted = predictVehicleMotion(renderedVehiclePose, deltaSeconds);
  const errorX = desired.position.x - predicted.position.x;
  const errorY = desired.position.y - predicted.position.y;
  const displacement = Math.hypot(errorX, errorY);
  const gain =
    displacement < VEHICLE_POSITION_DEADBAND_M
      ? 0.32
      : ALPHA_BETA_POSITION_GAIN;
  renderedVehiclePose.position.x = predicted.position.x + errorX * gain;
  renderedVehiclePose.position.y = predicted.position.y + errorY * gain;
  const correctedVelocity = {
    x:
      predicted.velocity.x + (errorX * ALPHA_BETA_VELOCITY_GAIN) / deltaSeconds,
    y:
      predicted.velocity.y + (errorY * ALPHA_BETA_VELOCITY_GAIN) / deltaSeconds,
  };
  renderedVehiclePose.velocity = {
    x: correctedVelocity.x * 0.28 + (desired.velocity.x || 0) * 0.72,
    y: correctedVelocity.y * 0.28 + (desired.velocity.y || 0) * 0.72,
  };
  renderedVehiclePose.yaw = normalizeAngle(
    predicted.yaw + normalizeAngle(desired.yaw - predicted.yaw) * gain,
  );
  renderedVehiclePose.yawRate = desired.yawRate || 0;
  renderedVehiclePose.source = desired.source;
  renderedVehicleAt = now;
  return renderedVehiclePose;
}
function requestVehicleAnimation() {
  if (vehicleAnimationFrame || document.hidden || !vehiclePoseInMap()?.position)
    return;
  const render = (frameAt) => {
    vehicleAnimationFrame = undefined;
    if (document.hidden || !lastMapLayout) return;
    if (clientPerformance.lastVehicleFrameAt) {
      const interval = frameAt - clientPerformance.lastVehicleFrameAt;
      clientPerformance.vehicleFrameIntervalMs =
        clientPerformance.vehicleFrameIntervalMs
          ? clientPerformance.vehicleFrameIntervalMs * 0.85 + interval * 0.15
          : interval;
      if (interval > 34) clientPerformance.vehicleLongFrames += 1;
    }
    clientPerformance.lastVehicleFrameAt = frameAt;
    clientPerformance.vehicleFrames += 1;
    const vehicle = renderedVehiclePoseInMap();
    if (vehicle?.position) syncVehicleLayer(vehicle, lastMapLayout);
    // 仅更新独立 DOM 车体层；不重新绘制地图、虚拟墙或点云。
    if (
      vehiclePoseInMap()?.position &&
      performance.now() - vehicleUpdatedAt < 1500
    )
      vehicleAnimationFrame = requestAnimationFrame(render);
  };
  vehicleAnimationFrame = requestAnimationFrame(render);
}
function followVehicleCenter(vehicle) {
  const desired = {
    x: vehicle.position.x + (mapView.followOffset?.x || 0),
    y: vehicle.position.y + (mapView.followOffset?.y || 0),
  };
  if (
    !mapView.center ||
    Math.hypot(desired.x - mapView.center.x, desired.y - mapView.center.y) >
      FOLLOW_CENTER_SNAP_DISTANCE_M
  ) {
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
  if (!vehicle?.position || overviewUntilMovement || !mapView.followVehicle)
    return false;
  const desiredX = vehicle.position.x + (mapView.followOffset?.x || 0);
  const desiredY = vehicle.position.y + (mapView.followOffset?.y || 0);
  const centerPending =
    !mapView.center ||
    Math.hypot(desiredX - mapView.center.x, desiredY - mapView.center.y) >
      FOLLOW_CENTER_SETTLE_DISTANCE_M;
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
    x: mapInfo.origin.x + (mapInfo.width * mapInfo.resolution) / 2,
    y: mapInfo.origin.y + (mapInfo.height * mapInfo.resolution) / 2,
  };
  const vehicle = renderedVehiclePoseInMap();
  if (overviewUntilMovement) mapView.center = fallbackCenter;
  else if (mapView.followVehicle && vehicle?.position) {
    followVehicleCenter(vehicle);
  }
  if (!mapView.center) mapView.center = fallbackCenter;
  if (!mapView.pixelsPerMeter) {
    const worldWidth = mapInfo.width * mapInfo.resolution;
    const worldHeight = mapInfo.height * mapInfo.resolution;
    const fullMapScale =
      Math.min(
        mapViewport.width / worldWidth,
        mapViewport.height / worldHeight,
      ) * 0.92;
    const viewportAspect = mapViewport.width / Math.max(1, mapViewport.height);
    const mapAspect = worldWidth / Math.max(1e-6, worldHeight);
    // 手机上的横屏 WebView 常常只剩下一条很浅的可视区域。若仍强行把整张
    // 近方形地图塞入其中，地图会缩成中央一张小邮票，格栅和车体都无法阅读。
    // 这时以地图宽度建立初始工作视图：保留完整横向路线，裁去上下远端；用户
    // 仍可双指缩放/拖动，车辆移动后也会自然进入标准 16m 跟车尺度。
    const shallowLandscape =
      viewportAspect >= Math.max(2.1, mapAspect * 1.65) &&
      mapViewport.height < 360;
    const focusedLandscapeScale = (mapViewport.width / worldWidth) * 0.94;
    mapView.pixelsPerMeter = overviewUntilMovement
      ? // 初始概览必须完整容纳地图；不能套用近景视图的最小缩放限制，
        // 否则在大地图上仍会出现边缘被裁切的“概览”。浅横屏例外见上：
        // 优先可读性而不是留出大量无效背景。
        Math.max(1, shallowLandscape ? focusedLandscapeScale : fullMapScale)
      : Math.max(
          MIN_PIXELS_PER_METER,
          Math.min(
            MAX_PIXELS_PER_METER,
            mapViewport.width / DEFAULT_VIEW_METERS,
          ),
        );
  }
  const ratio = mapInfo.resolution * mapView.pixelsPerMeter;
  const width = mapInfo.width * ratio;
  const height = mapInfo.height * ratio;
  return {
    ratio,
    width,
    height,
    pixelsPerMeter: mapView.pixelsPerMeter,
    center: mapView.center,
    vehicle,
    viewportWidth: mapViewport.width,
    viewportHeight: mapViewport.height,
    // 地图必须稳定保持其原始 map 坐标朝向。定位航向的零点不一定与地图北向
    // 完全一致，若在进入页面时旋转地图，会让静止小车也看到整张地图倾斜。
    rotation: 0,
    left:
      mapViewport.width / 2 +
      (mapInfo.origin.x - mapView.center.x) * mapView.pixelsPerMeter,
    top:
      mapViewport.height / 2 -
      (mapInfo.origin.y +
        mapInfo.height * mapInfo.resolution -
        mapView.center.y) *
        mapView.pixelsPerMeter,
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
      drawAnimationFrame = undefined;
      drawQueued = false;
      lastMapDrawAt = performance.now();
      drawMap();
    });
  };
  if (interactive || elapsed >= MAP_RENDER_INTERVAL_MS) render();
  else
    drawDeferredTimer = window.setTimeout(
      render,
      MAP_RENDER_INTERVAL_MS - elapsed,
    );
}
function stopRenderScheduling() {
  if (drawDeferredTimer) window.clearTimeout(drawDeferredTimer);
  if (drawAnimationFrame) window.cancelAnimationFrame(drawAnimationFrame);
  drawDeferredTimer = undefined;
  drawAnimationFrame = undefined;
  drawQueued = false;
  if (vehicleAnimationFrame) window.cancelAnimationFrame(vehicleAnimationFrame);
  vehicleAnimationFrame = undefined;
}
function metricGridStep(pixelsPerMeter) {
  let step = pixelsPerMeter >= 28 ? 1 : pixelsPerMeter >= 12 ? 2 : 5;
  const mapExtent = mapInfo
    ? (mapInfo.width + mapInfo.height) * mapInfo.resolution
    : 0;
  while (mapExtent / step > 600) step *= 2;
  return step;
}
function updateMapScale(layout, gridStep) {
  const root = $("mapScale");
  const bar = $("mapScaleBar");
  if (!root || !bar) return;
  if (!mobileConsoleEnabled()) {
    root.hidden = true;
    return;
  }
  const candidates = [0.5, 1, 2, 5, 10, 20, 50, 100];
  const scaleDistance = candidates.reduce(
    (best, value) => {
      const width = value * layout.pixelsPerMeter;
      const score =
        width >= 48 && width <= 132
          ? Math.abs(width - 88)
          : 1000 + Math.abs(width - 88);
      return score < best.score ? { value, score } : best;
    },
    { value: 1, score: Infinity },
  ).value;
  root.hidden = false;
  bar.style.width = `${Math.max(36, Math.min(132, scaleDistance * layout.pixelsPerMeter))}px`;
  setText("mapScaleLabel", `${scaleDistance} m`);
  setText("mapGridLabel", `${gridStep} m 小格 · ${gridStep * 5} m 主格`);
}
function renderMetricGrid(layout) {
  if (!pixiGridLayer || !mapInfo) return;
  if (!mobileConsoleEnabled()) {
    metricGridSignature = undefined;
    pixiGridLayer.removeChildren().forEach((child) => child.destroy());
    $("mapScale").hidden = true;
    return;
  }
  const step = metricGridStep(layout.pixelsPerMeter);
  const majorStep = step * 5;
  // 线宽按当前屏幕缩放反算到地图像素，缩放前后始终保持约 0.65/1.1 CSS px。
  const widthBucket = Math.max(1, Math.round(layout.pixelsPerMeter / 4));
  const signature = `${mapGeneration}:${step}:${widthBucket}`;
  updateMapScale(layout, step);
  if (signature === metricGridSignature) return;
  metricGridSignature = signature;
  pixiGridLayer.removeChildren().forEach((child) => child.destroy());
  const minX = Number(mapInfo.origin.x);
  const minY = Number(mapInfo.origin.y);
  const maxX = minX + mapInfo.width * mapInfo.resolution;
  const maxY = minY + mapInfo.height * mapInfo.resolution;
  const drawLines = (spacing, graphics) => {
    const firstX = Math.ceil((minX - 1e-9) / spacing) * spacing;
    const firstY = Math.ceil((minY - 1e-9) / spacing) * spacing;
    for (
      let worldX = firstX, count = 0;
      worldX <= maxX + 1e-7 && count < 1000;
      worldX += spacing, count += 1
    ) {
      const x = (worldX - minX) / mapInfo.resolution;
      graphics.moveTo(x, 0);
      graphics.lineTo(x, mapInfo.height);
    }
    for (
      let worldY = firstY, count = 0;
      worldY <= maxY + 1e-7 && count < 1000;
      worldY += spacing, count += 1
    ) {
      const y = mapInfo.height - (worldY - minY) / mapInfo.resolution;
      graphics.moveTo(0, y);
      graphics.lineTo(mapInfo.width, y);
    }
  };
  const minor = new Graphics();
  drawLines(step, minor);
  minor.stroke({
    color: MAP_PALETTE.gridMinor,
    width: 0.65 / layout.ratio,
    alpha: 0.16,
  });
  const major = new Graphics();
  drawLines(majorStep, major);
  major.stroke({
    color: MAP_PALETTE.gridMajor,
    width: 1.1 / layout.ratio,
    alpha: 0.28,
  });
  pixiGridLayer.addChild(minor, major);
}
function drawMap() {
  if (!mapInfo || !mapTexture || !pixiReady) return;
  // 地图纹理、虚拟墙和点云均由 PixiJS 的同一世界容器渲染。此处只更新
  // GPU 相机矩阵，不重新上传静态地图纹理或重建点云几何。
  const layout = currentMapLayout();
  lastMapLayout = layout;
  renderMetricGrid(layout);
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
  pixiMapTexture.source.scaleMode = "nearest";
  pixiMapSprite = new Sprite(pixiMapTexture);
  pixiMapSprite.width = mapInfo.width;
  pixiMapSprite.height = mapInfo.height;
  pixiMapLayer.addChild(pixiMapSprite);
  metricGridSignature = undefined;
  pixiGridLayer.removeChildren().forEach((child) => child.destroy());
  pixiWallLayer.removeChildren().forEach((child) => child.destroy());
  const walls = new Graphics();
  const mobile = mobileConsoleEnabled();
  // 手机地图的墙线比原始占据栅格更粗，并带一层深红细边；不会与紫色点云或栅格混在一起。
  const lineWidth = mobile
    ? Math.max(1.8, 0.11 / mapInfo.resolution)
    : Math.max(1, 0.06 / mapInfo.resolution);
  for (const wall of virtualWalls) {
    const points = Array.isArray(wall.points) ? wall.points : [];
    if (points.length < 2) continue;
    points.forEach((point, index) => {
      const world =
        wall.coordinate_mode === "image_relative"
          ? {
              x: mapInfo.origin.x + Number(point.x),
              y: mapInfo.origin.y + Number(point.y),
            }
          : { x: Number(point.x), y: Number(point.y) };
      const targetX = (world.x - mapInfo.origin.x) / mapInfo.resolution;
      const targetY =
        mapInfo.height - (world.y - mapInfo.origin.y) / mapInfo.resolution;
      if (index === 0) walls.moveTo(targetX, targetY);
      else walls.lineTo(targetX, targetY);
    });
  }
  if (mobile)
    walls.stroke({
      color: 0x6f1f2a,
      width: lineWidth + 1.4,
      alpha: 0.72,
      cap: "round",
      join: "round",
    });
  walls.stroke({
    color: (mobile ? MAP_PALETTE : DESKTOP_MAP_PALETTE).virtualWall,
    width: lineWidth,
    cap: "round",
    join: "round",
  });
  pixiWallLayer.addChild(walls);
  renderCostmap();
  pixiApp.render();
}
function renderCloudPoints(packedPoints) {
  if (!pixiReady || !mapInfo) return;
  pixiCloudLayer.removeChildren().forEach((child) => child.destroy());
  if (!packedPoints?.length) {
    pixiApp.render();
    return;
  }
  const points = new Graphics();
  const mobile = mobileConsoleEnabled();
  // 大屏采用 0.52 px 让抽稀后的导航点在白底图上可稳定辨识；手机保持 0.82 px
  // 以应对更高的物理像素密度。两端共用相同点云帧，差异仅为显示尺度。
  const pointRadius = mobile ? 0.82 : 0.52;
  for (let index = 0; index < packedPoints.length; index += 2) {
    const x = (packedPoints[index] - mapInfo.origin.x) / mapInfo.resolution;
    const y =
      mapInfo.height -
      (packedPoints[index + 1] - mapInfo.origin.y) / mapInfo.resolution;
    if (x >= 0 && x < mapInfo.width && y >= 0 && y < mapInfo.height)
      points.rect(
        x - pointRadius,
        y - pointRadius,
        pointRadius * 2,
        pointRadius * 2,
      );
  }
  points.fill(
    (mobileConsoleEnabled() ? MAP_PALETTE : DESKTOP_MAP_PALETTE).cloud,
  );
  pixiCloudLayer.addChild(points);
  pixiApp.render();
}
function syncVehicleLayer(vehicle, layout) {
  const element = $("vehicleLayer");
  if (
    !vehicle?.position ||
    !mapInfo ||
    !Number.isFinite(Number(vehicle.position.x)) ||
    !Number.isFinite(Number(vehicle.position.y))
  ) {
    element.hidden = true;
    return;
  }
  const nativeX = (vehicle.position.x - mapInfo.origin.x) / mapInfo.resolution;
  const nativeY =
    mapInfo.height -
    (vehicle.position.y - mapInfo.origin.y) / mapInfo.resolution;
  const baseX = layout.left + nativeX * layout.ratio;
  const baseY = layout.top + nativeY * layout.ratio;
  const centerX = layout.viewportWidth / 2;
  const centerY = layout.viewportHeight / 2;
  const cosine = Math.cos(layout.rotation);
  const sine = Math.sin(layout.rotation);
  const x = centerX + cosine * (baseX - centerX) - sine * (baseY - centerY);
  const y = centerY + sine * (baseX - centerX) + cosine * (baseY - centerY);
  const length =
    Math.max(0.2, Number(vehicleModel.length_m) || 1.0) * layout.pixelsPerMeter;
  const width =
    Math.max(0.15, Number(vehicleModel.width_m) || 0.68) *
    layout.pixelsPerMeter;
  element.hidden = false;
  if (element.style.width !== `${width}px`) element.style.width = `${width}px`;
  if (element.style.height !== `${length}px`)
    element.style.height = `${length}px`;
  // 车体每帧只写 transform，进入独立合成层。禁止写 left/top，否则浏览器可能
  // 重新计算绝对定位布局，形成“数据很新但视觉一卡一卡”的假延迟。
  // ROS yaw 以 +X 为零、逆时针增加；屏幕 Y 轴向下而车体图标默认朝上，故须
  // 转换为 pi/2 - yaw。只旋转车体，底图、点云和虚拟墙始终保持 map 朝向。
  const localYaw = Math.PI / 2 - vehicle.yaw;
  const transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%) rotate(${localYaw}rad)`;
  if (element.style.transform !== transform)
    element.style.transform = transform;
}
function vehiclePoseInMap() {
  // 小车端 C++ 已从 map -> base_* TF 得到位姿；浏览器只消费该最小实时结果。
  if (tfVehiclePose) {
    if (performance.now() - tfVehiclePose.receivedAt < LIVE_POSE_FALLBACK_MS)
      return tfVehiclePose;
  }
  return undefined;
}
function leaveOverviewAfterMovement(position) {
  if (!overviewUntilMovement || !position) return;
  if (!overviewPoseAnchor) {
    overviewPoseAnchor = { x: position.x, y: position.y };
    return;
  }
  if (
    Math.hypot(
      position.x - overviewPoseAnchor.x,
      position.y - overviewPoseAnchor.y,
    ) < INITIAL_OVERVIEW_MOVEMENT_M
  )
    return;
  overviewUntilMovement = false;
  mapView.pixelsPerMeter = undefined;
  mapView.followOffset = { x: 0, y: 0 };
}
function estimateLiveMotion(position, yaw, now) {
  const raw = {
    position: { x: Number(position.x), y: Number(position.y) },
    yaw,
  };
  const previous = latestLiveMotion;
  if (!previous) {
    latestLiveMotion = {
      ...raw,
      measuredAt: now,
      velocity: { x: 0, y: 0 },
      yawRate: 0,
    };
    return latestLiveMotion;
  }
  const distance = Math.hypot(
    raw.position.x - previous.position.x,
    raw.position.y - previous.position.y,
  );
  const yawDelta = normalizeAngle(raw.yaw - previous.yaw);
  const positionChanged = distance >= STATIC_POSE_POSITION_HOLD_M;
  const yawChanged = Math.abs(yawDelta) >= STATIC_POSE_YAW_HOLD_RAD;
  const changed = positionChanged || yawChanged;
  if (changed) {
    // 位置与航向独立提交：例如定位位置略有噪声但正在原地转向时，不能把该
    // 位置噪声一同写入；反之亦然。`latestLiveMotion` 是静止显示的可信锚点。
    const committed = {
      position: positionChanged ? raw.position : previous.position,
      yaw: yawChanged ? raw.yaw : previous.yaw,
    };
    const elapsedSeconds = (now - previous.measuredAt) / 1000;
    let velocity = { x: 0, y: 0 };
    let yawRate = 0;
    if (elapsedSeconds >= 0.01 && elapsedSeconds <= 0.8) {
      const vx = (committed.position.x - previous.position.x) / elapsedSeconds;
      const vy = (committed.position.y - previous.position.y) / elapsedSeconds;
      if (Math.hypot(vx, vy) <= 3.0) velocity = { x: vx, y: vy };
      const candidateYawRate =
        normalizeAngle(committed.yaw - previous.yaw) / elapsedSeconds;
      if (Math.abs(candidateYawRate) <= MAX_VEHICLE_YAW_RATE_RADPS)
        yawRate = candidateYawRate;
    }
    latestLiveMotion = { ...committed, measuredAt: now, velocity, yawRate };
  }
  // TF 偶发短暂停顿时，最多沿最后一个可信速度外推 300 ms；超过窗口立即停止，
  // 因而不会把图标平滑成与实车脱节的历史回放。
  const motionAge = now - latestLiveMotion.measuredAt;
  return {
    // 必须返回锚定后的位姿，而不是 raw。旧实现仅抑制了速度估计，位置仍被
    // 每个 60 Hz 微扰覆盖，因而静止小车依旧在地图上细微抖动。
    position: latestLiveMotion.position,
    yaw: latestLiveMotion.yaw,
    // 不能用每个 60 Hz 心跳包的 receivedAt 代替这个值；渲染层必须知道最后一帧
    // 真正改变的测量是什么时候到达，才可以平滑跨过 TF 的短暂停顿。
    motionMeasuredAt: latestLiveMotion.measuredAt,
    velocity:
      motionAge <= MAX_VEHICLE_PREDICTION_MS
        ? latestLiveMotion.velocity
        : { x: 0, y: 0 },
    yawRate:
      motionAge <= MAX_VEHICLE_PREDICTION_MS ? latestLiveMotion.yawRate : 0,
  };
}
function updateLivePose(message, sourceAgeMs = 0) {
  const position = message?.pose?.position;
  const orientation = message?.pose?.orientation;
  if (
    !position ||
    !orientation ||
    !Number.isFinite(Number(position.x)) ||
    !Number.isFinite(Number(position.y))
  )
    return;
  // C++ 已完成 map->base 查找；浏览器只处理专用紧凑位姿帧。
  livePoseUpdatedAt = performance.now();
  clientPerformance.poseApplied += 1;
  vehicleUpdatedAt = livePoseUpdatedAt;
  const motion = estimateLiveMotion(
    position,
    yawOf(orientation),
    livePoseUpdatedAt,
  );
  const stablePosition = motion.position;
  const yaw = motion.yaw;
  const { velocity, yawRate, motionMeasuredAt } = motion;
  livePoseSourceAgeMs = sourceAgeMs;
  tfVehiclePose = {
    position: stablePosition,
    orientation,
    yaw,
    source: "live",
    receivedAt: livePoseUpdatedAt,
    motionMeasuredAt,
    velocity,
    yawRate,
    sourceAgeMs,
  };
  // 轻量位姿是当前性能路径；它也必须能驱动概览 -> 随车视图，不能依赖
  // 轻量位姿首次到达即可从全图进入跟车视角，不能依赖其它 ROS 话题。
  leaveOverviewAfterMovement(stablePosition);
  updateDiagnostics();
  scheduleMapDraw();
  requestFollowAnimation();
  requestVehicleAnimation();
}
function telemetryHeader(data, expectedKind) {
  if (
    !(data instanceof ArrayBuffer) ||
    data.byteLength < TELEMETRY_HEADER_BYTES
  )
    return undefined;
  const view = new DataView(data);
  const magic = String.fromCharCode(
    view.getUint8(0),
    view.getUint8(1),
    view.getUint8(2),
    view.getUint8(3),
  );
  if (
    magic !== TELEMETRY_MAGIC ||
    view.getUint8(4) !== 1 ||
    view.getUint8(5) !== expectedKind
  )
    return undefined;
  return {
    view,
    sequence: view.getUint32(6, false),
    timestampNs: view.getBigUint64(10, false),
    pointCount: view.getUint16(18, false),
  };
}
function telemetrySourceAgeMs(timestampNs) {
  const sentAtMs = Number(timestampNs / 1000000n);
  const age = Date.now() - sentAtMs;
  // ROS 仿真时钟或未校时的浏览器不应把无意义的时间差误报为流故障。
  return Number.isFinite(age) && age >= 0 && age <= 5000 ? age : 0;
}
function updateTelemetryPose(data) {
  const header = telemetryHeader(data, TELEMETRY_POSE);
  if (
    !header ||
    header.pointCount !== 1 ||
    data.byteLength !== TELEMETRY_HEADER_BYTES + 12
  )
    return;
  const x = header.view.getFloat32(TELEMETRY_HEADER_BYTES, false);
  const y = header.view.getFloat32(TELEMETRY_HEADER_BYTES + 4, false);
  const yaw = header.view.getFloat32(TELEMETRY_HEADER_BYTES + 8, false);
  if (![x, y, yaw].every(Number.isFinite)) return;
  updateLivePose(
    {
      pose: {
        position: { x, y },
        orientation: { x: 0, y: 0, z: Math.sin(yaw / 2), w: Math.cos(yaw / 2) },
      },
    },
    telemetrySourceAgeMs(header.timestampNs),
  );
}
function updateTelemetryCloud(data) {
  const header = telemetryHeader(data, TELEMETRY_CLOUD);
  if (
    !header ||
    header.pointCount > POINT_LIMIT ||
    data.byteLength !== TELEMETRY_HEADER_BYTES + header.pointCount * 8
  )
    return;
  const packedMapPoints = new Float32Array(header.pointCount * 2);
  for (let index = 0; index < header.pointCount; index += 1) {
    const offset = TELEMETRY_HEADER_BYTES + index * 8;
    packedMapPoints[index * 2] = header.view.getFloat32(offset, false);
    packedMapPoints[index * 2 + 1] = header.view.getFloat32(offset + 4, false);
  }
  cloudUpdatedAt = performance.now();
  liveCloudSourceAgeMs = telemetrySourceAgeMs(header.timestampNs);
  cloud = {
    frameId: mapInfo?.frameId || "map",
    packedMapPoints,
    mapPointCount: header.pointCount,
  };
  recordCloudFrame();
  updateDiagnostics();
}
function updateTelemetryCostmap(data) {
  const header = telemetryHeader(data, TELEMETRY_COSTMAP);
  if (
    !header ||
    header.pointCount === 0 ||
    header.pointCount > COSTMAP_MAX_CELLS ||
    data.byteLength !==
      TELEMETRY_HEADER_BYTES + COSTMAP_META_BYTES + header.pointCount
  )
    return;
  const offset = TELEMETRY_HEADER_BYTES;
  const originX = header.view.getFloat32(offset, false);
  const originY = header.view.getFloat32(offset + 4, false);
  const originYaw = header.view.getFloat32(offset + 8, false);
  const resolution = header.view.getFloat32(offset + 12, false);
  const width = header.view.getUint16(offset + 16, false);
  const height = header.view.getUint16(offset + 18, false);
  if (
    width === 0 ||
    height === 0 ||
    width * height !== header.pointCount ||
    ![originX, originY, originYaw, resolution].every(Number.isFinite) ||
    resolution <= 0
  )
    return;
  costmap = {
    width,
    height,
    resolution,
    origin: { x: originX, y: originY, yaw: originYaw },
    cells: new Uint8Array(data, offset + COSTMAP_META_BYTES, header.pointCount),
  };
  costmapUpdatedAt = performance.now();
  liveCostmapSourceAgeMs = telemetrySourceAgeMs(header.timestampNs);
  scheduleCostmapExpiry();
  renderCostmap();
  updateDiagnostics();
  scheduleMapDraw();
}
function scheduleLatestCloudPacket(data) {
  clientPerformance.cloudPackets += 1;
  pendingCloudPacket = { data, receivedAt: performance.now() };
  if (cloudPacketQueued) return;
  cloudPacketQueued = true;
  requestAnimationFrame(flushLatestCloudPacket);
}
function flushLatestCloudPacket() {
  cloudPacketQueued = false;
  const packet = pendingCloudPacket;
  pendingCloudPacket = undefined;
  if (
    packet &&
    performance.now() - packet.receivedAt <= CLOUD_PACKET_MAX_AGE_MS
  ) {
    try {
      updateTelemetryCloud(packet.data);
    } catch (_) {
      /* 单帧异常不影响下一帧。 */
    }
  }
  if (pendingCloudPacket && !cloudPacketQueued) {
    cloudPacketQueued = true;
    requestAnimationFrame(flushLatestCloudPacket);
  }
}
function scheduleLatestCostmapPacket(data) {
  clientPerformance.costmapPackets += 1;
  pendingCostmapPacket = { data, receivedAt: performance.now() };
  if (costmapPacketQueued) return;
  costmapPacketQueued = true;
  requestAnimationFrame(flushLatestCostmapPacket);
}
function flushLatestCostmapPacket() {
  costmapPacketQueued = false;
  const packet = pendingCostmapPacket;
  pendingCostmapPacket = undefined;
  if (
    packet &&
    performance.now() - packet.receivedAt <= COSTMAP_PACKET_MAX_AGE_MS
  ) {
    try {
      updateTelemetryCostmap(packet.data);
    } catch (_) {
      /* 不完整或非法的单帧不能影响后续最新栅格。 */
    }
  }
  if (pendingCostmapPacket && !costmapPacketQueued) {
    costmapPacketQueued = true;
    requestAnimationFrame(flushLatestCostmapPacket);
  }
}
function scheduleLatestPosePacket(data) {
  clientPerformance.posePackets += 1;
  pendingPosePacket = { data, receivedAt: performance.now() };
  if (posePacketQueued) return;
  posePacketQueued = true;
  requestAnimationFrame(flushLatestPosePacket);
}
function flushLatestPosePacket() {
  posePacketQueued = false;
  const packet = pendingPosePacket;
  pendingPosePacket = undefined;
  if (
    packet &&
    performance.now() - packet.receivedAt <= POSE_PACKET_MAX_AGE_MS
  ) {
    try {
      updateTelemetryPose(packet.data);
    } catch (_) {
      /* 保持观测连接可用。 */
    }
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
  const mapText = mapInfo
    ? `${mapInfo.width} × ${mapInfo.height} 地图`
    : "等待地图";
  const vehicle = vehiclePoseInMap();
  const inMap =
    vehicle?.position &&
    mapInfo &&
    vehicle.position.x >= mapInfo.origin.x &&
    vehicle.position.x <=
      mapInfo.origin.x + mapInfo.width * mapInfo.resolution &&
    vehicle.position.y >= mapInfo.origin.y &&
    vehicle.position.y <=
      mapInfo.origin.y + mapInfo.height * mapInfo.resolution;
  const source = "实时位姿";
  const poseText = vehicle
    ? inMap
      ? `${source} x ${vehicle.position.x.toFixed(2)} · y ${vehicle.position.y.toFixed(2)} · 小车已绘制`
      : `${source}不在当前地图范围`
    : "等待实时位姿";
  const cloudAge = cloud
    ? Math.max(0, (performance.now() - cloudUpdatedAt) / 1000)
    : 0;
  const cloudCount = cloud?.mapPointCount ?? cloud?.mapPoints?.length ?? 0;
  const cloudText = pauseCloudForCamera()
    ? cloud
      ? `图像低延迟优先，点云暂停 · 最近 ${cloudCount} 点`
      : "图像低延迟优先，点云暂停"
    : cloud
    ? `${cloudCount} 个地图点 · ${cloudAge.toFixed(1)} 秒前`
    : "等待点云";
  const costmapAge = costmapIsCurrent()
    ? Math.max(0, (performance.now() - costmapUpdatedAt) / 1000)
    : 0;
  const costmapText = !costmapVisible
    ? "局部代价地图已隐藏"
    : costmapIsCurrent()
      ? `局部代价地图 ${costmap.width} × ${costmap.height} · ${costmapAge.toFixed(1)} 秒前`
      : "等待局部代价地图";
  const wallText = virtualWalls.length
    ? `${virtualWalls.length} 段虚拟墙`
    : wallStatus;
  setText(
    "mapDiagnostics",
    `${mapText} · ${poseText} · ${cloudText} · ${costmapText} · ${wallText}`,
  );
}

function pauseCloudForCamera() {
  return false;
}
function invalidateMapScopedCloud() {
  // map 坐标系在切图时会重置。丢弃旧图的待解码/待绘制扫描，并给渲染器加
  // generation 栅栏，杜绝上一张图的异步点云在新图就绪后闪现一帧。
  mapGeneration += 1;
  cloud = undefined;
  pendingCloudPacket = undefined;
  pendingCloudFrame = undefined;
  costmap = undefined;
  costmapUpdatedAt = 0;
  pendingCostmapPacket = undefined;
  window.clearTimeout(costmapExpiryTimer);
  if (cloudRenderTimer) {
    window.clearTimeout(cloudRenderTimer);
    cloudRenderTimer = undefined;
  }
  renderCloudPoints();
  clearCostmapRenderer();
}
function recordCloudFrame() {
  const now = performance.now();
  // 仅保留最新扫描。渲染间隔内覆盖尚未处理的帧，禁止形成延迟积压或透明拖影。
  const packedPoints =
    cloud.packedMapPoints || packCloudPoints(cloud.mapPoints || []);
  if (
    queueCloudRender({
      receivedAt: now,
      points: packedPoints,
      generation: mapGeneration,
    })
  )
    return;
  scheduleCloudRasterBuild();
}
function scheduleCloudRasterBuild() {
  // 拖拽和缩放时点云并不需要重新投影；保留最新数据，交互结束后再一次性刷新。
  // 这样大点云的 PixiJS 图形更新不会抢走鼠标事件和 CSS 合成帧。
  if (mapInteractionActive) {
    cloudRasterPending = true;
    return;
  }
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
  if (!mapInfo) {
    renderCloudPoints();
    return;
  }
  renderCloudPoints(packedPoints || packCloudPoints(mapPoints || []));
}
async function refreshActiveMap(observation) {
  // active_map.json 由既有轨迹记录器写入；点云/位姿链路不触碰地图缓存。
  const mapId = observation.active_map_id;
  if (!mapId || mapId === loadedMapId || mapId === requestedActiveMapId) return;
  requestedActiveMapId = mapId;
  try {
    const layers = await request(
      `/api/observation/maps/${encodeURIComponent(mapId)}/layers`,
    );
    virtualWalls = Array.isArray(layers.virtual_walls)
      ? layers.virtual_walls
      : [];
    loadCachedMap(mapId, layers.map);
  } catch (_) {
    // 网络短暂失败不能把这次切图永久标为“已处理”；下一次轻量标记检查会重试。
    reportObservationOnce(
      `cached-map-${mapId}`,
      "WARNING",
      `地图缓存层读取失败：map_id=${mapId}。请检查 maps_cache 与轨迹记录器。`,
    );
    requestedActiveMapId = undefined;
    virtualWalls = [];
  }
  updateDiagnostics();
  scheduleMapDraw();
}
function loadCachedMap(mapId, metadata) {
  if (
    mapId === loadedMapId ||
    !metadata?.width ||
    !metadata?.height ||
    !(metadata.resolution > 0) ||
    !Array.isArray(metadata.origin)
  )
    return;
  loadedMapId = mapId;
  const image = new Image();
  image.decoding = "async";
  image.onload = () => {
    if (loadedMapId !== mapId) return;
    invalidateMapScopedCloud();
    mapInfo = {
      width: Number(metadata.width),
      height: Number(metadata.height),
      resolution: Number(metadata.resolution),
      origin: {
        x: Number(metadata.origin[0]) || 0,
        y: Number(metadata.origin[1]) || 0,
      },
      frameId: normalizeFrame(metadata.frame_id) || "map",
    };
    mapTexture?.destroy(true);
    mapTexture = Texture.from(image);
    $("mapEmpty").hidden = true;
    // 进入观测页且车辆尚未提供定位时，优先展示完整地图；运行中切图则延续随车视角。
    if (!vehiclePoseInMap()?.position) {
      overviewUntilMovement = true;
      overviewPoseAnchor = undefined;
      mapView.pixelsPerMeter = undefined;
      mapView.center = undefined;
      mapView.followOffset = { x: 0, y: 0 };
    }
    renderStaticWorld();
    scheduleCloudRasterBuild();
    updateDiagnostics();
    scheduleMapDraw();
  };
  image.onerror = () => {
    if (loadedMapId === mapId) {
      loadedMapId = undefined;
      setText(
        "mapDiagnostics",
        "当前地图缓存读取失败；请在测试任务中重新开启轨迹记录。",
      );
      reportObservationOnce(
        `cached-map-preview-${mapId}`,
        "WARNING",
        `地图缓存预览读取失败：map_id=${mapId}；请在测试任务中重新开启轨迹记录。`,
      );
    }
  };
  image.src = `/api/observation/maps/${encodeURIComponent(mapId)}/preview.png`;
}

function closeTelemetryConnections() {
  telemetryConnectionGeneration += 1;
  for (const lane of ["cloud", "pose", "costmap"]) {
    window.clearTimeout(telemetryReconnectTimers[lane]);
    telemetryReconnectTimers[lane] = undefined;
    telemetryLaneOpen[lane] = false;
    telemetryLaneAttempts[lane] = 0;
  }
  cloudSocket?.close();
  poseSocket?.close();
  costmapSocket?.close();
  cloudSocket = undefined;
  poseSocket = undefined;
  costmapSocket = undefined;
}
function connectTelemetry(payload) {
  const port = Number(payload?.telemetry?.websocket_port);
  const rawHost = String(location.hostname || "").trim();
  if (!Number.isInteger(port) || port < 1 || port > 65535 || !rawHost)
    throw new Error("未取得 Aletheia 实时遥测地址");
  // 小车控制台当前在受控局域网使用 HTTP；HTTPS 页面不能接入明文 ws，明确报错
  // 而不是误把异常表现为“等待点云”。
  if (location.protocol === "https:")
    throw new Error(
      "当前控制台使用 HTTPS，不能连接小车的明文实时遥测 WebSocket。请通过 HTTP 控制台访问。",
    );
  const host = rawHost.includes(":") ? `[${rawHost}]` : rawHost;
  const base = `ws://${host}:${port}`;
  closeTelemetryConnections();
  const generation = telemetryConnectionGeneration;
  const updateConnection = () => {
    if (telemetryLaneOpen.cloud && telemetryLaneOpen.pose) {
      setText("connectionState", "已连接");
      setText("sideState", "本地实时数据");
      setText(
        "connectionDetail",
        telemetryLaneOpen.costmap || mobileConsoleEnabled()
          ? "专用二进制遥测 · 点云 / 位姿 / 局部代价地图"
          : "点云与位姿已连接；局部代价地图重连中",
      );
    } else if (telemetryLaneOpen.cloud || telemetryLaneOpen.pose) {
      setText("connectionState", "部分连接");
      setText(
        "connectionDetail",
        telemetryLaneOpen.cloud
          ? "点云已连接，正在重连位姿"
          : "位姿已连接，正在重连点云",
      );
    } else {
      setText("connectionState", "重连中");
      setText("connectionDetail", "正在恢复专用实时遥测…");
    }
  };
  const openLane = (lane, path, apply, label) => {
    const socket = new WebSocket(`${base}${path}`);
    socket.binaryType = "arraybuffer";
    if (lane === "cloud") cloudSocket = socket;
    else if (lane === "pose") poseSocket = socket;
    else costmapSocket = socket;
    socket.addEventListener("open", () => {
      if (generation !== telemetryConnectionGeneration) {
        socket.close();
        return;
      }
      telemetryLaneOpen[lane] = true;
      telemetryLaneAttempts[lane] = 0;
      updateConnection();
      resolveObservationDiagnostic(
        `telemetry-${path}`,
        `${label}实时通道已恢复。`,
      );
      reportObservation("INFO", `${label}实时通道已连接。`);
    });
    socket.addEventListener("message", (event) => {
      if (event.data instanceof ArrayBuffer) apply(event.data);
    });
    socket.addEventListener("error", () => {
      if (generation === telemetryConnectionGeneration)
        reportObservationOnce(
          `telemetry-${path}`,
          "ERROR",
          `${label}实时通道连接失败：${base}${path}。请检查小车端遥测网关。`,
        );
    });
    socket.addEventListener("close", (event) => {
      if (generation !== telemetryConnectionGeneration) return;
      telemetryLaneOpen[lane] = false;
      updateConnection();
      const delay = Math.min(3000, 250 * 2 ** telemetryLaneAttempts[lane]);
      telemetryLaneAttempts[lane] = Math.min(
        telemetryLaneAttempts[lane] + 1,
        4,
      );
      window.clearTimeout(telemetryReconnectTimers[lane]);
      telemetryReconnectTimers[lane] = window.setTimeout(() => {
        if (generation === telemetryConnectionGeneration)
          openLane(lane, path, apply, label);
      }, delay);
    });
    return socket;
  };
  setText("connectionState", "连接中");
  setText("connectionDetail", "正在连接专用实时遥测…");
  openLane("cloud", "/cloud", scheduleLatestCloudPacket, "点云");
  openLane("pose", "/pose", scheduleLatestPosePacket, "位姿");
  if (!mobileConsoleEnabled())
    openLane("costmap", "/costmap", scheduleLatestCostmapPacket, "局部代价地图");
}
async function main() {
  initializeTheme();
  window.RYAletheiaShell?.install();
  setupMobileConsole();
  setupMapInteraction();
  const costmapToggle = $("costmapVisible");
  costmapVisible = costmapToggle?.checked !== false;
  costmapToggle?.addEventListener("change", () => {
    costmapVisible = costmapToggle.checked;
    renderCostmap();
    updateDiagnostics(true);
    scheduleMapDraw(true);
  });
  $("webrtcVideoToggle")?.addEventListener("click", toggleWebRtcVideo);
  startWebRtcVideoStatus();
  await initializePixiRenderer();
  try {
    const [settings, upgrade] = await Promise.all([
      request("/api/settings"),
      request("/api/system/upgrade"),
    ]);
    setText(
      "consoleVersion",
      upgrade.current_version ? `v${upgrade.current_version}` : "开发版",
    );
    if (!settings.live_observation?.enabled) {
      setText("connectionState", "未启用");
      setText("connectionDetail", "请先在运行配置启用实时运行观测。");
      return;
    }
    const models = Array.isArray(settings.live_observation?.vehicle_models)
      ? settings.live_observation.vehicle_models
      : [];
    vehicleModel =
      models.find(
        (item) => item.id === settings.live_observation?.active_vehicle_model,
      ) ||
      models[0] ||
      vehicleModel;
    // 必须由受控接口确认专用遥测已启动；不能因“本机端口可达”接入外部服务。
    let ready = await request("/api/observation/start", { method: "POST" });
    for (
      let attempt = 0;
      !ready.telemetry?.online && attempt < 12;
      attempt += 1
    ) {
      setText("connectionState", "遥测启动中");
      setText("connectionDetail", `正在等待本地遥测网关（${attempt + 1}/12）`);
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      ready = await request("/api/observation");
    }
    if (!ready.telemetry?.online) {
      setText("connectionState", "遥测未就绪");
      setText("connectionDetail", "请在诊断日志中检查实时遥测网关启动记录。");
      return;
    }
    await refreshActiveMap(ready);
    connectTelemetry(ready);
    window.setInterval(() => {
      reportClientMetrics();
      request("/api/observation/heartbeat", { method: "POST" })
        .then(refreshActiveMap)
        .catch(() => {});
    }, 5000);
    window.setInterval(() => {
      request("/api/observation/active-map")
        .then(refreshActiveMap)
        .catch(() => {});
    }, ACTIVE_MAP_SYNC_MS);
  } catch (error) {
    setText("connectionState", "不可用");
    setText("connectionDetail", error.message);
    reportObservation("ERROR", `实时观测初始化失败：${error.message}`);
  }
}
window.addEventListener("error", (event) => {
  const location = event.filename
    ? `${event.filename}:${event.lineno || 0}:${event.colno || 0}`
    : "未知位置";
  const detail = event.error?.message || event.message || "未知页面异常";
  reportObservationOnce(
    `page-error-${location}-${detail}`,
    "ERROR",
    `实时观测页面异常：${detail}（${location}）。`,
  );
});
window.addEventListener("unhandledrejection", (event) => {
  const detail =
    event.reason?.message || String(event.reason || "未知 Promise 异常");
  reportObservationOnce(
    `page-rejection-${detail}`,
    "ERROR",
    `实时观测页面未处理 Promise 异常：${detail}`,
  );
});
window.addEventListener("beforeunload", () => {
  window.clearInterval(webrtcStatusTimer);
  [...webrtcPlayers.keys()].forEach(destroyWebRtcPlayer);
  stopRenderScheduling();
  closeTelemetryConnections();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopRenderScheduling();
  else if (mapInfo) scheduleMapDraw();
});
main();
