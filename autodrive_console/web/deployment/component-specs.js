export const DEFAULT_COMPONENT_TEMPLATES = {
  access_protocols: [
    { id: "bluetooth", label: "蓝牙" },
    { id: "4g", label: "4G" },
  ],
  elevator_protocols: [
    { id: "mqtt", label: "MQTT" },
    { id: "lora", label: "LORA" },
  ],
};

export const COMPONENT_SPECS = {
  start: {
    name: "起点",
    fields: [
      {
        key: "start_action",
        label: "起始动作",
        type: "select",
        options: [["dispatch", "派送起始"], ["return", "返程起始"]],
      },
    ],
  },
  target: {
    name: "目标点",
    fields: [
      { key: "door", label: "门牌号", type: "text", placeholder: "例如：1509", default: "" },
      {
        key: "arrival_action",
        label: "到达动作",
        type: "select",
        options: [["place_water", "泄水"], ["auto_cargo", "卸货"]],
        default: "place_water",
      },
    ],
  },
  building_entrance: {
    name: "楼栋入口",
    fields: [],
  },
  elevator: {
    name: "电梯",
    fields: [
      { key: "button_floor", label: "本地图按钮层", type: "number", step: "1", placeholder: "例如：1" },
      { key: "wait_distance_m", label: "候梯距离（m）", type: "number", min: "0.5", max: "5", step: "0.1", default: 1.5 },
    ],
  },
  gate: {
    name: "闸机",
    fields: [
      { key: "gate_id", label: "闸机编号", type: "text", placeholder: "例如：G-01" },
      { key: "controller_device_id", label: "控制设备号", type: "text", inputMode: "numeric", pattern: "[1-9][0-9]*", placeholder: "例如：10044", default: "" },
      { key: "access_protocol", label: "控制协议", type: "select", protocolCategory: "access_protocols", default: "bluetooth" },
      { key: "pre_open_distance_m", label: "开门前距离（m）", type: "number", min: "0.5", max: "5", step: "0.1", default: 1.5 },
      { key: "post_open_distance_m", label: "开门后停靠距离（m）", type: "number", min: "0.5", max: "5", step: "0.1", default: 1.5 },
    ],
  },
  auto_door: {
    name: "自动门",
    fields: [
      { key: "door_id", label: "门编号", type: "text", placeholder: "例如：D-01" },
      { key: "controller_device_id", label: "控制设备号", type: "text", inputMode: "numeric", pattern: "[1-9][0-9]*", placeholder: "例如：10044", default: "" },
      { key: "access_protocol", label: "控制协议", type: "select", protocolCategory: "access_protocols", default: "bluetooth" },
      { key: "pre_open_distance_m", label: "开门前距离（m）", type: "number", min: "0.5", max: "5", step: "0.1", default: 1.5 },
      { key: "post_open_distance_m", label: "开门后停靠距离（m）", type: "number", min: "0.5", max: "5", step: "0.1", default: 1.5 },
    ],
  },
  narrow_passage: {
    name: "窄通道",
    fields: [
      { key: "speed_profile", label: "速度模式", type: "select", options: [["narrow_point", "窄通道"], ["slow_point", "减速"], ["single_point", "常规"]] },
    ],
  },
  ramp: {
    name: "坡道",
    fields: [
      { key: "speed_profile", label: "速度模式", type: "select", options: [["slow_point", "减速"], ["single_point", "常规"]] },
    ],
  },
  slow_zone: {
    name: "减速区",
    fields: [
      { key: "speed_profile", label: "速度模式", type: "select", options: [["slow_point", "减速"], ["single_point", "常规"]] },
    ],
  },
};

export const componentName = (component) =>
  COMPONENT_SPECS[component?.kind]?.name || component?.label || component?.kind;

export const protocolOptions = (project, category) => {
  const options = project?.component_templates?.[category];
  return Array.isArray(options) && options.length
    ? options.map((item) => [item.id, item.label])
    : (DEFAULT_COMPONENT_TEMPLATES[category] || []).map((item) => [item.id, item.label]);
};

export const protocolTitle = (project, protocol) =>
  protocolOptions(project, "elevator_protocols").find(([id]) => id === protocol)?.[1] ||
  protocol ||
  "未配置";
