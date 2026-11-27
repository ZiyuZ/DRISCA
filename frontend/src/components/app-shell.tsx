import { zhCN, format } from "../i18n";
import {
  CarFront,
  CloudSun,
  Copy,
  Database,
  Home,
  Link,
  Map,
  Minus,
  Monitor,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
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
    [zhCN.nav.console, Home],
    [zhCN.nav.scene, Map],
    [zhCN.nav.weather, CloudSun],
    [zhCN.nav.traffic, CarFront],
    [zhCN.nav.data, Database],
  ] as const;
  const configPages = [
    [zhCN.nav.settings, Monitor],
    [zhCN.nav.input, Settings],
  ] as const;
  const statusMeta: Record<RuntimeState["system_status"], { label: string; dot: string }> = {
    disconnected: { label: zhCN.status.carlaDisconnected, dot: " idle" },
    connecting: { label: zhCN.status.carlaConnecting, dot: " connecting" },
    connected: { label: zhCN.status.carlaConnected, dot: "" },
    previewing: { label: zhCN.nav.previewing, dot: "" },
    replaying: { label: zhCN.nav.replaying, dot: "" },
    running: { label: zhCN.status.running, dot: "" },
    error: { label: zhCN.nav.error, dot: " error" },
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
            aria-label={collapsed ? zhCN.nav.expandSidebar : zhCN.nav.collapseSidebar}
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
          <span className="title-offline" role="status">{zhCN.status.serviceDisconnected}</span>
        )}
        <div className="title-actions">
          {presetAction}
          <Hint text={zhCN.nav.manageCarla}>
            <Button
              variant="ghost"
              className="simulator-status-tag"
              data-status={state.system_status}
              aria-label={format(zhCN.nav.manageCarlaStatus, { label: currentStatus.label })}
              onClick={onUnreal}
            >
              <span className={`dot${currentStatus.dot}`} />
              <span>{currentStatus.label}</span>
            </Button>
          </Hint>
          <Hint text={zhCN.nav.share}>
            <Button
              variant="ghost"
              className="app-icon-button"
              onClick={onShare}
              aria-label={zhCN.nav.share}
            >
              <Link />
            </Button>
          </Hint>
        </div>
        {desktop && (
          <div className="window-buttons relative z-[61]">
            <Hint text={zhCN.nav.minimize}>
              <Button
                variant="ghost"
                aria-label={zhCN.nav.minimize}
                onClick={() => windowAction("minimize_window")}
              >
                <Minus />
              </Button>
            </Hint>
            <Hint text={maximized ? zhCN.nav.restore : zhCN.nav.maximize}>
              <Button
                variant="ghost"
                aria-label={maximized ? zhCN.nav.restore : zhCN.nav.maximize}
                onClick={() => windowAction("toggle_maximize")}
              >
                {maximized ? <Copy /> : <Square />}
              </Button>
            </Hint>
            <Hint text={zhCN.common.close}>
              <Button
                variant="ghost"
                className="close"
                aria-label={zhCN.common.close}
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
          <nav className="dr-nav" aria-label={zhCN.nav.mainNavigation}>
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
            <nav className="dr-nav config-nav" aria-label={zhCN.nav.settingsNavigation}>
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
        </aside>
        <main className="dr-main">
          <div
            key={page}
            className={`content${page === zhCN.nav.console ? " home-content" : " fixed-content"}`}
          >
            <fieldset disabled={!serviceOnline} className="contents">{children}</fieldset>
          </div>
        </main>
      </div>
    </div>
  );
}
