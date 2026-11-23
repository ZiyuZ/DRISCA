import { useEffect, useRef, useState } from "react";
import { catalogMatchesPreset, mapKey, matchSpawnIndex, spawnBound, spawnLabel } from "../lib/spawn";
import type { PresetConfig, SpawnPoint } from "../types/api";
import { Modal } from "./common";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

const fields = [
  ["x", "X · m"],
  ["y", "Y · m"],
  ["z", "Z · m"],
  ["pitch", "俯仰角 · °"],
  ["yaw", "偏航角 · °"],
  ["roll", "翻滚角 · °"],
] as const;
type Field = (typeof fields)[number][0];
type Drafts = Record<Field, string>;

const emptyDrafts = (): Drafts => ({ x: "", y: "", z: "", pitch: "", yaw: "", roll: "" });
const toDrafts = (point: SpawnPoint): Drafts => ({
  x: String(point.x),
  y: String(point.y),
  z: String(point.z),
  pitch: String(point.pitch),
  yaw: String(point.yaw),
  roll: String(point.roll),
});
const parseDraft = (text: string) => {
  if (!text.trim()) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
};

type Props = {
  preset: PresetConfig;
  catalogMap: string | null;
  spawnPoints: SpawnPoint[];
  connected: boolean;
  worldLoading: boolean;
  phaseIdle: boolean;
  onLoadMap: () => Promise<void>;
  onConfirm: (point: SpawnPoint) => void;
  onClose: () => void;
};

