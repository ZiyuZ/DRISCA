import { zhCN, format } from "../i18n";
import { useEffect, useState } from "react";
type Snapshot = { running: boolean; speed_mps: number; speed_limit_mps: number; gear: number; control_mode: string; steer: number; takeover_requested: boolean; };
export function Hud() {
  const [s, set] = useState<Snapshot | null>(null);
  const [online, setOnline] = useState(false);
  useEffect(() => {
    const es = new EventSource("/stream");
    es.onopen = () => setOnline(true);
    es.onerror = () => setOnline(false);
    es.onmessage = (e) => set(JSON.parse(e.data));
    return () => es.close();
  }, []);
  return (
    <div className="hud">
      {!online ? <h2>{zhCN.hud.disconnected}</h2> : s?.running ? (
        <>
          <div className="hud-speed">
            {Math.round(s.speed_mps * 3.6)}
            <small> km/h</small>
          </div>
          <p>
            {format(zhCN.hud.drivingStats, { speedLimit: Math.round(s.speed_limit_mps * 3.6), gear: s.gear, mode: s.control_mode === "autopilot" ? zhCN.hud.autopilot : zhCN.hud.manual })}
          </p>
          <p>
            {format(zhCN.hud.steer, { percent: Math.round(s.steer * 100) })}
            {s.takeover_requested ? zhCN.hud.takeover : ""}
          </p>
        </>
      ) : (
        <h2>{zhCN.hud.waiting}</h2>
      )}
    </div>
  );
}
