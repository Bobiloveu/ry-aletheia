import { requestJson } from "./platform/http.js";
import {
  loadBagRecordingDraft,
  loadManualBagRecordingDraft,
  saveBagRecordingDraft,
  saveManualBagRecordingDraft,
} from "./bag-recording-selection.js";

const $ = (id) => document.getElementById(id);
const manualMode = new URLSearchParams(window.location.search).get("mode") === "manual";
const draft = manualMode ? loadManualBagRecordingDraft() : loadBagRecordingDraft();
let topics = [];
let selected = new Set(draft?.topics || []);
let loading = false;

if (manualMode) {
  document.title = "手动场景录制 · RY Aletheia";
  $("pageTitle").textContent = "配置手动场景录制";
  $("pageSubtitle").textContent = "选择需要保留的 DDS Topic 后开始录制。录制不发送控制指令，可在遥控过程中持续进行。";
  $("returnLink").href = "/bag-recordings.html";
  $("returnLink").textContent = "返回诊断录包";
  $("cancelLink").href = "/bag-recordings.html";
  $("testAttemptScope").hidden = true;
  $("manualScope").hidden = false;
  $("sceneLabel").value = draft?.label || "";
  $("durationMinutes").value = String(draft?.durationMinutes || 15);
  $("save").textContent = "开始手动录制";
}

function renderSelection() {
  const count = selected.size;
  $("selectedCount").textContent = count ? `已选择 ${count} 个 Topic` : "尚未选择 Topic";
  $("selectionHint").textContent = count ? "录制开始前会重新确认这些 Topic 仍可用。" : "最多选择 32 个 Topic。";
}

function renderTopics() {
  const term = $("filter").value.trim().toLowerCase();
  const visible = topics.filter((topic) => !term || topic.name.toLowerCase().includes(term) || topic.type.toLowerCase().includes(term));
  $("topicList").replaceChildren(...(visible.length ? visible.map((topic) => {
    const row = document.createElement("label"); row.className = "bag-config-topic-row";
    const input = Object.assign(document.createElement("input"), { type: "checkbox", checked: selected.has(topic.name), value: topic.name });
    const name = document.createElement("strong"); name.textContent = topic.name;
    const type = document.createElement("span"); type.textContent = topic.type;
    const publishers = document.createElement("small"); publishers.textContent = `${topic.publisher_count} 个发布者`;
    row.append(input, name, type, publishers);
    return row;
  }) : [Object.assign(document.createElement("p"), { className: "bag-config-empty", textContent: loading ? "正在读取 ROS 图…" : "未发现可录的 DDS Topic。请确认发布者已启动后刷新。" })]));
}

async function refreshTopics() {
  loading = true; $("refresh").disabled = true; $("topicHint").textContent = "正在读取 DDS 图，最多需要约 2 秒…"; renderTopics();
  try {
    const data = await requestJson("/api/bag-recordings/topics");
    topics = Array.isArray(data.topics) ? data.topics : [];
    selected = new Set([...selected].filter((name) => topics.some((topic) => topic.name === name)));
    $("topicHint").textContent = topics.length ? `已发现 ${topics.length} 个可录 Topic；开始目标轮前仍会再次验证。` : "未发现可录 DDS Topic；请确认发布者和 ROS 域后刷新。";
  } catch (error) {
    $("topicHint").textContent = `读取 ROS 图失败：${error.message}`;
  } finally {
    loading = false; $("refresh").disabled = false; renderSelection(); renderTopics();
  }
}

$("attemptIndex").value = draft?.attemptIndex || 1;
$("refresh").addEventListener("click", refreshTopics);
$("filter").addEventListener("input", renderTopics);
$("topicList").addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== "checkbox") return;
  if (input.checked && selected.size >= 32) { input.checked = false; $("topicHint").textContent = "一次最多可选择 32 个 Topic。"; return; }
  if (input.checked) selected.add(input.value); else selected.delete(input.value);
  renderSelection();
});
$("save").addEventListener("click", async () => {
  try {
    if (manualMode) {
      const manualDraft = saveManualBagRecordingDraft(undefined, {
        topics: [...selected], durationMinutes: Number($("durationMinutes").value), label: $("sceneLabel").value,
      });
      $("save").disabled = true;
      await requestJson("/api/bag-recordings/manual", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(manualDraft),
      });
      window.location.assign("/bag-recordings.html?manualRecording=started");
      return;
    }
    saveBagRecordingDraft(undefined, { attemptIndex: $("attemptIndex").value, topics: [...selected] });
    window.location.assign("/?diagnosticRecording=ready");
  } catch (error) {
    $("topicHint").textContent = error.message;
  } finally {
    $("save").disabled = false;
  }
});
renderSelection();
refreshTopics();
