import { zhCN, format } from "../i18n";
import { NumberInput } from "./number-input";
import { Download, ListX, Play, Square, Trash2 } from "lucide-react";
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
import { Switch } from "./ui/switch";
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
  follow_ego: boolean;
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
  onOpenExportDir: () => void;
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
  onStopReplay: () => void;
};
const date = (n: number) =>
  new Date(n * 1000).toLocaleString("zh-CN", { hour12: false });
export function DataPage(p: Props) {
  const allSelected =
    p.sessions.length > 0 &&
    p.sessions.every((s) => p.selected.includes(s.session_id));
  return (
    <PageTabs value={p.tab} onValueChange={p.setTab}
      items={[["sessions", zhCN.data.sessions], ["recordings", zhCN.data.recordings]]}>
      {p.tab === "sessions" ? (
        <div className="data-page">
          <Card className="dr-card table-card gap-0">
            <div className="table-top data-filters">
              <Input
                className="input"
                placeholder={zhCN.data.searchSessions}
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
                  ["all", zhCN.data.allStatuses],
                  ["running", zhCN.data.running],
                  ["committed", zhCN.data.completed],
                  ["aborted", zhCN.data.aborted],
                ]}
              />
              <div className="date-filter">
                <Input
                  className="input"
                  type="date"
                  aria-label={zhCN.data.startDate}
                  value={p.from}
                  onChange={(e) => p.setFrom(e.target.value)}
                />
                <span>{zhCN.data.dateTo}</span>
                <Input
                  className="input"
                  type="date"
                  aria-label={zhCN.data.endDate}
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
                {zhCN.data.lastMonth}</Button>
              <Button
                disabled={!p.selected.length || p.state.export.running}
                onClick={p.onExport}
              >
                <Download />
                {zhCN.data.exportSelected}{p.selected.length ? ` · ${p.selected.length}` : ""}
              </Button>
              <Button variant="destructive" disabled={!p.selected.length || p.state.export.running}
                onClick={p.onDelete}>
                <Trash2 />{zhCN.data.deleteSelected}</Button>
            </div>
            <div className="selection-toolbar">
              <span className="small total-sessions">{format(zhCN.data.totalSessions, { count: p.total })}</span>
              <span className="small">{format(zhCN.data.selectedSessions, { count: p.selected.length })}</span>
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
                {format(zhCN.data.selectAllFiltered, { count: p.sessions.length })}</Button>
              <IconAction
                label={zhCN.data.clearSelection}
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
                        aria-label={zhCN.data.selectAllSessions}
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
                    <TableHead>{zhCN.data.sessionId}</TableHead>
                    <TableHead>{zhCN.data.subjectId}</TableHead>
                    <TableHead>{zhCN.data.startedAt}</TableHead>
                    <TableHead>{zhCN.data.map}</TableHead>
                    <TableHead>{zhCN.data.status}</TableHead>
                    <TableHead>{zhCN.data.frameCount}</TableHead>
                    <TableHead>{zhCN.data.notes}</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {p.sessions.map((s) => (
                    <TableRow key={s.session_id}>
                      <TableCell>
                        <Checkbox
                          checked={p.selected.includes(s.session_id)}
                          aria-label={format(zhCN.data.selectSubject, { subjectId: s.subject_id })}
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
                            ? zhCN.data.completed
                            : s.status === "aborted"
                              ? zhCN.data.aborted
                              : zhCN.data.running}
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
                          {zhCN.common.details}</Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!p.sessions.length && (
                    <TableRow>
                      <TableCell colSpan={9} className="empty">
                        {zhCN.data.noSessions}</TableCell>
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
                      ? zhCN.data.exporting
                      : p.state.export.error || zhCN.data.exportComplete}
                  </span>
                  <span className="mono">{p.state.export.progress}%</span>
                </div>
                <Progress
                  className="progress"
                  max={100}
                  value={p.state.export.progress}
                />
                {p.state.export.path && (
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                    <span className="small mono min-w-0 break-all">{p.state.export.path}</span>
                    <Button size="sm" variant="outline" onClick={p.onOpenExportDir}>{zhCN.data.openExportFolder}</Button>
                  </div>
                )}
              </div>
            )}
        </div>
      ) : (
        <div className="tab-scroll replay-page">
          <Card className="dr-card table-card replay-table gap-0">
            <div className="table-top">
              <Input
                className="input"
                placeholder={zhCN.data.searchRecordings}
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
                    <TableHead>{zhCN.data.recordingFile}</TableHead>
                    <TableHead>{zhCN.data.size}</TableHead>
                    <TableHead>{zhCN.data.modifiedAt}</TableHead>
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
                        {zhCN.data.noRecordings}</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
            <div className="pagination">
              <span className="small">{format(zhCN.data.totalRecordings, { count: p.recTotal })}</span>
              <div className="row">
                <Button
                  variant="outline"
                  disabled={p.recPage <= 1}
                  onClick={() => p.setRecPage(p.recPage - 1)}
                >
                  {zhCN.data.previousPage}</Button>
                <span className="small mono">
                  {p.recPage} / {Math.max(1, Math.ceil(p.recTotal / 8))}
                </span>
                <Button
                  variant="outline"
                  disabled={p.recPage * 8 >= p.recTotal}
                  onClick={() => p.setRecPage(p.recPage + 1)}
                >
                  {zhCN.data.nextPage}</Button>
              </div>
            </div>
          </Card>
          <Card className="dr-card replay-settings gap-0">
            <div className="card-head">
              <h2>{zhCN.data.replaySettings}</h2>
              <span className="small mono">{p.recording || zhCN.data.chooseRecording}</span>
            </div>
            {p.state.replay.running && <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 p-3" role="status">
              <div className="min-w-0"><strong className="text-sm">{zhCN.data.replaying}</strong><p className="small break-all">{p.state.replay.name}</p></div>
              <Button variant="destructive" size="sm" onClick={p.onStopReplay}><Square />{zhCN.data.stopReplay}</Button>
            </div>}
            {p.state.replay.error && <p className="mb-3 text-sm text-destructive" role="alert">{p.state.replay.error}</p>}
            <div className="replay-form">
              <label className="parameter-wide flex items-start gap-3 rounded-lg border bg-muted/20 p-3">
                <Switch checked={p.replay.follow_ego} onCheckedChange={value => p.setReplay({ ...p.replay, follow_ego: value })} />
                <span className="grid gap-1 text-sm">{zhCN.data.followEgo}<span className="small">{zhCN.data.followEgoHint}</span></span>
              </label>
              {(
                [
                  ["start_time", zhCN.data.replayStart],
                  ["duration", zhCN.data.replayDuration],
                  ["time_factor", zhCN.data.replaySpeed],
                  ["follow_actor_id", zhCN.data.followActor],
                ] as const
              ).map(([key, label]) => (
                <label className="dr-field" key={key}>
                  <span>{label}</span>
                  <NumberInput
                    className="input mono"
                    disabled={key === "follow_actor_id" && p.replay.follow_ego}
                    
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
              <div className="parameter-wide flex flex-wrap justify-end gap-2 border-t pt-3">
              <Button
                variant="outline"
                disabled={!p.recording || !p.state.carla_connected || p.state.phase !== "idle"}
                onClick={p.onInfo}
              >
                {zhCN.data.viewRecordingInfo}</Button>
              <Hint
                enabled={!p.state.carla_connected || p.state.phase !== "idle"}
                text={
                  !p.state.carla_connected
                    ? zhCN.carla.connectFirst
                    : p.state.phase !== "idle"
                      ? zhCN.data.stopExperimentFirst
                      : zhCN.data.startReplay
                }
              >
                <span>
                  <Button
                    disabled={
                      !p.recording ||
                      p.state.replay.running ||
                      !p.state.carla_connected ||
                      p.state.phase !== "idle"
                    }
                    onClick={p.onReplay}
                  >
                    <Play />
                    {zhCN.data.startReplay}</Button>
                </span>
              </Hint>
              </div>
            </div>
          </Card>
        </div>
      )}
    </PageTabs>
  );
}
