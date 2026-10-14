import { requestJson } from "./platform/http.js";
import { createInventoryExportPages } from "./software-inventory-export.js";

const elements = {
  form: document.querySelector("#vehicleProfileForm"),
  vehicleNumber: document.querySelector("#vehicleNumber"),
  vehicleVin: document.querySelector("#vehicleVin"),
  vehicleModel: document.querySelector("#vehicleModel"),
  vehicleProject: document.querySelector("#vehicleProject"),
  vehicleLocation: document.querySelector("#vehicleLocation"),
  saveInventory: document.querySelector("#saveInventory"),
  refreshInventory: document.querySelector("#refreshInventory"),
  exportInventory: document.querySelector("#exportInventory"),
  profileStatus: document.querySelector("#profileStatus"),
  inventoryStatus: document.querySelector("#inventoryStatus"),
  snapshotDetail: document.querySelector("#snapshotDetail"),
  packageRows: document.querySelector("#packageRows"),
  inventoryEmpty: document.querySelector("#inventoryEmpty"),
  inventoryMessage: document.querySelector("#inventoryMessage"),
};

let requestSequence = 0;
let saveInFlight = false;
let lastSuccessfulSnapshot = null;

const vehicleKeys = ["vehicle_number", "vin", "model", "project", "location"];
const profileInputs = {
  vehicle_number: elements.vehicleNumber,
  vin: elements.vehicleVin,
  model: elements.vehicleModel,
  project: elements.vehicleProject,
  location: elements.vehicleLocation,
};

function localTime(value) {
  if (!value) return "尚未读取";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "尚未读取";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(date).replaceAll("/", "-");
}

function beijingStamp(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).formatToParts(date);
  const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return values.year + values.month + values.day + "-" + values.hour + values.minute + values.second;
}

function setMessage(message, kind = "") {
  elements.inventoryMessage.textContent = message || "";
  elements.inventoryMessage.className = "inventory-message" + (kind ? " " + kind : "");
}

function profileFromForm() {
  return Object.fromEntries(vehicleKeys.map((key) => [key, profileInputs[key].value.trim()]));
}

function isProfileComplete(vehicle) {
  return vehicleKeys.every((key) => typeof vehicle?.[key] === "string" && vehicle[key].trim().length > 0);
}

function storedPackageNotes() {
  // Preserve legacy metadata required by the existing save API without
  // exposing editable fields in the read-only package version table.
  return Object.fromEntries((lastSuccessfulSnapshot?.packages || []).map((item) => [
    item.package_name,
    { maintainer: item.maintainer || "", description: item.description || "" },
  ]));
}

function setSnapshotStatus(snapshot) {
  const available = snapshot?.inventory_status === "available";
  elements.inventoryStatus.textContent = available ? "清单已读取" : "暂不可读取";
  elements.inventoryStatus.className = "inventory-status " + (available ? "available" : "unavailable");
  elements.snapshotDetail.textContent = available
    ? "发现时间：" + localTime(snapshot.discovered_at) + " · 已安装 " + snapshot.packages.length + " 个 ry-* 软件包"
    : snapshot?.message || "当前无法读取软件清单，请稍后刷新。";
  elements.profileStatus.textContent = isProfileComplete(snapshot?.vehicle) ? "车辆档案完整" : "请补全车辆档案";
  elements.profileStatus.className = "inventory-status " + (isProfileComplete(snapshot?.vehicle) ? "available" : "");
  elements.exportInventory.disabled = !available || !isProfileComplete(snapshot?.vehicle) || !lastSuccessfulSnapshot;
}

function addTextCell(row, className, value) {
  const cell = document.createElement("td");
  cell.className = className;
  cell.textContent = value;
  row.append(cell);
}

function renderPackages(snapshot) {
  elements.packageRows.replaceChildren();
  const packages = Array.isArray(snapshot?.packages) ? snapshot.packages : [];
  elements.inventoryEmpty.hidden = true;
  if (snapshot?.inventory_status !== "available") {
    elements.inventoryEmpty.hidden = false;
    elements.inventoryEmpty.textContent = "软件清单暂不可读取。已保存的车辆档案仍可查看和修改，恢复后请刷新再保存。";
    return;
  }
  if (!packages.length) {
    const empty = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.className = "inventory-table-empty";
    cell.textContent = "当前未发现已安装的 ry-* 软件包。";
    empty.append(cell);
    elements.packageRows.append(empty);
    return;
  }
  packages.forEach((item) => {
    const row = document.createElement("tr");
    row.dataset.package = item.package_name;
    addTextCell(row, "inventory-package", item.package_name);
    addTextCell(row, "inventory-file", item.package_filename);
    addTextCell(row, "inventory-version", item.version);
    addTextCell(row, "inventory-version", item.architecture);
    elements.packageRows.append(row);
  });
}

