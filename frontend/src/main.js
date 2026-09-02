import {
  createApp,
  computed,
  onMounted,
  ref,
} from "vue/dist/vue.esm-bundler.js";
import "../../autodrive_console/web/styles.css";
import "../../autodrive_console/web/refinement.css";
import "../../autodrive_console/web/page_views.css";
import "./runtimeSettings.css";
import "../../autodrive_console/web/app_shell.css";
import "../../autodrive_console/web/app_shell.js";

const request = async (url, options = {}) => {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(body.error || `请求失败（HTTP ${response.status}）`);
  return body;
};
function initializeTheme() {
  const key = "ry-aletheia-theme";
  const apply = () => {
    const light = localStorage.getItem(key) === "light";
    document.body.classList.toggle("theme-light", light);
    document.documentElement.style.colorScheme = light ? "light" : "dark";
  };
  document.querySelector(".brand .mark")?.addEventListener("click", () => {
    localStorage.setItem(
      key,
      document.body.classList.contains("theme-light") ? "dark" : "light",
    );
    apply();
  });
  apply();
}
function normalizeCaseWorkspaceLabel() {
  document.querySelectorAll('a[href="/case-library.html"]').forEach((link) => {
    const icon = link.querySelector("span");
    link.textContent = "";
    if (icon) link.appendChild(icon);
    link.append("测试用例管理");
  });
}

