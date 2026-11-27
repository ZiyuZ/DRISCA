import { zhCN } from "../i18n";
import type { TrafficStyleCounts } from "../types/api";

export const trafficStyles = [
  {
    value: "balanced",
    label: zhCN.traffic.balanced,
    description: zhCN.traffic.balancedHint,
  },
  {
    value: "aggressive",
    label: zhCN.traffic.aggressive,
    description: zhCN.traffic.aggressiveHint,
  },
  {
    value: "conservative",
    label: zhCN.traffic.conservative,
    description: zhCN.traffic.conservativeHint,
  },
  {
    value: "sluggish",
    label: zhCN.traffic.sluggish,
    description: zhCN.traffic.sluggishHint,
  },
] as const;

export const totalTrafficVehicles = (counts: TrafficStyleCounts | undefined): number =>
  counts ? counts.balanced + counts.aggressive + counts.conservative + counts.sluggish : 0;

export const carFollowingModels = [
  {
    value: "idm",
    label: zhCN.traffic.idm,
    short: "IDM",
    description: zhCN.traffic.idmHint,
  },
  {
    value: "gipps",
    label: zhCN.traffic.gipps,
    short: "Gipps",
    description: zhCN.traffic.gippsHint,
  },
  {
    value: "krauss",
    label: zhCN.traffic.krauss,
    short: "Krauss",
    description: zhCN.traffic.kraussHint,
  },
] as const;

export const laneChangeModels = [
  {
    value: "gap",
    label: zhCN.traffic.gap,
    short: zhCN.traffic.gapShort,
    description: zhCN.traffic.gapHint,
  },
  {
    value: "mobil",
    label: zhCN.traffic.mobil,
    short: "MOBIL",
    description: zhCN.traffic.mobilHint,
  },
] as const;
