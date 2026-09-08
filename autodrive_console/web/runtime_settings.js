import { requestJson } from "./platform/http.js";

const $ = id => document.getElementById(id);
let upgradeSupported = false;
let selectedUpgradeFile = null;

async function loadSettings() {
  try {
    const data = await requestJson('/api/settings', {}, { errorMessage: '配置读取失败' });
    $('taskDirectory').value = data.task_directory; $('commandTimeout').value = data.command_timeout_s; $('elevatorWaitTimeout').value = data.elevator_wait_timeout_s; $('taskExecutionTimeout').value = data.task_execution_timeout_s;
  } catch (error) { $('settingsMessage').textContent = error.message; }
}
function updateUpgradeButton() { $('applyUpgrade').disabled = !upgradeSupported || !selectedUpgradeFile; }
async function loadUpgradeStatus() {
  try {
    const data = await requestJson('/api/system/upgrade', {}, { errorMessage: '升级状态读取失败' });
    upgradeSupported = Boolean(data.supported);
    $('upgradeState').textContent = upgradeSupported ? '可升级' : '不可用';
    $('upgradeState').className = `badge ${upgradeSupported ? '' : 'muted'}`;
    $('upgradeCurrentMd5').textContent = 'Ed25519 签名与 SHA-256 校验';
    $('upgradeMessage').textContent = '';
    updateUpgradeButton();
  } catch (error) { $('upgradeState').textContent = '检查失败'; $('upgradeMessage').textContent = error.message; }
}
function selectUpgradeFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.zip')) { $('upgradeMessage').textContent = '请选择 .zip 格式的离线升级包。'; return; }
  selectedUpgradeFile = file;
  $('upgradeFileName').textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MiB`;
  $('upgradeMessage').textContent = '升级包已选择，点击“校验并应用升级”后将自动重启控制台。'; updateUpgradeButton();
}
function waitForUpgradeRestart() {
  const startedAt = Date.now(); const timeoutMs = 30000;
  const probe = async () => {
    const elapsed = Math.round((Date.now() - startedAt) / 1000);
    $('upgradeProgress').textContent = `正在等待新版本启动（${elapsed}/30 秒）`;
    try {
      const response = await fetch(`/api/system/upgrade?restartProbe=${Date.now()}`, { cache: 'no-store' });
      if (response.ok) { window.location.reload(); return; }
    } catch (_) { /* 旧进程已退出或新进程尚未监听，继续探测。 */ }
    if (Date.now() - startedAt < timeoutMs) { setTimeout(probe, 1000); return; }
    $('upgradeProgress').textContent = '';
    $('upgradeMessage').textContent = '升级已完成，但 30 秒内未检测到新版本响应。请以普通账户在终端执行 ry-aletheia 后刷新页面。';
    updateUpgradeButton();
  };
  setTimeout(probe, 500);
}
function uploadUpgrade() {
  if (!selectedUpgradeFile || !upgradeSupported) return;
  if (!window.confirm(`确认应用升级包“${selectedUpgradeFile.name}”？\n\n将先校验 Ed25519 发布签名和 SHA-256，备份当前程序，再自动重启控制台。`)) return;
  const button = $('applyUpgrade'); const request = new XMLHttpRequest(); button.disabled = true; $('upgradeProgress').textContent = '正在上传 0%';
  request.open('POST', '/api/system/upgrade'); request.setRequestHeader('Content-Type', 'application/zip'); request.setRequestHeader('X-Upgrade-Filename', selectedUpgradeFile.name);
  request.upload.onprogress = event => { if (event.lengthComputable) $('upgradeProgress').textContent = `正在上传 ${Math.round(event.loaded / event.total * 100)}%`; };
  request.onerror = () => { $('upgradeMessage').textContent = '升级连接中断，当前程序未确认替换；请刷新页面检查当前版本。'; updateUpgradeButton(); };
  request.onload = () => {
    let data = {}; try { data = JSON.parse(request.responseText); } catch (_) {}
    if (request.status >= 200 && request.status < 300) {
      $('upgradeProgress').textContent = '校验完成，正在重启'; $('upgradeMessage').textContent = data.message || '升级完成，控制台正在重启。';
      waitForUpgradeRestart();
    } else { $('upgradeProgress').textContent = ''; $('upgradeMessage').textContent = data.error || `升级失败（HTTP ${request.status}）`; updateUpgradeButton(); }
  };
  request.send(selectedUpgradeFile);
}

$('saveSettings').addEventListener('click', async () => {
  try {
    await requestJson('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task_directory:$('taskDirectory').value.trim(), command_timeout_s:Number($('commandTimeout').value), elevator_wait_timeout_s:Number($('elevatorWaitTimeout').value), task_execution_timeout_s:Number($('taskExecutionTimeout').value)})}, { errorMessage: '配置保存失败' }); $('settingsMessage').textContent = '本机运行配置已保存。';
  } catch (error) { $('settingsMessage').textContent = error.message; }
});
$('upgradeFile').addEventListener('change', event => selectUpgradeFile(event.target.files[0]));
$('upgradeDropzone').addEventListener('dragover', event => { event.preventDefault(); $('upgradeDropzone').classList.add('dragover'); });
$('upgradeDropzone').addEventListener('dragleave', () => $('upgradeDropzone').classList.remove('dragover'));
$('upgradeDropzone').addEventListener('drop', event => { event.preventDefault(); $('upgradeDropzone').classList.remove('dragover'); selectUpgradeFile(event.dataTransfer.files[0]); });
$('applyUpgrade').addEventListener('click', uploadUpgrade);
loadSettings(); loadUpgradeStatus();
