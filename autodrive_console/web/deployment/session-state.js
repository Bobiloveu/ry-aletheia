import {
  isDeploymentStageUnlocked,
  resolveDeploymentViewStage,
} from "./workflow.js";

export const SESSION_STORAGE_KEY = "ry-aletheia:deployment-session:v1";

function validId(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function pointer(value) {
  if (!value || typeof value !== "object" || value.version !== 1 || !validId(value.projectId)) {
    return null;
  }
  const storedDraft = value.deploymentTaskDraft && typeof value.deploymentTaskDraft === "object"
    ? value.deploymentTaskDraft
    : {};
  const viewedDeploymentStage = value.viewedDeploymentStage ?? value.viewedStage;
  return {
    version: 1,
    projectId: value.projectId,
    mapId: validId(value.mapId) ? value.mapId : null,
    viewedDeploymentStage: validId(viewedDeploymentStage) ? viewedDeploymentStage : null,
    deploymentTaskDraft: {
      mapSource: ["import", "mapping"].includes(storedDraft.mapSource)
        ? storedDraft.mapSource
        : null,
      mapLabel: typeof storedDraft.mapLabel === "string"
        ? storedDraft.mapLabel.slice(0, 80)
        : "",
    },
  };
}

export function readDeploymentSession(store = globalThis.localStorage) {
  if (!store) return null;
  try {
    const raw = store.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    return pointer(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function writeDeploymentSession(store = globalThis.localStorage, value = {}) {
  if (!store) return null;
  const next = pointer({ version: 1, ...value });
  if (!next) return null;
  try {
    store.setItem(SESSION_STORAGE_KEY, JSON.stringify(next));
  } catch {
    return null;
  }
  return next;
}

export function clearDeploymentSession(store = globalThis.localStorage) {
  if (!store) return;
  try {
    store.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // Storage can be disabled by browser policy. The page still works in memory.
  }
}

export function clampDeploymentStage(currentStage, requestedStage) {
  if (!currentStage) return "project";
  if (!requestedStage) return currentStage;
  return isDeploymentStageUnlocked(currentStage, requestedStage)
    ? resolveDeploymentViewStage(currentStage, requestedStage)
    : currentStage;
}
