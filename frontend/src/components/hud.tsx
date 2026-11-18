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
      {!online ? <h2>管理服务连接已断开</h2> : s?.running ? (
        <>
          <div className="hud-speed">
            {Math.round(s.speed_mps * 3.6)}
            <small> km/h</small>
          </div>
          <p>
            限速 {Math.round(s.speed_limit_mps * 3.6)}　挡位 {s.gear}
            {s.control_mode === "autopilot" ? "自动驾驶" : "人工驾驶"}
          </p>
          <p>
            转向 {Math.round(s.steer * 100)}%
            {s.takeover_requested ? "请接管车辆" : ""}
          </p>
        </>
      ) : (
        <h2>等待实验开始</h2>
      )}
    </div>
  );
}
