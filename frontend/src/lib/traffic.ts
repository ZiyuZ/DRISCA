export const trafficStyles = [
  {
    value: "balanced",
    label: "均衡",
    description: "兼顾通行效率与安全，使用默认车头时距与加速度。",
  },
  {
    value: "aggressive",
    label: "激进",
    description: "更小的车头时距和更强的加速倾向，跟车更紧。",
  },
  {
    value: "conservative",
    label: "保守",
    description: "更大的安全距离，速度调整更平缓。",
  },
  {
    value: "sluggish",
    label: "反应迟钝",
    description: "含约 0.6 秒感知延迟，反应与起步更慢。",
  },
  {
    value: "mixed",
    label: "混合（多风格）",
    description: "按 50/20/20/10 分配均衡、激进、保守与反应迟钝车辆。",
  },
] as const;

export const carFollowingModels = [
  {
    value: "idm",
    label: "IDM 智能驾驶员模型",
    short: "IDM",
    description: "根据期望速度与车头时距计算连续加速度，跟车平顺。",
  },
  {
    value: "gipps",
    label: "Gipps 安全距离模型",
    short: "Gipps",
    description: "以安全制动距离约束目标速度，强调不追尾。",
  },
  {
    value: "krauss",
    label: "Krauss 随机安全速度模型",
    short: "Krauss",
    description: "在安全速度范围内随机化，车流离散度更明显。",
  },
] as const;

export const laneChangeModels = [
  {
    value: "gap",
    label: "安全间隙规则",
    short: "安全间隙",
    description: "目标车道前后间隙满足安全要求时才换道。",
  },
  {
    value: "mobil",
    label: "MOBIL 激励换道模型",
    short: "MOBIL",
    description: "综合自身与后车的收益判断是否换道，更倾向主动寻优。",
  },
] as const;
