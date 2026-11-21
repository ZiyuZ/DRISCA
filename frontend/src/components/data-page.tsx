import { NumberInput } from "./number-input";
import { Download, ListX, Play, Trash2 } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import type { RuntimeState } from "../types/api";
import { Hint } from "./hint";
import { IconAction } from "./icon-action";
import { PageTabs } from "./page-tabs";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Progress } from "./ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./ui/table";

export type Session = {
  session_id: string;
  subject_id: string;
  started_at: number;
  status: string;
  frame_count: number;
  map_name: string;
  note: string;
  finished_at: number | null;
};
export type Recording = {
  name: string;
  size_bytes: number;
  modified_at: number;
};
type Replay = {
  start_time: number;
  duration: number;
  time_factor: number;
  follow_actor_id: number;
};
type Props = {
  tab: string;
  setTab: (value: string) => void;
  state: RuntimeState;
  sessions: Session[];
  total: number;
  selected: string[];
  setSelected: Dispatch<SetStateAction<string[]>>;
  search: string;
  setSearch: (v: string) => void;
  status: string;
  setStatus: (v: string) => void;
  from: string;
  setFrom: (v: string) => void;
  to: string;
  setTo: (v: string) => void;
  onRecent: () => void;
  onExport: () => void;
  onDelete: () => void;
  onDetail: (id: string) => void;
  recordings: Recording[];
  recTotal: number;
  recPage: number;
  setRecPage: (v: number) => void;
  recSearch: string;
  setRecSearch: (v: string) => void;
  recording: string;
  setRecording: (v: string) => void;
  replay: Replay;
  setReplay: (v: Replay) => void;
  onInfo: () => void;
  onReplay: () => void;
};
const date = (n: number) =>
  new Date(n * 1000).toLocaleString("zh-CN", { hour12: false });
