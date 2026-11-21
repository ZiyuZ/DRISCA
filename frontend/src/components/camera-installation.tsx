import { CircleHelp, RotateCcw } from "lucide-react";
import { useRef, useState, type PointerEvent } from "react";
import type { Camera, PresetConfig } from "../types/api";
import { Hint } from "./hint";
import { IconAction } from "./icon-action";
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

export function CameraInstallation({ cameras, applied, extent = { x: 2, y: 1, z: 1 }, running, onChange, onApply }: Props) {
  const initial = useRef(structuredClone(cameras));
  const [camera, setCamera] = useState<CameraName>("front");
  const [view, setView] = useState<"top" | "side">("top");
  const current = cameras[camera];
  const pending = running && JSON.stringify(current) !== JSON.stringify(applied?.[camera]);
  const halfY = 110 * extent.y / extent.x;
  const halfZ = 110 * extent.z / extent.x;
  const drag = useRef<{ name: CameraName; original: Camera; start: DOMPoint; svg: SVGSVGElement; } | null>(null);
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
    drag.current = { name, original: { ...cameras[name] }, start: point(svg, e), svg };
  };
  const moveDrag = (e: PointerEvent<SVGCircleElement>) => {
    const d = drag.current;
    if (!d) return;
    const p = point(d.svg, e);
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
              const point = (angle: number) => ({
                x: x + Math.sin((angle * Math.PI) / 180) * 130,
                y: y - Math.cos((angle * Math.PI) / 180) * 130,
              });
              const a = point(c.yaw - c.fov / 2);
              const b = point(c.yaw + c.fov / 2);
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
                      d={`M${x},${y} l${Math.cos((c.pitch * Math.PI) / 180) * Math.cos((c.yaw * Math.PI) / 180) * 55},${-Math.sin((c.pitch * Math.PI) / 180) * 55}`}
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
          <h2>{names[camera]}</h2>
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
        <div className="row mount-save">
          <IconAction label="撤销本页相机调整" onClick={() => onChange(camera, structuredClone(initial.current[camera]))}>
            <RotateCcw />
          </IconAction>
          {pending && <span className="small">待应用</span>}
          <Button
            variant="outline"
            disabled={!pending}
            onClick={() => onApply(camera, current)}
          >
            应用到实验
          </Button>
        </div>
      </Card>
    </div>
  );
}
