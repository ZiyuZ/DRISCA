import { CircleHelp, Eye, EyeOff, RotateCcw } from "lucide-react";
import { useRef, useState, type CSSProperties, type PointerEvent } from "react";
import type { CameraViewport, DisplayLayout } from "../types/api";
import { Hint } from "./hint";
import { IconAction } from "./icon-action";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog";
import { Input } from "./ui/input";

type MirrorName = keyof Omit<DisplayLayout, "show_rearview">;
const names: Record<MirrorName, string> = { rear_top: "中央后视镜", rear_left: "左后视镜", rear_right: "右后视镜" };
const mirrorNames = Object.keys(names) as MirrorName[];
type Props = {
  layout: DisplayLayout;
  applied?: DisplayLayout | null;
  resolution: [number, number];
  running: boolean;
  onChange: (layout: DisplayLayout) => void;
  onResolutionChange: (size: [number, number]) => void;
  onApply: (layout: DisplayLayout) => void;
};

export function DisplayLayoutEditor({ layout, applied, resolution, running, onChange, onResolutionChange, onApply }: Props) {
  const initial = useRef(structuredClone(layout));
  const [selected, setSelected] = useState<MirrorName>("rear_top");
  const [customOpen, setCustomOpen] = useState(false);
  const [customSize, setCustomSize] = useState<[number, number]>(resolution);
  const mirror = layout[selected];
  const pending = running && JSON.stringify(layout) !== JSON.stringify(applied);
  const drag = useRef<{ name: MirrorName; original: CameraViewport; x: number; y: number; rect: DOMRect; resize: boolean; } | null>(null);
  const startDrag = (e: PointerEvent, name: MirrorName, resize: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    setSelected(name);
    const canvas = e.currentTarget.closest(".layout-canvas")!;
    drag.current = { name, original: structuredClone(layout[name]), x: e.clientX, y: e.clientY, rect: canvas.getBoundingClientRect(), resize };
  };
  const moveDrag = (e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = (e.clientX - d.x) / d.rect.width;
    const dy = (e.clientY - d.y) / d.rect.height;
    const next = structuredClone(d.original);
    if (d.resize) {
      next.image_size = [Math.max(32, Math.round(d.original.image_size[0] + dx * resolution[0])), Math.max(24, Math.round(d.original.image_size[1] + dy * resolution[1]))];
      next.screen_position = [Math.max(0, Math.min(1, d.original.screen_position[0] + dx / 2)), Math.max(0, Math.min(1, d.original.screen_position[1] + dy / 2))];
    } else next.screen_position = [Math.max(0, Math.min(1, d.original.screen_position[0] + dx)), Math.max(0, Math.min(1, d.original.screen_position[1] + dy))];
    onChange({ ...layout, [d.name]: next });
  };
  const endDrag = () => { drag.current = null; };
  return (
    <>
      <Card className="dr-card unified-layout-card gap-0">
        <div
          className="layout-canvas"
          style={
            {
              aspectRatio: `${resolution[0]}/${resolution[1]}`,
              "--canvas-ratio": resolution[0] / resolution[1],
            } as CSSProperties
          }
        >
          <svg
            className="road-scene"
            viewBox="0 0 800 450"
            preserveAspectRatio="none"
          >
            <rect width="800" height="450" fill="var(--secondary)" />
            <path
              d="M0 210 90 140l55 30 85-75 120 110 80-30 100 40 90-75 90 50 90-40v300H0z"
              fill="var(--muted)"
            />
            <path d="M0 270h800v180H0z" fill="var(--border)" />
            <path
              d="M350 240h100l215 210H135z"
              fill="var(--muted-foreground)"
            />
            <path
              d="M394 260h12l8 53h-28zm-11 80h34l12 86h-58z"
              fill="var(--card)"
            />
            <path
              d="m350 240-215 210m315-210 215 210"
              stroke="var(--card)"
              strokeWidth="4"
            />
            <path d="M0 430q400-40 800 0v20H0z" fill="var(--foreground)" />
          </svg>
          {layout.show_rearview &&
            mirrorNames.map((n, i) => {
              const m =
                layout[n as keyof Omit<DisplayLayout, "show_rearview">];
              const size = m.image_size!;
              return (
                <div
                  key={n}
                  className={`layout-mirror${selected === n ? " selected" : ""}`}
                  onPointerDown={(e) => startDrag(e, n, false)}
                  onPointerMove={moveDrag}
                  onPointerUp={endDrag}
                  onPointerCancel={endDrag}
                  onLostPointerCapture={endDrag}
                  style={{
                    left: `${m.screen_position[0] * 100}%`,
                    top: `${m.screen_position[1] * 100}%`,
                    width: `${(size[0] / resolution[0]) * 100}%`,
                    height: `${(size[1] / resolution[1]) * 100}%`,
                  }}
                >
                  <span className="mirror-number">{i + 1}</span>
                  <button
                    className="resize-handle"
                    aria-label={`缩放${names[n]}`}
                    onPointerDown={(e) => startDrag(e, n, true)}
                  />
                </div>
              );
            })}
          <div className="canvas-floating-controls">
            <SharedSelect
              className="select canvas-resolution"
              disabled={running}
              aria-label="驾驶分辨率"
              value={resolution.join("x")}
              onValueChange={(value) => {
                if (value === "custom") {
                  setCustomSize([...resolution]);
                  setCustomOpen(true);
                } else onResolutionChange(value.split("x").map(Number) as [number, number]);
              }}
              options={[
                ...new Set([
                  resolution.join("x"),
                  "1600x900",
                  "1920x1080",
                  "2560x1440",
                  "3840x1080",
                  "5760x1080",
                ]),
              ].map((value) => [value, value.replace("x", " × ")] as const).concat([["custom", "自定义…"]])}
            />
            <div className="row">
              <Hint
                text={layout.show_rearview ? "隐藏后视镜" : "显示后视镜"}
              >
                <Button
                  variant="ghost"
                  className="canvas-control app-icon-button"
                  onClick={() => onChange({ ...layout, show_rearview: !layout.show_rearview })}
                  aria-label="切换后视镜"
                >
                  {layout.show_rearview ? <Eye /> : <EyeOff />}
                </Button>
              </Hint>
              <Hint text="拖动后视镜移动位置；拖动右下角调整尺寸。">
                <Button
                  variant="ghost"
                  className="canvas-control app-icon-button"
                  aria-label="布局操作说明"
                >
                  <CircleHelp />
                </Button>
              </Hint>
            </div>
          </div>
        </div>
        <div className="mirror-legend">
          {mirrorNames.map((n, i) => (
            <Button
              variant="ghost"
              key={n}
              className={selected === n ? "active" : ""}
              onClick={() => setSelected(n)}
            >
              <b>{i + 1}</b>
              <span>{names[n]}</span>
              <small className="mono">
                {layout[
                  n as keyof Omit<DisplayLayout, "show_rearview">
                ].image_size?.join(" × ")}
              </small>
            </Button>
          ))}
        </div>
        <div className="layout-inspector">
          <div className="row">
            <SharedSelect
              className="select"
              value={selected}
              onValueChange={(value) => setSelected(value as MirrorName)}
              options={mirrorNames.map((name) => [name, names[name]])}
            />
            {["中心 X · px", "中心 Y · px", "宽度 · px", "高度 · px"].map(
              (label, i) => (
                <label className="dr-field" key={label}>
                  <span>{label}</span>
                  <Input
                    className="input mono"
                    type="number"
                    value={
                      i < 2
                        ? Math.round(
                          mirror.screen_position[i] * resolution[i],
                        )
                        : mirror.image_size![i - 2]
                    }
                    onChange={(e) => {
                      const values = [
                        ...(i < 2
                          ? mirror.screen_position
                          : mirror.image_size!),
                      ];
                      values[i < 2 ? i : i - 2] =
                        i < 2
                          ? Number(e.target.value) / resolution[i]
                          : Number(e.target.value);
                      const key = i < 2 ? "screen_position" : "image_size";
                      onChange({ ...layout, [selected]: { ...mirror, [key]: values } });
                    }}
                  />
                </label>
              ),
            )}
          </div>
        </div>
        <div className="layout-footer">
          <IconAction label="撤销本页布局调整" onClick={() => onChange(structuredClone(initial.current))}>
            <RotateCcw />
          </IconAction>
          {pending && <span className="small">待应用</span>}
          <div className="row">
            <Button
              variant="outline"
              disabled={!pending}
              onClick={() => onApply(layout)}
            >
              应用到实验
            </Button>
          </div>
        </div>
      </Card>
      <Dialog open={customOpen} onOpenChange={setCustomOpen}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader><DialogTitle>自定义驾驶分辨率</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            {(["宽度 · px", "高度 · px"] as const).map((label, i) => (
              <label className="field" key={label}><span>{label}</span>
                <Input type="number" min={1} step={1} value={customSize[i]}
                  onChange={(e) => setCustomSize((old) => i === 0 ? [Number(e.target.value), old[1]] : [old[0], Number(e.target.value)])} />
              </label>
            ))}
          </div>
          <DialogFooter>
            <Button disabled={!customSize.every((v) => Number.isInteger(v) && v > 0)}
              onClick={() => { onResolutionChange(customSize); setCustomOpen(false); }}>应用</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
