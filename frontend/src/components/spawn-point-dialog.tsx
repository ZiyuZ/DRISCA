import { useEffect, useRef, useState } from "react";
import { catalogMatchesPreset, mapKey, matchSpawnIndex, spawnBound, spawnLabel } from "../lib/spawn";
import type { PresetConfig, SpawnPoint } from "../types/api";
import { Modal } from "./common";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";

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
  useEffect(() => {
    if (!hasPoints) setMode("custom");
  }, [hasPoints]);
  const chosen = mode === "point" && pointIndex !== null ? (points[pointIndex] ?? null) : null;
  const pointMissing = mode === "point" && chosen === null;
  const parsed = fields.map(([key]) => parseDraft(drafts[key]));
  const complete = parsed.every((value): value is number => value !== null);
  const statusTitle = boundHere
    ? "该地图的出生点已确认"
    : hasPoints
      ? "尚未选择该地图的出生点"
      : mapLoaded
        ? "该地图没有预设出生点"
        : "尚未选择该地图的出生点";
  const statusText = boundHere
    ? !mapLoaded
      ? "当前预设已有该地图的出生点；加载目标地图后可从预设点中改选。"
      : hasPoints
        ? "可继续使用当前坐标，或从地图预设出生点中改选。"
        : "当前使用自定义坐标；该地图没有预设出生点。"
    : hasPoints
      ? "已随机预选一个预设出生点，确认或改选后再开始实验。"
      : !connected
        ? "连接模拟器后可加载目标地图并选择预设出生点，也可以直接填写坐标。"
        : mapLoaded
          ? "请填写完整坐标后确认。"
          : `目标地图 ${mapKey(preset.world.map_name)} 尚未加载；加载后可选择预设出生点，也可以直接填写坐标。`;
  const loadDisabled = !connected || !phaseIdle || worldLoading;
  const loadHint = !connected
    ? "连接模拟器后可加载目标地图。"
    : !phaseIdle
      ? "实验进行中不能切换地图。"
      : `加载 ${mapKey(preset.world.map_name)} 后会随机预选一个预设出生点。`;
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
  const field = ([key, label]: (typeof fields)[number]) => {
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
          step="any"
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
  };
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
          <Button onClick={confirm} disabled={mode === "point" && !chosen}>
            使用该出生点
          </Button>
        </>
      }
    >
      <div className="spawn-dialog">
        <div className="spawn-status" role="status">
          <strong>{statusTitle}</strong>
          <span>{statusText}</span>
        </div>
        {!mapLoaded && (
          <div className="spawn-load-card">
            <div className="spawn-load-copy">
              <strong>目标地图：{mapKey(preset.world.map_name)}</strong>
              <span>{loadHint}</span>
            </div>
            <Button disabled={loadDisabled} onClick={() => void onLoadMap()}>
              {worldLoading ? "正在加载…" : "加载目标地图"}
            </Button>
          </div>
        )}
        <Tabs
          value={mode}
          onValueChange={(value) => {
            setSubmitted(false);
            setMode(value as "point" | "custom");
          }}
          className="spawn-mode"
        >
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="point" disabled={!hasPoints}>预设出生点</TabsTrigger>
            <TabsTrigger value="custom">自定义坐标</TabsTrigger>
          </TabsList>
          <TabsContent value="point" className="spawn-tab-panel">
            {hasPoints ? (
              <>
                <label className="dr-field">
                  <span>{mapKey(preset.world.map_name)} 的地图出生点</span>
                  <SharedSelect
                    value={pointIndex !== null ? `point:${pointIndex}` : ""}
                    options={points.map((point, index) => [
                      `point:${index}`,
                      `出生点 ${index + 1} · ${spawnLabel(point)}`,
                    ] as const)}
                    onValueChange={(value) => {
                      setSubmitted(false);
                      setPointIndex(Number(value.slice("point:".length)));
                    }}
                  />
                </label>
                {chosen && (
                  <div className="spawn-point-card">
                    <div className="spawn-point-row">
                      <span>位置</span>
                      <strong>X {chosen.x.toFixed(2)} · Y {chosen.y.toFixed(2)} · Z {chosen.z.toFixed(2)}</strong>
                    </div>
                    <div className="spawn-point-row">
                      <span>姿态</span>
                      <strong>
                        俯仰 {chosen.pitch.toFixed(2)}° · 偏航 {chosen.yaw.toFixed(2)}° ·
                        翻滚 {chosen.roll.toFixed(2)}°
                      </strong>
                    </div>
                  </div>
                )}
                {pointMissing && (
                  <p className="text-sm text-destructive" role="alert">
                    出生点列表已更新，请重新选择出生点。
                  </p>
                )}
                <p className="spawn-hint">已随机预选一个点，可直接确认，也可以从列表改选。</p>
              </>
            ) : (
              <p className="spawn-hint">该地图没有预设出生点，请使用自定义坐标。</p>
            )}
          </TabsContent>
          <TabsContent value="custom" className="spawn-tab-panel">
            <div className="spawn-section">
              <div className="spawn-section-head">
                <strong>位置</strong>
                <span>地图世界坐标 · m</span>
              </div>
              <div className="three">{fields.slice(0, 3).map(field)}</div>
            </div>
            <div className="spawn-section">
              <div className="spawn-section-head">
                <strong>姿态</strong>
                <span>角度 · °</span>
              </div>
              <div className="three">{fields.slice(3).map(field)}</div>
            </div>
            {submitted && !complete && (
              <p className="text-sm text-destructive" role="alert">
                请填写完整的出生点坐标（X、Y、Z、俯仰、偏航、翻滚）。
              </p>
            )}
            <p className="spawn-hint">
              坐标需落在目标地图的道路上；启动前会用道路查询校验，道路外会被拒绝。
            </p>
          </TabsContent>
        </Tabs>
      </div>
    </Modal>
  );
}
