import { zhCN } from "../i18n";
import { CircleHelp, RotateCcw } from "lucide-react";
import { useRef, useState, type PointerEvent } from "react";
import type { Camera, PresetConfig } from "../types/api";
import { Hint } from "./hint";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { NumberInput } from "./number-input";
import { Slider } from "./ui/slider";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

export type CameraName = keyof PresetConfig["cameras"];
const names: Record<CameraName, string> = {
  front: zhCN.settings.cameraFront, rear_top: zhCN.settings.cameraRearTop, rear_left: zhCN.settings.cameraRearLeft, rear_right: zhCN.settings.cameraRearRight,
};
const cameraNames = Object.keys(names) as CameraName[];
type Props = {
  cameras: PresetConfig["cameras"];
  applied?: PresetConfig["cameras"] | null;
  extent?: { x: number; y: number; z: number; };
  running: boolean;
  onChange: (name: CameraName, value: Camera) => void;
  onApply: (name: CameraName, value: Camera) => void;
};

type DragState = {
  name: CameraName;
  kind: "position" | "yaw" | "pitch";
  original: Camera;
  start: DOMPoint;
  svg: SVGSVGElement;
  nodeX: number;
  nodeY: number;
};

export function CameraInstallation({ cameras, extent = { x: 2, y: 1, z: 1 }, running, onChange, onApply }: Props) {
  const initial = useRef(structuredClone(cameras));
  const [camera, setCamera] = useState<CameraName>("front");
  const [view, setView] = useState<"top" | "side">("top");
  const [preview, setPreview] = useState<{ name: CameraName; value: Camera } | null>(null);
  const previewRef = useRef(preview);
  const shown = (name: CameraName) => preview?.name === name ? preview.value : cameras[name];
  const current = shown(camera);
  const changePreview = (name: CameraName, value: Camera) => {
    previewRef.current = { name, value };
    setPreview(previewRef.current);
  };
  const commit = (name: CameraName, value: Camera) => {
    previewRef.current = null;
    setPreview(null);
    if (JSON.stringify(value) === JSON.stringify(cameras[name])) return;
    onChange(name, value);
    if (running) onApply(name, value);
  };
  const halfY = 110 * extent.y / extent.x;
  const halfZ = 110 * extent.z / extent.x;
  const drag = useRef<DragState | null>(null);
  const point = (svg: SVGSVGElement, e: PointerEvent<SVGCircleElement>) => {
    const p = svg.createSVGPoint();
    p.x = e.clientX;
    p.y = e.clientY;
    return p.matrixTransform(svg.getScreenCTM()!.inverse());
  };
  const startDrag = (e: PointerEvent<SVGCircleElement>, name: CameraName) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setCamera(name);
    const svg = e.currentTarget.ownerSVGElement!;
    drag.current = {
      name,
      kind: "position",
      original: { ...cameras[name] },
      start: point(svg, e),
      svg,
      nodeX: 0,
      nodeY: 0,
    };
  };
  const startAngleDrag = (
    e: PointerEvent<SVGCircleElement>,
    name: CameraName,
    kind: "yaw" | "pitch",
    nodeX: number,
    nodeY: number,
  ) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setCamera(name);
    const svg = e.currentTarget.ownerSVGElement!;
    drag.current = {
      name,
      kind,
      original: { ...cameras[name] },
      start: point(svg, e),
      svg,
      nodeX,
      nodeY,
    };
  };
  const moveDrag = (e: PointerEvent<SVGCircleElement>) => {
    const d = drag.current;
    if (!d) return;
    const p = point(d.svg, e);
    if (d.kind === "yaw") {
      const yaw = Math.atan2(p.x - d.nodeX, -(p.y - d.nodeY)) * 180 / Math.PI;
      changePreview(d.name, { ...d.original, yaw: Math.round(yaw * 10) / 10 });
      return;
    }
    if (d.kind === "pitch") {
      const ratio = Math.max(-1, Math.min(1, -(p.y - d.nodeY) / 55));
      const pitch = Math.asin(ratio) * 180 / Math.PI;
      changePreview(d.name, { ...d.original, pitch: Math.round(pitch * 10) / 10 });
      return;
    }
    const dx = p.x - d.start.x;
    const dy = p.y - d.start.y;
    changePreview(d.name, {
      ...d.original,
      x: d.original.x + (view === "top" ? -dy / 110 : dx / 110),
      ...(view === "top" ? { y: d.original.y + dx / halfY } : { z: d.original.z - dy / halfZ }),
    });
  };
  const endDrag = () => {
    if (!drag.current) return;
    drag.current = null;
    const final = previewRef.current;
    if (final) commit(final.name, final.value);
  };
  const cancelDrag = () => {
    drag.current = null;
    previewRef.current = null;
    setPreview(null);
  };
  const fields = [
    ["x", zhCN.settings.cameraX, -100, 100], ["y", zhCN.settings.cameraY, -100, 100],
    ["z", zhCN.settings.cameraZ, -100, 100], ["pitch", zhCN.settings.cameraPitch, -90, 90],
    ["yaw", zhCN.settings.cameraYaw, -180, 180], ["roll", zhCN.settings.cameraRoll, -180, 180],
    ["fov", zhCN.settings.cameraFov, 30, 150],
  ] as const;
  return (
    <div className="mount-page">
      <Card className="dr-card camera-diagram-card gap-0">
        <div className="mount-stage">
          <Tabs
            value={view}
            onValueChange={(value) => setView(value as "top" | "side")}
            className="mount-floating-controls"
          >
            <TabsList className="shadow-sm">
              <TabsTrigger value="top">{zhCN.settings.cameraTopView}</TabsTrigger>
              <TabsTrigger value="side">{zhCN.settings.cameraSideView}</TabsTrigger>
            </TabsList>
          </Tabs>
          <svg
            className="mount-diagram"
            viewBox="0 0 400 300"
            aria-label={zhCN.settings.cameraDiagram}
          >
            <rect
              x={view === "top" ? 200 - halfY : 90}
              y={view === "top" ? 40 : 150 - halfZ}
              width={view === "top" ? 2 * halfY : 220}
              height={view === "top" ? 220 : 2 * halfZ}
              rx="25"
              fill="var(--card)"
              stroke="var(--muted-foreground)"
            />
            {view === "top" && (
              <>
                <path
                  d="M200 10v280M20 150h360"
                  stroke="var(--border)"
                  strokeDasharray="4 4"
                />
                <rect
                  x={200 - halfY * 0.7}
                  y="78"
                  width={halfY * 1.4}
                  height="136"
                  rx="14"
                  fill="var(--secondary)"
                  stroke="var(--border)"
                />
                <text
                  x="200"
                  y="22"
                  textAnchor="middle"
                  fill="var(--muted-foreground)"
                  fontSize="10"
                  stroke="none"
                >
                  {zhCN.settings.vehicleFront}</text>
              </>
            )}
            {cameraNames.map((n, i) => {
              const c = shown(n);
              const x =
                view === "top" ? 200 + c.y * halfY : 200 + c.x * 110;
              const y =
                view === "top" ? 150 - c.x * 110 : 150 - c.z * halfZ;
              const color = [
                "var(--chart-3)",
                "var(--chart-2)",
                "var(--chart-4)",
                "var(--primary)",
              ][i];
              const at = (angle: number, radius: number) => ({
                x: x + Math.sin((angle * Math.PI) / 180) * radius,
                y: y - Math.cos((angle * Math.PI) / 180) * radius,
              });
              const a = at(c.yaw - c.fov / 2, 130);
              const b = at(c.yaw + c.fov / 2, 130);
              const pitchRad = (c.pitch * Math.PI) / 180;
              const facing = Math.cos((c.yaw * Math.PI) / 180) >= 0 ? 1 : -1;
              const dirX = facing * Math.cos(pitchRad) * 55;
              const dirY = -Math.sin(pitchRad) * 55;
              const handle = view === "top"
                ? { x: at(c.yaw, 55).x, y: at(c.yaw, 55).y, kind: "yaw" as const, value: c.yaw }
                : { x: x + dirX, y: y + dirY, kind: "pitch" as const, value: c.pitch };
              return (
                <g key={n}>
                  {view === "top" ? (
                    <path
                      d={`M${x},${y} L${a.x},${a.y} A130,130 0 0 1 ${b.x},${b.y} Z`}
                      fill={color}
                      fillOpacity={camera === n ? 0.19 : 0.05}
                      stroke={color}
                      strokeOpacity={camera === n ? 0.6 : 0.16}
                    />
                  ) : (
                    <path
                      d={`M${x},${y} l${dirX},${dirY}`}
                      stroke={color}
                      strokeWidth="2"
                    />
                  )}
                  <circle
                    className="camera-node"
                    pointerEvents="all"
                    cx={x}
                    cy={y}
                    r={camera === n ? 11 : 8}
                    fill={color}
                    stroke="var(--card)"
                    strokeWidth="2"
                    onPointerDown={(e) => startDrag(e, n)}
                    onPointerMove={moveDrag}
                    onPointerUp={endDrag}
                    onPointerCancel={cancelDrag}
                    onLostPointerCapture={cancelDrag}
                  />
                  <text
                    x={x}
                    y={y + 3}
                    textAnchor="middle"
                    fill="white"
                    fontSize="9"
                    stroke="none"
                    pointerEvents="none"
                  >
                    {i + 1}
                  </text>
                  {camera === n && (
                    <g>
                      {view === "top" && (
                        <line
                          x1={x}
                          y1={y}
                          x2={handle.x}
                          y2={handle.y}
                          stroke={color}
                          strokeWidth="1.5"
                          strokeDasharray="3 3"
                          pointerEvents="none"
                        />
                      )}
                      <circle
                        className="camera-handle"
                        pointerEvents="all"
                        cx={handle.x}
                        cy={handle.y}
                        r="6"
                        fill={color}
                        stroke="var(--card)"
                        strokeWidth="2"
                        onPointerDown={(e) => startAngleDrag(e, n, handle.kind, x, y)}
                        onPointerMove={moveDrag}
                        onPointerUp={endDrag}
                        onPointerCancel={cancelDrag}
                        onLostPointerCapture={cancelDrag}
                      />
                      <text
                        className="camera-angle-readout"
                        x={handle.x + 10}
                        y={handle.y - 8}
                        textAnchor="start"
                        pointerEvents="none"
                      >
                        {`${view === "top" ? zhCN.settings.yawShort : zhCN.settings.pitchShort} ${handle.value.toFixed(1)}°`}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
        <div className="mount-legend">
          {cameraNames.map((n, i) => (
            <Button
              variant="ghost"
              key={n}
              className={camera === n ? "active" : ""}
              onClick={() => setCamera(n)}
            >
              <span
                className="legend-dot"
                style={{
                  background: [
                    "var(--chart-3)",
                    "var(--chart-2)",
                    "var(--chart-4)",
                    "var(--primary)",
                  ][i],
                }}
              >
                {i + 1}
              </span>
              <span>{names[n]}</span>
            </Button>
          ))}
        </div>
      </Card>
      <Card className="dr-card mount-controls gap-0">
        <div className="card-head">
          <div>
            <h2>{names[camera]}</h2>
            {running && <p className="small">{zhCN.settings.cameraCommitHint}</p>}
          </div>
          <div className="flex items-center gap-1">
            <Hint text={zhCN.settings.cameraRestoreHint}>
              <Button variant="ghost" size="sm" onClick={() => commit(camera, structuredClone(initial.current[camera]))}>
                <RotateCcw />{zhCN.settings.cameraRestore}</Button>
            </Hint>
            <Hint text={zhCN.settings.cameraCoordinatesHint}>
              <Button
                variant="ghost"
                className="app-icon-button"
                aria-label={zhCN.settings.cameraCoordinatesHelp}
              >
                <CircleHelp />
              </Button>
            </Hint>
          </div>
        </div>
        <div className="mount-fields">
          {fields.map(([key, label, min, max]) => {
            const pos = ["x", "y", "z"].includes(key);
            const value = pos
              ? Math.round(current[key] * 1000) / 10
              : current[key];
            const changed = (v: number) => ({ ...current, [key]: pos ? v / 100 : v });
            return (
              <label className="dr-field" key={key}>
                <span>{label}</span>
                <div className="range-number">
                  <Slider
                    aria-label={label}
                    className="prototype-slider"
                    min={min}
                    max={max}
                    step={0.1}
                    value={[Math.max(min, Math.min(max, value))]}
                    onValueChange={([v]) => changePreview(camera, changed(v))}
                    onValueCommit={([v]) => commit(camera, changed(v))}
                    onPointerCancel={cancelDrag}
                  />
                  <NumberInput
                    className="input mono"
                    step="0.1"
                    value={value}
                    onValueChange={v => commit(camera, changed(v))}
                  />
                </div>
              </label>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