export function DataPage(p: Props) {
  const allSelected =
    p.sessions.length > 0 &&
    p.sessions.every((s) => p.selected.includes(s.session_id));
  return (
    <PageTabs value={p.tab} onValueChange={p.setTab}
      items={[["sessions", "会话记录"], ["recordings", "录像回放"]]}>
      {p.tab === "sessions" ? (
        <div className="data-page">
          <Card className="dr-card table-card gap-0">
            <div className="table-top data-filters">
              <Input
                className="input"
                placeholder="搜索被试或会话编号"
                value={p.search}
                onChange={(e) => p.setSearch(e.target.value)}
              />
              <SharedSelect
                className="session-status"
                value={p.status || "all"}
                onValueChange={(value) =>
                  p.setStatus(value === "all" ? "" : value)
                }
                options={[
                  ["all", "全部状态"],
                  ["running", "进行中"],
                  ["committed", "已完成"],
                  ["aborted", "已中止"],
                ]}
              />
              <div className="date-filter">
                <Input
                  className="input"
                  type="date"
                  aria-label="开始日期"
                  value={p.from}
                  onChange={(e) => p.setFrom(e.target.value)}
                />
                <span>至</span>
                <Input
                  className="input"
                  type="date"
                  aria-label="结束日期"
                  value={p.to}
                  onChange={(e) => p.setTo(e.target.value)}
                />
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="recent-filter app-text-button"
                onClick={p.onRecent}
              >
                最近一月
              </Button>
              <Button
                disabled={!p.selected.length || p.state.export.running}
                onClick={p.onExport}
              >
                <Download />
                导出所选{p.selected.length ? ` · ${p.selected.length}` : ""}
              </Button>
              <Button variant="outline" disabled={!p.selected.length || p.state.export.running}
                onClick={p.onDelete}>
                <Trash2 />删除所选
              </Button>
            </div>
            <div className="selection-toolbar">
              <span className="small total-sessions">共 {p.total} 个会话</span>
              <span className="small">已选 {p.selected.length} 个会话</span>
              <Button
                variant="ghost"
                size="sm"
                disabled={!p.sessions.length}
                onClick={() =>
                  p.setSelected((old) => [
                    ...new Set([
                      ...old,
                      ...p.sessions.map((s) => s.session_id),
                    ]),
                  ])
                }
              >
                选择筛选结果全部 {p.sessions.length} 项
              </Button>
              <IconAction
                label="清空选择"
                disabled={!p.selected.length}
                onClick={() => p.setSelected([])}
              >
                <ListX />
              </IconAction>
            </div>
            <div className="table-scroll">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="select-col">
                      <Checkbox
                        aria-label="选择当前筛选的全部实验"
                        checked={allSelected}
                        onCheckedChange={(v) =>
                          p.setSelected((old) =>
                            v
                              ? [
                                ...new Set([
                                  ...old,
                                  ...p.sessions.map((s) => s.session_id),
                                ]),
                              ]
                              : old.filter(
                                (id) =>
                                  !p.sessions.some(
                                    (s) => s.session_id === id,
                                  ),
                              ),
                          )
                        }
                      />
                    </TableHead>
                    <TableHead>会话编号</TableHead>
                    <TableHead>被试编号</TableHead>
                    <TableHead>开始时间</TableHead>
                    <TableHead>地图</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>记录帧数</TableHead>
                    <TableHead>备注</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {p.sessions.map((s) => (
                    <TableRow key={s.session_id}>
                      <TableCell>
                        <Checkbox
                          checked={p.selected.includes(s.session_id)}
                          aria-label={`选择 ${s.subject_id}`}
                          onCheckedChange={(v) =>
                            p.setSelected((old) =>
                              v
                                ? [...old, s.session_id]
                                : old.filter((id) => id !== s.session_id),
                            )
                          }
                        />
                      </TableCell>
                      <TableCell className="mono">{s.session_id}</TableCell>
                      <TableCell className="mono">{s.subject_id}</TableCell>
                      <TableCell className="mono">
                        {date(s.started_at)}
                      </TableCell>
                      <TableCell>{s.map_name}</TableCell>
                      <TableCell>
                        <span
                          className={`dr-badge ${s.status === "committed" ? "live" : "warn"}`}
                        >
                          {s.status === "committed"
                            ? "已完成"
                            : s.status === "aborted"
                              ? "已中止"
                              : "进行中"}
                        </span>
                      </TableCell>
                      <TableCell className="mono">
                        {s.frame_count.toLocaleString()}
                      </TableCell>
                      <TableCell>
                        {s.note}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => p.onDetail(s.session_id)}
                        >
                          详情
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!p.sessions.length && (
                    <TableRow>
                      <TableCell colSpan={9} className="empty">
                        当前条件下暂无实验记录
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </Card>
          {(p.state.export.running ||
            p.state.export.path ||
            p.state.export.error) && (
              <div className="export-status">
                <div className="row spread">
                  <span>
                    {p.state.export.running
                      ? "正在导出"
                      : p.state.export.error || "导出完成"}
                  </span>
                  <span className="mono">{p.state.export.progress}%</span>
                </div>
                <Progress
                  className="progress"
                  max={100}
                  value={p.state.export.progress}
                />
                <span className="small mono">{p.state.export.path}</span>
              </div>
            )}
        </div>
      ) : (
        <div className="tab-scroll replay-page">
          <Card className="dr-card table-card replay-table gap-0">
            <div className="table-top">
              <Input
                className="input"
                placeholder="搜索录像名称"
                value={p.recSearch}
                onChange={(e) => {
                  p.setRecSearch(e.target.value);
                  p.setRecPage(1);
                }}
              />
            </div>
            <div className="table-scroll">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>录像文件</TableHead>
                    <TableHead>大小</TableHead>
                    <TableHead>修改时间</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {p.recordings.map((r) => (
                    <TableRow
                      key={r.name}
                      className={`recording-row${p.recording === r.name ? " chosen" : ""}`}
                      tabIndex={0}
                      onClick={() => p.setRecording(r.name)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          p.setRecording(r.name);
                        }
                      }}
                    >
                      <TableCell className="mono">{r.name}</TableCell>
                      <TableCell>
                        {(r.size_bytes / 1024 / 1024).toFixed(1)} MB
                      </TableCell>
                      <TableCell className="mono">
                        {date(r.modified_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!p.recordings.length && (
                    <TableRow>
                      <TableCell colSpan={3} className="empty">
                        暂无匹配的录像
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
            <div className="pagination">
              <span className="small">共 {p.recTotal} 个录像</span>
              <div className="row">
                <Button
                  variant="outline"
                  disabled={p.recPage <= 1}
                  onClick={() => p.setRecPage(p.recPage - 1)}
                >
                  上一页
                </Button>
                <span className="small mono">
                  {p.recPage} / {Math.max(1, Math.ceil(p.recTotal / 8))}
                </span>
                <Button
                  variant="outline"
                  disabled={p.recPage * 8 >= p.recTotal}
                  onClick={() => p.setRecPage(p.recPage + 1)}
                >
                  下一页
                </Button>
              </div>
            </div>
          </Card>
          <Card className="dr-card replay-settings gap-0">
            <div className="card-head">
              <h2>回放设置</h2>
              <span className="small mono">{p.recording || "请选择录像"}</span>
            </div>
            <div className="replay-form">
              {(
                [
                  ["start_time", "起始时间 · 秒"],
                  ["duration", "回放时长 · 秒"],
                  ["time_factor", "倍速"],
                  ["follow_actor_id", "跟随车辆 ID"],
                ] as const
              ).map(([key, label]) => (
                <label className="dr-field" key={key}>
                  <span>{label}</span>
                  <NumberInput
                    className="input mono"
                    
                    value={p.replay[key]}
                    onValueChange={(value) =>
                      p.setReplay({
                        ...p.replay,
                        [key]: value,
                      })
                    }
                  />
                </label>
              ))}
              <Button
                variant="outline"
                disabled={!p.recording || !p.state.carla_connected || p.state.phase !== "idle"}
                onClick={p.onInfo}
              >
                查看信息
              </Button>
              <Hint
                enabled={!p.state.carla_connected || p.state.phase !== "idle"}
                text={
                  !p.state.carla_connected
                    ? "请先连接 CARLA"
                    : p.state.phase !== "idle"
                      ? "请先结束实验"
                      : "开始回放"
                }
              >
                <span>
                  <Button
                    disabled={
                      !p.recording ||
                      !p.state.carla_connected ||
                      p.state.phase !== "idle"
                    }
                    onClick={p.onReplay}
                  >
                    <Play />
                    开始回放
                  </Button>
                </span>
              </Hint>
            </div>
          </Card>
        </div>
      )}
    </PageTabs>
  );
}
