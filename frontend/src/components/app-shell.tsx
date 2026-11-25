import {
  CarFront,
  CloudSun,
  Copy,
  Database,
  Home,
  Link,
  Minus,
  Monitor,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  SlidersHorizontal,
  Square,
  X,
} from "lucide-react";
import React from "react";
import { toast } from "sonner";
import type { RuntimeState } from "../types/api";
import { Hint } from "./hint";
import { Button } from "./ui/button";

const resizeEdges = [
  ["top", "inset-x-[10px] top-0 h-[5px] cursor-ns-resize"],
  ["bottom", "inset-x-[10px] bottom-0 h-[5px] cursor-ns-resize"],
  ["left", "inset-y-[10px] left-0 w-[5px] cursor-ew-resize"],
  ["right", "inset-y-[10px] right-0 w-[5px] cursor-ew-resize"],
  ["top-left", "top-0 left-0 size-[10px] cursor-nwse-resize"],
  ["top-right", "top-0 right-0 size-[10px] cursor-nesw-resize"],
  ["bottom-left", "bottom-0 left-0 size-[10px] cursor-nesw-resize"],
  ["bottom-right", "bottom-0 right-0 size-[10px] cursor-nwse-resize"],
] as const;

type Props = {
  page: string;
  setPage: (page: string) => void;
  collapsed: boolean;
  setCollapsed: (value: boolean) => void;
  desktop: boolean;
  state: RuntimeState;
  onBeforeClose: () => Promise<void>;
  serviceOnline: boolean;
  onUnreal: () => void;
  onShare: () => void;
  presetAction: React.ReactNode;
  children: React.ReactNode;
};

export function AppShell({
  page,
  setPage,
  collapsed: collapsedSetting,
  setCollapsed,
  desktop,
  state,
  onBeforeClose,
  serviceOnline,
  onUnreal,
  onShare,
  presetAction,
  children,
}: Props) {
  const [phone, setPhone] = React.useState(false);
  const [maximized, setMaximized] = React.useState(false);
  React.useEffect(() => {
    const media = window.matchMedia("(max-width: 640px)");
    const update = () => setPhone(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const collapsed = phone || collapsedSetting;
  const pages = [
    ["控制台", Home],
    ["场景与车辆", SlidersHorizontal],
    ["天气", CloudSun],
    ["交通流", CarFront],
    ["数据管理", Database],
  ] as const;
  const configPages = [
    ["主机配置", Monitor],
    ["输入配置", Settings],
  ] as const;
  const statusMeta: Record<RuntimeState["system_status"], { label: string; dot: string }> = {
    disconnected: { label: "模拟器未连接", dot: " idle" },
    connecting: { label: "模拟器连接中", dot: " connecting" },
    connected: { label: "模拟器已连接", dot: "" },
    running: { label: "实验中", dot: "" },
    error: { label: "运行异常", dot: " error" },
  };
  const currentStatus = statusMeta[state.system_status] ?? statusMeta.disconnected;
  const windowAction = async (action: string) => {
    const webview = (
      window as Window & { pywebview?: { api: Record<string, () => Promise<void>>; }; }
    ).pywebview;
    try {
      if (action === "close_window") await onBeforeClose();
      if (!webview) return;
      await webview.api[action]();
      if (action === "toggle_maximize") setMaximized(value => !value);
    } catch (error) {
      toast.error(String(error));
    }
  };
  return (
    <div className={`prototype-shell shell${desktop ? " desktop" : ""}`}>
      {desktop && resizeEdges.map(([edge, position]) => (
        <div
          key={edge}
          aria-hidden="true"
          className={`fixed z-[60] select-none ${position}`}
          onMouseDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            const webview = (window as Window & {
              pywebview?: { api: { start_resize?: (edge: typeof resizeEdges[number][0]) => void; }; };
            }).pywebview;
            webview?.api.start_resize?.(edge);
          }}
        />
      ))}
      <header className="app-titlebar">
        {!phone && (
          <Button
            variant="ghost"
            className="collapse-button title-collapse"
            aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </Button>
        )}
        <div className="app-identity pywebview-drag-region">
          <strong>DRISCA</strong>
          <span className="app-separator" />
          <span className="page-title">{page}</span>
        </div>
        {!serviceOnline && (
          <span className="title-offline" role="status">管理端连接已断开</span>
        )}
        <div className="title-actions">
          {presetAction}
          <Hint text="连接地址与二维码">
            <Button
              variant="ghost"
              className="app-icon-button"
              onClick={onShare}
              aria-label="连接地址与二维码"
            >
              <Link />
            </Button>
          </Hint>
        </div>
        {desktop && (
          <div className="window-buttons relative z-[61]">
            <Hint text="最小化">
              <Button
                variant="ghost"
                aria-label="最小化"
                onClick={() => windowAction("minimize_window")}
              >
                <Minus />
              </Button>
            </Hint>
            <Hint text={maximized ? "还原" : "最大化"}>
              <Button
                variant="ghost"
                aria-label={maximized ? "还原" : "最大化"}
                onClick={() => windowAction("toggle_maximize")}
              >
                {maximized ? <Copy /> : <Square />}
              </Button>
            </Hint>
            <Hint text="关闭">
              <Button
                variant="ghost"
                className="close"
                aria-label="关闭"
                onClick={() => windowAction("close_window")}
              >
                <X viewBox="4 4 16 16" />
              </Button>
            </Hint>
          </div>
        )}
      </header>
      <div className={`layout${collapsed ? " collapsed" : ""}${serviceOnline ? "" : " service-offline"}`}>
        <aside className="dr-sidebar">
          <nav className="dr-nav" aria-label="主导航">
            {pages.map(([name, Icon]) => (
              <Hint key={name} text={name} enabled={collapsed} side="right">
                <Button
                  variant="ghost"
                  className={page === name ? "selected" : ""}
                  aria-current={page === name ? "page" : undefined}
                  onClick={() => setPage(name)}
                >
                  <Icon />
                  {!collapsed && <span>{name}</span>}
                </Button>
              </Hint>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <nav className="dr-nav" aria-label="配置导航">
              {configPages.map(([name, Icon]) => (
                <Hint key={name} text={name} enabled={collapsed} side="right">
                  <Button
                    variant="ghost"
                    className={page === name ? "selected" : ""}
                    aria-current={page === name ? "page" : undefined}
                    onClick={() => setPage(name)}
                  >
                    <Icon />
                    {!collapsed && <span>{name}</span>}
                  </Button>
                </Hint>
              ))}
            </nav>
            <div className="host-status">
              <Hint text={`${currentStatus.label}，点击管理模拟器连接`} enabled={collapsed} side="right">
                <Button variant="ghost" className="host-label host-status-button" onClick={onUnreal}>
                  <span className={`dot${currentStatus.dot}`} />
                  {!collapsed && <span className="connection-label">{currentStatus.label}</span>}
                </Button>
              </Hint>
            </div>
          </div>
        </aside>
        <main className="dr-main">
          <div
            key={page}
            className={`content${page === "控制台" ? " home-content" : " fixed-content"}`}
          >
            <fieldset disabled={!serviceOnline} className="contents">{children}</fieldset>
          </div>
        </main>
      </div>
    </div>
  );
}
