export const DEFAULT_COMPONENT_TEMPLATES = {
  access_protocols: [
    { id: "bluetooth", label: "蓝牙" },
    { id: "4g", label: "4G" },
  ],
  elevator_protocols: [
    { id: "bluetooth", label: "蓝牙" },
    { id: "4g", label: "4G" },
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
        options: [["deliver", "投递"], ["wait", "等待"], ["return", "返程"]],
      },
    ],
  },
  elevator: {
    name: "电梯",
    fields: [
      { key: "wait_distance_m", label: "候梯距离（m）", type: "number", min: "0.5", max: "5", step: "0.1", default: 1.5 },
    ],
  },
  gate: {
    name: "闸机",
    fields: [
      { key: "gate_id", label: "闸机编号", type: "text", placeholder: "例如：G-01" },
      { key: "access_protocol", label: "控制协议", type: "select", protocolCategory: "access_protocols", default: "bluetooth" },
      {
        key: "speed_profile",
        label: "速度模式",
        type: "select",
        options: [["single_point", "常规"], ["slow_point", "减速"], ["narrow_point", "窄通道"]],
      },
    ],
  },
  auto_door: {
    name: "自动门",
    fields: [
      { key: "door_id", label: "门编号", type: "text", placeholder: "例如：D-01" },
      { key: "access_protocol", label: "控制协议", type: "select", protocolCategory: "access_protocols", default: "bluetooth" },
      { key: "speed_profile", label: "速度模式", type: "select", options: [["single_point", "常规"], ["slow_point", "减速"]] },
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