createApp({
  setup() {
    const taskDirectory = ref("");
    const commandTimeout = ref(8);
    const taskExecutionTimeout = ref(900);
    const observationEnabled = ref(false);
    const vehicleModels = ref([]);
    const activeVehicleModel = ref("");
    const settingsMessage = ref("");
    const upgrade = ref({ supported: false });
    const consoleVersion = ref("版本读取中");
    const selectedFile = ref(null);
    const upgradeMessage = ref("");
    const progress = ref("");
    const saving = ref(false);
    const upgrading = ref(false);
    const fileInput = ref(null);
    const upgradeState = computed(() =>
      upgrade.value.supported ? "可升级" : "不可用",
    );
    const upgradeClass = computed(
      () => `badge ${upgrade.value.supported ? "" : "muted"}`,
    );
    const selectedFileText = computed(() =>
      selectedFile.value
        ? `${selectedFile.value.name} · ${(selectedFile.value.size / 1024 / 1024).toFixed(1)} MiB`
        : "或点击此处选择 ZIP 文件",
    );
    const canUpgrade = computed(
      () => upgrade.value.supported && selectedFile.value && !upgrading.value,
    );
    function navigate(path) {
      if (window.location.port === "5173") {
        // 全部预览路由保持在 Vite；兼容页面由 Vite 代理至本地后端。
        if (path === "/") window.location.assign("/dashboard.html");
        else window.location.assign(path);
        return;
      }
      window.location.assign(path === "/" ? "/vue/dashboard.html" : path);
    }
    function applySettings(data) {
      taskDirectory.value = data.task_directory;
      commandTimeout.value = data.command_timeout_s;
      taskExecutionTimeout.value = Number(data.task_execution_timeout_s || 900);
      observationEnabled.value = Boolean(data.live_observation?.enabled);
      vehicleModels.value = Array.isArray(data.live_observation?.vehicle_models)
        ? data.live_observation.vehicle_models.map((model) => ({ ...model }))
        : [];
      activeVehicleModel.value =
        data.live_observation?.active_vehicle_model ||
        vehicleModels.value[0]?.id ||
        "";
    }
    async function loadSettings() {
      try {
        applySettings(await request("/api/settings", { cache: "no-store" }));
      } catch (error) {
        settingsMessage.value = error.message;
      }
    }
    async function loadUpgrade() {
      try {
        upgrade.value = await request("/api/system/upgrade");
        const version = String(upgrade.value.current_version || "").trim();
        consoleVersion.value =
          version && version !== "开发版" ? `v${version}` : "开发版";
      } catch (error) {
        upgradeMessage.value = error.message;
      }
    }
    function observationPayload() {
      return {
        enabled: observationEnabled.value,
        idle_stop_seconds: 45,
        vehicle_models: vehicleModels.value.map((model) => ({
          id: String(model.id || "").trim(),
          name: String(model.name || "").trim(),
          length_m: Number(model.length_m),
          width_m: Number(model.width_m),
        })),
        active_vehicle_model: activeVehicleModel.value,
      };
    }
    async function saveSettings() {
      saving.value = true;
      settingsMessage.value = "";
      try {
        applySettings(
          await request("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              task_directory: taskDirectory.value.trim(),
              command_timeout_s: Number(commandTimeout.value),
              task_execution_timeout_s: Number(taskExecutionTimeout.value),
              live_observation: observationPayload(),
            }),
          }),
        );
        settingsMessage.value = "本机运行配置已保存。";
      } catch (error) {
        settingsMessage.value = error.message;
      } finally {
        saving.value = false;
      }
    }
    function addVehicleModel() {
      const used = new Set(vehicleModels.value.map((model) => model.id));
      let suffix = vehicleModels.value.length + 1;
      while (used.has(`vehicle-${suffix}`)) suffix += 1;
      const model = {
        id: `vehicle-${suffix}`,
        name: `自定义车型 ${suffix}`,
        length_m: 1.0,
        width_m: 0.68,
      };
      vehicleModels.value.push(model);
      activeVehicleModel.value = model.id;
    }
    function removeVehicleModel(index) {
      if (vehicleModels.value.length <= 1) {
        settingsMessage.value = "车型库至少需要保留一个车型。";
        return;
      }
      const [removed] = vehicleModels.value.splice(index, 1);
      if (activeVehicleModel.value === removed.id)
        activeVehicleModel.value = vehicleModels.value[0].id;
    }
    function repairActiveVehicle(model) {
      if (
        !vehicleModels.value.some(
          (item) => item.id === activeVehicleModel.value,
        )
      )
        activeVehicleModel.value = model.id;
    }
    function chooseFile(file) {
      if (!file) return;
      if (!file.name.toLowerCase().endsWith(".zip")) {
        upgradeMessage.value = "请选择 .zip 格式的离线升级包。";
        return;
      }
      selectedFile.value = file;
      upgradeMessage.value =
        "升级包已选择，点击“校验并应用升级”后将自动重启控制台。";
    }
    function waitForUpgradeRestart(expectedVersion) {
      const startedAt = Date.now();
      const probe = async () => {
        progress.value = `正在等待新版本启动（${Math.round((Date.now() - startedAt) / 1000)}/30 秒）`;
        try {
          const response = await fetch(
            `/api/system/upgrade?restartProbe=${Date.now()}`,
            { cache: "no-store" },
          );
          const body = await response.json().catch(() => ({}));
          // 旧进程在 shutdown 排队期间也可能短暂返回 200。必须确认目标版本已运行，
          // 不能仅依据 HTTP 成功就刷新，否则浏览器会回到即将退出的旧页面。
          if (
            response.ok &&
            String(body.current_version || "") === String(expectedVersion || "")
          ) {
            window.location.replace(
              `${window.location.pathname}?upgraded=${encodeURIComponent(expectedVersion)}&t=${Date.now()}`,
            );
            return;
          }
        } catch (_) {
          /* 重启窗口内连接中断是正常现象，继续探测。 */
        }
        if (Date.now() - startedAt < 30000) {
          setTimeout(probe, 1000);
          return;
        }
        progress.value = "";
        upgradeMessage.value = `升级请求已提交，但 30 秒内未确认版本 ${expectedVersion} 已启动；请重新打开工具并核对版本号。`;
        upgrading.value = false;
      };
      setTimeout(probe, 700);
    }
    function uploadUpgrade() {
      if (
        !canUpgrade.value ||
        !window.confirm(
          `确认应用升级包“${selectedFile.value.name}”？\n\n将校验发布签名与文件完整性，备份当前程序，再自动重启控制台。`,
        )
      )
        return;
      upgrading.value = true;
      progress.value = "正在上传 0%";
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/system/upgrade");
      xhr.setRequestHeader("Content-Type", "application/zip");
      xhr.setRequestHeader("X-Upgrade-Filename", selectedFile.value.name);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable)
          progress.value = `正在上传 ${Math.round((event.loaded / event.total) * 100)}%`;
      };
      xhr.onerror = () => {
        upgradeMessage.value =
          "升级连接中断，当前程序未确认替换；请刷新页面检查当前版本。";
        progress.value = "";
        upgrading.value = false;
      };
      xhr.onload = () => {
        let data = {};
        try {
          data = JSON.parse(xhr.responseText);
        } catch (_) {}
        if (xhr.status >= 200 && xhr.status < 300) {
          progress.value = "校验完成，正在重启";
          upgradeMessage.value = data.message || "升级完成，控制台正在重启。";
          waitForUpgradeRestart(data.version);
        } else {
          progress.value = "";
          upgradeMessage.value = data.error || `升级失败（HTTP ${xhr.status}）`;
          upgrading.value = false;
        }
      };
      xhr.send(selectedFile.value);
    }
    onMounted(() => {
      initializeTheme();
      normalizeCaseWorkspaceLabel();
      window.RYAletheiaShell?.install();
      loadSettings();
      loadUpgrade();
    });
    return {
      taskDirectory,
      commandTimeout,
      taskExecutionTimeout,
      observationEnabled,
      vehicleModels,
      activeVehicleModel,
      settingsMessage,
      upgrade,
      consoleVersion,
      upgradeMessage,
      progress,
      saving,
      upgrading,
      fileInput,
      upgradeState,
      upgradeClass,
      selectedFileText,
      canUpgrade,
      navigate,
      saveSettings,
      addVehicleModel,
      removeVehicleModel,
      repairActiveVehicle,
      chooseFile,
      uploadUpgrade,
    };
  },
  template: `
    <aside><div class="brand"><div class="mark"><svg viewBox="0 0 32 32"><path d="M5 24 16 4l11 20-11 4z"/><path d="m11 21 5-10 5 10-5 2z"/></svg></div><div><b>RY <span>Aletheia</span></b><small>AUTOMATED TEST SYSTEM</small><span class="brand-version">{{ consoleVersion }}</span></div></div><nav><a href="/" @click.prevent="navigate('/')"><span>⌘</span>任务指挥台</a><a href="/deployment.html" @click.prevent="navigate('/deployment.html')"><span>◇</span>部署建图</a><a href="/live-observation.html" @click.prevent="navigate('/live-observation.html')"><span>◉</span>实时运行观测</a><a href="/case-library.html" @click.prevent="navigate('/case-library.html')"><span>▤</span>用例资产库</a><a href="/reports.html" @click.prevent="navigate('/reports.html')"><span>◫</span>报告中心</a><a class="active" href="/runtime-settings.html"><span>⚙</span>运行配置</a></nav><div class="side-status"><span class="pulse"></span> LOCAL RUNTIME<br><strong>受控本机配置</strong><a class="side-diagnostic-link" href="/tool-logs.html" @click.prevent="navigate('/tool-logs.html')">诊断日志</a></div></aside>
    <main class="page-main"><header class="page-header"><div><p class="eyebrow">LOCAL RUNTIME / GOVERNED SETTINGS</p><h1>运行配置</h1><p class="sub">本机运行、实时观测与离线升级配置。</p></div></header><section class="page-grid">
      <article class="panel span-7"><div class="panel-title"><div><p class="eyebrow">CONSOLE SETTINGS</p><h2>本机运行参数</h2></div><button class="page-top-action" type="button" :disabled="saving" @click="saveSettings">{{ saving ? '正在保存' : '保存配置' }}</button></div><div class="settings-form"><label>任务目标目录<input v-model="taskDirectory"></label><label>Supervisor 查询超时（秒）<input v-model.number="commandTimeout" type="number" min="1" max="120"></label><label>单轮任务服务超时（秒）<input v-model.number="taskExecutionTimeout" type="number" min="60" max="3600"></label></div><p class="inline-message">{{ settingsMessage }}</p></article>
      <article class="panel span-5"><p class="eyebrow">DEPENDENCY ORCHESTRATION</p><h2>测试依赖编排</h2><p class="config-note">在任务指挥台配置测试依赖节点与启动顺序。</p></article>
      <article class="panel span-7"><p class="eyebrow">LIVE OBSERVATION / LOCAL TELEMETRY</p><h2>实时运行观测</h2><div class="settings-form"><label class="checkbox-setting"><input v-model="observationEnabled" type="checkbox"> 启用按需实时观测</label></div></article>
      <article class="panel span-5"><p class="eyebrow">OBSERVATION CONNECTION</p><h2>专用遥测边界</h2><p class="config-note">实时观测页仅接收当前小车的专用点云与位姿遥测；地图缓存和 WebRTC 视频维持各自独立链路。</p></article>
      <article class="panel vehicle-library-panel"><div class="panel-title"><div><p class="eyebrow">VEHICLE PROFILE / LIVE OUTLINE</p><h2>车型选择</h2></div><div class="panel-actions"><button class="outline-button" type="button" @click="addVehicleModel">＋ 添加车型</button><button class="page-top-action" type="button" :disabled="saving" @click="saveSettings">{{ saving ? '正在保存' : '保存车型选择' }}</button></div></div><div class="vehicle-model-grid"><label>当前运行车型<select v-model="activeVehicleModel"><option v-for="model in vehicleModels" :key="model.id" :value="model.id">{{ model.name }}</option></select></label></div><div class="vehicle-model-row" v-for="(model, index) in vehicleModels" :key="model.id"><label>标识<input v-model="model.id" maxlength="64" @input="repairActiveVehicle(model)"></label><label>车型名称<input v-model="model.name" maxlength="48"></label><label>车长（m）<input v-model.number="model.length_m" type="number" min="0.2" max="5" step="0.01"></label><label>车宽（m）<input v-model.number="model.width_m" type="number" min="0.15" max="3" step="0.01"></label><button class="danger-outline" type="button" :disabled="vehicleModels.length <= 1" @click="removeVehicleModel(index)">删除</button></div></article>
      <article class="panel span-7 upgrade-panel"><div class="panel-title"><div><p class="eyebrow">OFFLINE CONSOLE UPGRADE</p><h2>工具离线升级</h2></div><span :class="upgradeClass">{{ upgradeState }}</span></div><input ref="fileInput" class="visually-hidden" type="file" accept=".zip,application/zip" @change="chooseFile($event.target.files[0])"><label class="upgrade-dropzone" @dragover.prevent @drop.prevent="chooseFile($event.dataTransfer.files[0])" @click="fileInput.click()"><span>⇧</span><b>拖入离线升级包</b><small>{{ selectedFileText }}</small></label><div class="upgrade-actions"><button class="page-top-action" type="button" :disabled="!canUpgrade" @click="uploadUpgrade">{{ upgrading ? '正在升级' : '校验并应用升级' }}</button><span>{{ progress }}</span></div><p class="inline-message">{{ upgradeMessage }}</p><p class="upgrade-meta">当前工具版本：<code>{{ consoleVersion }}</code> · 发布者真实性：<code>Ed25519 签名</code> · 文件完整性：<code>SHA-256</code></p></article>
      <article class="panel span-5"><p class="eyebrow">UPGRADE SAFETY</p><h2>升级边界</h2><p class="config-note">有执行中、取消中或等待人工恢复的测试计划时，控制台会拒绝升级。校验失败不会替换当前程序。</p></article>
    </section></main>`,
}).mount("#app");