export function SpawnPointDialog({
  preset,
  catalogMap,
  spawnPoints,
  connected,
  worldLoading,
  phaseIdle,
  onLoadMap,
  onConfirm,
  onClose,
}: Props) {
  const mapLoaded = catalogMatchesPreset(preset, catalogMap);
  const points = mapLoaded ? spawnPoints : [];
  const hasPoints = points.length > 0;
  const boundHere = spawnBound(preset);
  const initialMatch = hasPoints ? matchSpawnIndex(points, preset.ego.spawn_point) : null;
  const [mode, setMode] = useState<"point" | "custom">(() =>
    hasPoints && (!boundHere || initialMatch !== null) ? "point" : "custom",
  );
  const [pointIndex, setPointIndex] = useState<number | null>(() => {
    if (!hasPoints) return null;
    if (boundHere && initialMatch !== null) return initialMatch;
    return Math.floor(Math.random() * points.length);
  });
  const [drafts, setDrafts] = useState<Drafts>(() =>
    boundHere ? toDrafts(preset.ego.spawn_point) : emptyDrafts(),
  );
  const [submitted, setSubmitted] = useState(false);
  const picked = useRef(hasPoints);
  const inputRefs = useRef<Record<Field, HTMLInputElement | null>>({
    x: null,
    y: null,
    z: null,
    pitch: null,
    yaw: null,
    roll: null,
  });
  // 目标地图在对话框打开后才加载完成时，只在首次出现目录时初始化一次预选。
  useEffect(() => {
    if (picked.current || points.length === 0) return;
    picked.current = true;
    if (!boundHere) {
      setMode("point");
      setPointIndex(Math.floor(Math.random() * points.length));
      return;
    }
    const index = matchSpawnIndex(points, preset.ego.spawn_point);
    if (index !== null) {
      setMode("point");
      setPointIndex(index);
    }
  }, [points, boundHere, preset.ego.spawn_point]);
  const chosen = mode === "point" && pointIndex !== null ? (points[pointIndex] ?? null) : null;
  const pointMissing = mode === "point" && chosen === null;
  const parsed = fields.map(([key]) => parseDraft(drafts[key]));
  const complete = parsed.every((value): value is number => value !== null);
  const message = boundHere
    ? hasPoints
      ? "可继续使用当前坐标，或从地图预设出生点中改选。"
      : "当前使用自定义坐标。加载目标地图后可改选预设出生点。"
    : hasPoints
      ? "尚未选择该地图的出生点。已随机选择一个预设出生点，确认或改选后再开始实验。"
      : !connected
        ? "尚未选择该地图的出生点。连接模拟器后可加载目标地图并随机选择预设出生点，也可以直接填写坐标。"
        : mapLoaded
          ? "该地图没有预设出生点，请填写完整坐标后再开始实验。"
          : `尚未选择该地图的出生点。加载 ${mapKey(
              preset.world.map_name,
            )} 后可随机选择预设出生点，也可以直接填写坐标。`;
  const confirm = () => {
    if (mode === "point") {
      if (chosen) onConfirm(chosen);
      else setSubmitted(true);
      return;
    }
    setSubmitted(true);
    if (!complete) {
      const missing = fields.find(([key]) => parseDraft(drafts[key]) === null);
      if (missing) inputRefs.current[missing[0]]?.focus();
      return;
    }
    const [x, y, z, pitch, yaw, roll] = parsed as number[];
    onConfirm({ x, y, z, pitch, yaw, roll });
  };
  const loadDisabled = !connected || !phaseIdle || worldLoading;
  return (
    <Modal
      title="选择出生点"
      open
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={confirm}>使用该出生点</Button>
        </>
      }
    >
      <div className="grid min-w-0 gap-4">
        <p className="text-sm text-muted-foreground" role="status">
          {message}
        </p>
        {!mapLoaded && (
          <div className="spawn-load">
            <Button variant="outline" disabled={loadDisabled} onClick={() => void onLoadMap()}>
              {worldLoading ? "正在加载地图…" : `加载 ${mapKey(preset.world.map_name)}`}
            </Button>
            <span className="text-sm text-muted-foreground">
              {!connected
                ? "连接模拟器后可加载目标地图。"
                : !phaseIdle
                  ? "实验进行中不能切换地图。"
                  : "加载完成后会随机预选一个预设出生点。"}
            </span>
          </div>
        )}
        {hasPoints && (
          <label className="dr-field">
            <span>目标地图 {mapKey(preset.world.map_name)} 的出生点</span>
            <SharedSelect
              value={mode === "point" && pointIndex !== null ? `point:${pointIndex}` : "custom"}
              options={[
                ...points.map((point, index) => [`point:${index}`, `出生点 ${index + 1} · ${spawnLabel(point)}`] as const),
                ["custom", "自定义坐标"] as const,
              ]}
              onValueChange={(value) => {
                setSubmitted(false);
                if (value === "custom") {
                  setMode("custom");
                  return;
                }
                setMode("point");
                setPointIndex(Number(value.slice("point:".length)));
              }}
            />
          </label>
        )}
        {mode === "point" && chosen && <p className="text-sm">{spawnLabel(chosen)}</p>}
        {pointMissing && (
          <p className="text-sm text-destructive" role="alert">
            出生点列表已更新，请重新选择出生点。
          </p>
        )}
        {mode === "custom" && (
          <>
            <div className="three spawn-fields">
              {fields.map(([key, label]) => {
                const invalid = submitted && parseDraft(drafts[key]) === null;
                return (
                  <label className="dr-field" key={key}>
                    <span>{label}</span>
                    <Input
                      ref={(element) => {
                        inputRefs.current[key] = element;
                      }}
                      className="input mono"
                      type="number"
                      step="0.1"
                      required
                      aria-invalid={invalid ? "true" : "false"}
                      value={drafts[key]}
                      onChange={(event) => {
                        setSubmitted(false);
                        setDrafts((old) => ({ ...old, [key]: event.target.value }));
                      }}
                    />
                    {invalid && <small className="field-error">必填，且需为有限数值</small>}
                  </label>
                );
              })}
            </div>
            {submitted && !complete && (
              <p className="text-sm text-destructive" role="alert">
                请填写完整的出生点坐标（X、Y、Z、俯仰、偏航、翻滚）。
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              坐标需落在目标地图的道路上；启动前会用道路查询校验，道路外会被拒绝。
            </p>
          </>
        )}
      </div>
    </Modal>
  );
}
