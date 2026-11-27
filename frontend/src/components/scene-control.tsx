import { zhCN, format } from "../i18n";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { RuntimeState } from "../types/api";
import { Field, Modal, SearchSelect } from "./common";
import { Hint } from "./hint";
import { Button } from "./ui/button";

export function SceneControl({ state, online, host, port, onConnect, onClose }: {
  state: RuntimeState;
  online: boolean;
  host: string;
  port: number;
  onConnect: (host: string, port: number) => Promise<void>;
  onClose: () => void;
}) {
  const [address, setAddress] = useState(host);
  const [serverPort, setServerPort] = useState(port);
  const [map, setMap] = useState(state.catalog.map_name ?? "");
  const [pending, setPending] = useState(false);
  useEffect(() => setMap(state.catalog.map_name ?? ""), [state.catalog.map_name]);
  const idle = state.phase === "idle";
  const connected = online && state.carla_connected && !state.carla_connecting;
  const request = async (action: () => Promise<unknown>) => {
    setPending(true);
    try { await action(); }
    catch (error) { toast.error(error instanceof Error ? error.message : String(error)); }
    finally { setPending(false); }
  };
  return (
    <Modal title={zhCN.carla.sceneControl} open onClose={onClose}>
      <div className="grid min-w-0 gap-5">
        <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_7rem]">
          <Field label={zhCN.carla.address} value={address} onChange={setAddress} disabled={!online || !idle || state.carla_connecting || pending} />
          <Field label={zhCN.carla.port} type="number" value={serverPort} onChange={setServerPort} disabled={!online || !idle || state.carla_connecting || pending} />
        </div>
        <div className="flex justify-end">
          <Button variant="outline" disabled={!online || !idle || state.carla_connecting || pending || !address.trim() || !Number.isInteger(serverPort) || serverPort <= 1024 || serverPort > 65535}
            onClick={() => void request(() => onConnect(address.trim(), serverPort))}>
            {state.carla_connecting ? zhCN.carla.connecting : zhCN.carla.connect}
          </Button>
        </div>
        {state.carla_connected && <div className="grid min-w-0 gap-3 border-t pt-5">
          <span className="text-sm text-muted-foreground">{format(zhCN.carla.currentMap, { mapName: state.catalog.map_name?.split("/").pop() ?? "" })}</span>
          <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <SearchSelect label={zhCN.carla.map} value={map} options={state.catalog.maps.map(value => ({ value, label: value.split("/").pop()! }))}
              onChange={setMap} disabled={!connected || !idle || pending} />
            <Hint text={zhCN.carla.stopBeforeMap} enabled={!idle}>
              <Button disabled={!connected || !idle || pending || !map || map === state.catalog.map_name}
                onClick={() => void request(() => api("/api/world/map", "POST", { map_name: map }))}>{zhCN.carla.changeMap}</Button>
            </Hint>
          </div>
        </div>}
        {state.error && <p role="alert" className="text-sm text-destructive">{state.error}</p>}
      </div>
    </Modal>
  );
}
