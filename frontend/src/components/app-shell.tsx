import {
  CarFront,
  CloudSun,
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
    ["方案配置", SlidersHorizontal],
    ["天气", CloudSun],
    ["交通流", CarFront],
    ["数据管理", Database],
  ] as const;
  const configPages = [
    ["主机配置", Monitor],
    ["输入配置", Settings],
  ] as const;
  const phase = state.unreal.phase;
  const simulatorState = state.carla_connected
    ? "已连接"
    : state.carla_connecting
      ? "连接中"
      : phase === "starting"
        ? "正在启动"
        : phase === "stopping"
          ? "正在关闭"
          : phase === "error"
            ? "运行异常"
            : phase === "running"
              ? "运行中未连接"
              : "未启动";
  const simulatorDot = state.carla_connected
    ? ""
    : state.carla_connecting || phase === "starting" || phase === "stopping"
      ? " connecting"
      : " idle";
  const collecting = state.worker_state === "running";
  const windowAction = async (action: string) => {
    const webview = (
      window as Window & { pywebview?: { api: Record<string, () => void>; }; }
    ).pywebview;
    try {
      if (action === "close_window") await onBeforeClose();
      webview?.api[action]();
    } catch (error) {
      toast.error(String(error));
    }
  };
  return (
    <div className={`prototype-shell shell${desktop ? " desktop" : ""}`}>
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
          <div className="window-buttons">
            <Hint text="最小化">
              <Button
                variant="ghost"
                aria-label="最小化"
                onClick={() => windowAction("minimize_window")}
              >
                <Minus />
              </Button>
            </Hint>
            <Hint text="最大化 / 还原">
              <Button
                variant="ghost"
                aria-label="最大化 / 还原"
                onClick={() => windowAction("toggle_maximize")}
              >
                <Square />
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
              <Hint text={`模拟器 · ${simulatorState}，点击启动、关闭或连接`} enabled={collapsed} side="right">
                <Button variant="ghost" className="host-label host-status-button" onClick={onUnreal}>
                  <span className={`dot${simulatorDot}`} />
                  {!collapsed && <span className="connection-label">模拟器{simulatorState}</span>}
                </Button>
              </Hint>
              <Hint
                enabled={collapsed}
                side="right"
                text={collecting ? "实验采集 · 运行中" : "实验采集 · 未启动"}
              >
                <div className="host-label host-status-line" role="status" aria-live="polite">
                  <span className={`dot${collecting ? "" : " idle"}`} />
                  {!collapsed && (
                    <span className="connection-label">
                      实验采集{collecting ? "运行中" : "未启动"}
                    </span>
                  )}
                </div>
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
