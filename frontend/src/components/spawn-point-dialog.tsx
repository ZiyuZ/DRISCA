import { zhCN, format } from "../i18n";
import { useEffect, useId, useRef, useState } from "react";
import { catalogMatchesPreset, mapKey, matchSpawnIndex, spawnBound, spawnLabel } from "../lib/spawn";
import type { PresetConfig, SpawnPoint, Telemetry } from "../types/api";
import { ActionTooltip } from "./action-tooltip";

import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";

const fields = [
  ["x", "X · m"],
  ["y", "Y · m"],
  ["z", "Z · m"],
  ["pitch", zhCN.spawn.pitch],
  ["yaw", zhCN.spawn.yaw],
  ["roll", zhCN.spawn.roll],
] as const;
type Field = (typeof fields)[number][0];
type Drafts = Record<Field, string>;

const emptyDrafts = (): Drafts => ({ x: "", y: "", z: "", pitch: "", yaw: "", roll: "" });
const toDrafts = (point: SpawnPoint): Drafts => ({
  x: point.x.toFixed(2),
  y: point.y.toFixed(2),
  z: point.z.toFixed(2),
  pitch: point.pitch.toFixed(2),
  yaw: point.yaw.toFixed(2),
  roll: point.roll.toFixed(2),
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
  telemetry: Telemetry | null;
  onConfirm: (point: SpawnPoint) => void;

};

export function SpawnPointEditor({
  preset,
  catalogMap,
  spawnPoints,
  connected,
  telemetry,
  onConfirm,
}: Props) {
  const labelId = useId();
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
  // 目标地图加载完成后，只在首次出现目录时初始化一次预选。
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
    ? zhCN.spawn.confirmed
    : hasPoints
      ? zhCN.spawn.unselected
      : mapLoaded
        ? zhCN.spawn.noPresets
        : zhCN.spawn.unselected;
  const statusText = boundHere
    ? !mapLoaded
      ? zhCN.spawn.boundUnloadedHint
      : hasPoints
        ? zhCN.spawn.boundHint
        : zhCN.spawn.boundCustomHint
    : hasPoints
      ? zhCN.spawn.randomHint
      : !connected
        ? zhCN.spawn.disconnectedHint
        : mapLoaded
          ? zhCN.spawn.completeCoordinatesHint
          : format(zhCN.spawn.unloadedHint, { mapName: mapKey(preset.world.map_name) });
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
  const pickCurrent = () => {
    if (!telemetry) return;
    setSubmitted(false);
    setMode("custom");
    setDrafts(toDrafts({
      x: telemetry.location_x, y: telemetry.location_y, z: telemetry.location_z,
      pitch: telemetry.rotation_pitch, yaw: telemetry.rotation_yaw, roll: telemetry.rotation_roll,
    }));
  };
  const field = ([key, label]: (typeof fields)[number]) => {
    const invalid = submitted && parseDraft(drafts[key]) === null;
    return (
      <label className="field-row" key={key}>
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
        {invalid && <small className="field-error">{zhCN.spawn.required}</small>}
      </label>
    );
  };
  return (
      <div className="spawn-dialog spawn-editor">
        <div className="spawn-status" role="status">
          <strong>{statusTitle}</strong>
          <span>{statusText}</span>
        </div>
        <Tabs
          value={mode}
          onValueChange={(value) => {
            setSubmitted(false);
            setMode(value as "point" | "custom");
          }}
          className="spawn-mode"
        >
          <TabsList className="spawn-mode-list w-full">
            <TabsTrigger value="point" disabled={!hasPoints}>{zhCN.spawn.preset}</TabsTrigger>
            <TabsTrigger value="custom">{zhCN.spawn.custom}</TabsTrigger>
          </TabsList>
          <TabsContent value="point" className="spawn-tab-panel">
            {hasPoints ? (
              <>
                <div className="dr-field">
                  <span id={labelId}>{format(zhCN.spawn.mapPoints, { mapName: mapKey(preset.world.map_name) })}</span>
                  <SharedSelect
                    aria-labelledby={labelId}
                    disabled={!hasPoints}
                    placeholder={zhCN.spawn.chooseMapPoint}
                    value={pointIndex !== null ? `point:${pointIndex}` : ""}
                    options={points.map((point, index) => [
                      `point:${index}`,
                      format(zhCN.spawn.pointLabel, { index: index + 1, coordinates: spawnLabel(point) }),
                    ] as const)}
                    onValueChange={(value) => {
                      setSubmitted(false);
                      const index = Number(value.slice("point:".length));
                      setPointIndex(index);
                      const point = points[index];
                      if (point) {
                        setDrafts(toDrafts(point));
                        onConfirm(point);
                      }
                    }}
                  />
                </div>
                {chosen && (
                  <div className="spawn-point-card">
                    <div className="spawn-point-row">
                      <span>{zhCN.spawn.position}</span>
                      <strong>X {chosen.x.toFixed(2)} · Y {chosen.y.toFixed(2)} · Z {chosen.z.toFixed(2)}</strong>
                    </div>
                    <div className="spawn-point-row">
                      <span>{zhCN.spawn.rotation}</span>
                      <strong>
                        {format(zhCN.spawn.rotationValues, { pitch: chosen.pitch.toFixed(2), yaw: chosen.yaw.toFixed(2), roll: chosen.roll.toFixed(2) })}
                      </strong>
                    </div>
                  </div>
                )}
                {pointMissing && (
                  <p className="text-sm text-destructive" role="alert">
                    {zhCN.spawn.staleList}</p>
                )}
                <p className="spawn-hint">{boundHere ? zhCN.spawn.retained : zhCN.spawn.randomReady}</p>
              </>
            ) : (
              <p className="spawn-hint">{zhCN.spawn.noPresetsCustom}</p>
            )}
          </TabsContent>
          <TabsContent value="custom" className="spawn-tab-panel">
            <div className="spawn-section">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <strong className="text-sm">{zhCN.spawn.customTitle}</strong>
                <ActionTooltip reason={!telemetry ? zhCN.spawn.telemetryRequired : zhCN.spawn.pickupHint}>
                  <Button size="sm" variant="outline" disabled={!telemetry} onClick={pickCurrent}>{zhCN.spawn.pickup}</Button>
                </ActionTooltip>
              </div>
              <div className="spawn-coordinate-columns">
                <section className="grid content-start gap-3 rounded-lg border bg-muted/20 p-4">
                  <h3 className="text-xs font-semibold text-muted-foreground">{zhCN.spawn.positionGroup}</h3>
                  {fields.slice(0, 3).map(field)}
                </section>
                <section className="grid content-start gap-3 rounded-lg border bg-muted/20 p-4">
                  <h3 className="text-xs font-semibold text-muted-foreground">{zhCN.spawn.rotationGroup}</h3>
                  {fields.slice(3).map(field)}
                </section>
              </div>
            </div>
            {submitted && !complete && (
              <p className="text-sm text-destructive" role="alert">
                {zhCN.spawn.incompleteCoordinates}</p>
            )}
            <p className="spawn-hint">
              {zhCN.spawn.roadValidationHint}</p>
          </TabsContent>
        </Tabs>
        <div className="flex justify-end border-t pt-4">
          <Button onClick={confirm} disabled={mode === "point" && !chosen}>{zhCN.spawn.confirm}</Button>
        </div>
      </div>
  );
}
