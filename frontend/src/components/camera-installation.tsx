import { CircleHelp, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import type { Camera, PresetConfig } from "../types/api";
import { Hint } from "./hint";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { NumberInput } from "./number-input";
import { Slider } from "./ui/slider";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

export type CameraName = keyof PresetConfig["cameras"];
const names: Record<CameraName, string> = {
  front: "主视图", rear_top: "中央后视镜", rear_left: "左后视镜", rear_right: "右后视镜",
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

export function CameraInstallation({ cameras, applied, extent = { x: 2, y: 1, z: 1 }, running, onChange, onApply }: Props) {
  const initial = useRef(structuredClone(cameras));
  const [camera, setCamera] = useState<CameraName>("front");
  const [view, setView] = useState<"top" | "side">("top");
  const current = cameras[camera];
  const halfY = 110 * extent.y / extent.x;
  const halfZ = 110 * extent.z / extent.x;
  const drag = useRef<DragState | null>(null);
  const applyRef = useRef(onApply);
  useEffect(() => {
    applyRef.current = onApply;
  }, [onApply]);
  useEffect(() => {
    if (!running) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    for (const name of cameraNames) {
      if (JSON.stringify(cameras[name]) === JSON.stringify(applied?.[name])) continue;
      timers.push(setTimeout(() => applyRef.current(name, cameras[name]), 250));
    }
    return () => {
      for (const timer of timers) clearTimeout(timer);
    };
  }, [running, cameras, applied]);
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
      onChange(d.name, { ...d.original, yaw: Math.round(yaw * 10) / 10 });
      return;
    }
    if (d.kind === "pitch") {
      const ratio = Math.max(-1, Math.min(1, -(p.y - d.nodeY) / 55));
      const pitch = Math.asin(ratio) * 180 / Math.PI;
      onChange(d.name, { ...d.original, pitch: Math.round(pitch * 10) / 10 });
      return;
    }
    const dx = p.x - d.start.x;
    const dy = p.y - d.start.y;
    onChange(d.name, {
      ...d.original,
      x: d.original.x + (view === "top" ? -dy / 110 : dx / 110),
      ...(view === "top" ? { y: d.original.y + dx / halfY } : { z: d.original.z - dy / halfZ }),
    });
  };
  const endDrag = () => { drag.current = null; };
  const fields = [
    ["x", "前后位置 X · %", -100, 100], ["y", "左右位置 Y · %", -100, 100],
    ["z", "安装高度 Z · %", -100, 100], ["pitch", "俯仰角 · °", -90, 90],
    ["yaw", "偏航角 · °", -180, 180], ["roll", "翻滚角 · °", -180, 180],
    ["fov", "水平视野角 · °", 30, 150],
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
              <TabsTrigger value="top">顶视图</TabsTrigger>
              <TabsTrigger value="side">侧视图</TabsTrigger>
            </TabsList>
          </Tabs>
          <svg
            className="mount-diagram"
            viewBox="0 0 400 300"
            aria-label="车辆与相机安装位置示意"
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
                  车头 · +X
                </text>
              </>
            )}
            {cameraNames.map((n, i) => {
              const c = cameras[n];
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
                    onPointerCancel={endDrag}
                    onLostPointerCapture={endDrag}
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
                        onPointerCancel={endDrag}
                        onLostPointerCapture={endDrag}
                      />
                      <text
                        className="camera-angle-readout"
                        x={handle.x + 10}
                        y={handle.y - 8}
                        textAnchor="start"
                        pointerEvents="none"
                      >
                        {`${view === "top" ? "偏航" : "俯仰"} ${handle.value.toFixed(1)}°`}
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
            {running && <p className="small">调整后约 250ms 自动实时生效</p>}
          </div>
          <div className="flex items-center gap-1">
            <Hint text="恢复为进入本页时的相机设置">
              <Button variant="ghost" size="sm" onClick={() => onChange(camera, structuredClone(initial.current[camera]))}>
                <RotateCcw />恢复默认
              </Button>
            </Hint>
            <Hint text="位置以车身包围盒中心为 0%，边界为 ±100%。数字框可输入车身范围外的位置。">
              <Button
                variant="ghost"
                className="app-icon-button"
                aria-label="相机坐标说明"
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
            const change = (v: number) =>
              onChange(camera, { ...current, [key]: pos ? v / 100 : v });
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
                    onValueChange={([v]) => change(v)}
                  />
                  <NumberInput
                    className="input mono"
                    step="0.1"
                    value={value}
                    onValueChange={change}
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