function render(snapshot, { preserveForm = false } = {}) {
  const vehicle = snapshot?.vehicle || {};
  if (!preserveForm) vehicleKeys.forEach((key) => { profileInputs[key].value = vehicle[key] || ""; });
  renderPackages(snapshot);
  setSnapshotStatus(snapshot);
}

async function loadInventory({ preserveForm = false } = {}) {
  const sequence = ++requestSequence;
  elements.refreshInventory.disabled = true;
  try {
    const snapshot = await requestJson("/api/software-inventory", {}, { errorMessage: "读取软件清单失败" });
    if (sequence !== requestSequence) return;
    if (snapshot.inventory_status === "available") lastSuccessfulSnapshot = snapshot;
    render(snapshot, { preserveForm });
    if (snapshot.inventory_status !== "available") setMessage(snapshot.message, "error");
  } catch (error) {
    if (sequence !== requestSequence) return;
    const fallback = { inventory_status: "unavailable", message: error.message, vehicle: profileFromForm(), packages: [] };
    render(fallback, { preserveForm: true });
    setMessage(error.message, "error");
  } finally {
    if (sequence === requestSequence) elements.refreshInventory.disabled = false;
  }
}

async function saveInventory(event) {
  event.preventDefault();
  if (saveInFlight) return;
  saveInFlight = true;
  elements.saveInventory.disabled = true;
  setMessage("正在保存车辆档案…");
  try {
    const snapshot = await requestJson("/api/software-inventory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vehicle: profileFromForm(), package_notes: storedPackageNotes() }),
    }, { errorMessage: "保存车辆档案失败" });
    requestSequence += 1;
    lastSuccessfulSnapshot = snapshot.inventory_status === "available" ? snapshot : lastSuccessfulSnapshot;
    render(snapshot);
    setMessage("车辆档案已保存。", "success");
  } catch (error) {
    setMessage(error.message || "保存车辆档案失败。", "error");
  } finally {
    saveInFlight = false;
    elements.saveInventory.disabled = false;
    setSnapshotStatus(lastSuccessfulSnapshot || { inventory_status: "unavailable", vehicle: profileFromForm() });
  }
}

function sanitizeFilenameSegment(value) {
  const normalized = String(value || "vehicle").trim().replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  return normalized || "vehicle";
}

function triggerDownload(blob, filename) {
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("无法生成版本图片。")), "image/png");
  });
}

async function exportInventory() {
  const snapshot = lastSuccessfulSnapshot;
  if (!snapshot || snapshot.inventory_status !== "available" || !isProfileComplete(snapshot.vehicle)) return;
  const generatedAt = new Date();
  let pageIndex = 0;
  elements.exportInventory.disabled = true;
  setMessage("正在生成版本图片…");
  try {
    await document.fonts?.ready;
    for (const canvas of createInventoryExportPages({ document, snapshot, generatedAt })) {
      pageIndex += 1;
      const blob = await canvasBlob(canvas);
      const suffix = pageIndex > 1 ? "-" + pageIndex : "";
      triggerDownload(blob, "ry-software-inventory-" + sanitizeFilenameSegment(snapshot.vehicle.vehicle_number) + "-" + beijingStamp(generatedAt) + suffix + ".png");
    }
    setMessage("版本图片已生成并开始下载。", "success");
    globalThis.RYAletheiaDiagnostics?.report?.({event:'operation_completed',level:'INFO',operation:'software-inventory.image-export',message:'软件版本图片已生成并开始下载'});
  } catch (error) {
    globalThis.RYAletheiaDiagnostics?.failure?.('software-inventory.image-export',error);
    setMessage(error.message || "生成版本图片失败。", "error");
  } finally {
    setSnapshotStatus(lastSuccessfulSnapshot);
  }
}

elements.form.addEventListener("submit", saveInventory);
elements.refreshInventory.addEventListener("click", () => loadInventory({ preserveForm: true }));
elements.exportInventory.addEventListener("click", exportInventory);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !saveInFlight) loadInventory({ preserveForm: true });
});
loadInventory();
