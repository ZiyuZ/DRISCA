import { zhCN, format } from "../i18n";
import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { useRememberedTab } from "../hooks/use-remembered-tab";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { RuntimeState } from "../types/api";
import { Modal } from "./common";
import { DataPage, type Recording, type Session } from "./data-page";
import { Button } from "./ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
type SessionDetail = {
  session: Omit<Session, "frame_count"> & { ego_type_id: string | null; };
  frame_count: number;
  run_config: unknown;
  events: { timestamp: number; frame_no: number | null; name: string; source: string; payload_json: string; }[];
};
const day = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const date = (n: number) => new Date(n * 1000).toLocaleString("zh-CN", { hour12: false });
export function DataManager({ state, online }: { state: RuntimeState; online: boolean; }) {
  const [dataTab, setDataTab] = useRememberedTab("data", "sessions");
  const [modal, setModal] = useState("");
  const [revision, setRevision] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const call = async (action: () => Promise<unknown>, success?: string) => {
    try { await action(); if (success) toast.success(success); }
    catch (error) { toast.error(String(error)); }
  };
  const [from, setFrom] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return day(d);
  }),
    [to, setTo] = useState(() => day(new Date())),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [sessions, setSessions] = useState<Session[]>([]),
    [total, setTotal] = useState(0),
    [selected, setSelected] = useState<string[]>([]),
    [detail, setDetail] = useState<SessionDetail | null>(null),
    [recordings, setRecordings] = useState<Recording[]>([]),
    [recTotal, setRecTotal] = useState(0),
    [recSearch, setRecSearch] = useState(""),
    [recPage, setRecPage] = useState(1),
    [recording, setRecording] = useState(""),
    [recInfo, setRecInfo] = useState(""),
    [replay, setReplay] = useState({
      start_time: 0,
      duration: 0,
      time_factor: 1,
      follow_actor_id: 0,
      follow_ego: true,
    });
  useEffect(() => {
    if (!online || dataTab !== "sessions") return;
    const controller = new AbortController();
    const query = new URLSearchParams({ start_date: from, end_date: to, status, search });
    void api<{ items: Session[]; total: number; }>("/api/sessions?" + query, "GET", undefined, controller.signal)
      .then(result => { setSessions(result.items); setTotal(result.total); })
      .catch(error => { if (!controller.signal.aborted) toast.error(String(error)); });
    return () => controller.abort();
  }, [dataTab, from, to, status, search, online, state.phase, revision]);
  useEffect(() => {
    if (!online || dataTab !== "recordings") return;
    const controller = new AbortController();
    const query = new URLSearchParams({ search: recSearch, page: String(recPage), page_size: "8" });
    void api<{ items: Recording[]; total: number; }>("/api/recordings?" + query, "GET", undefined, controller.signal)
      .then(result => { setRecordings(result.items); setRecTotal(result.total); })
      .catch(error => { if (!controller.signal.aborted) toast.error(String(error)); });
    return () => controller.abort();
  }, [dataTab, recSearch, recPage, online]);
  return <>
    <DataPage
      tab={dataTab}
      setTab={setDataTab}
      state={state}
      sessions={sessions}
      total={total}
      selected={selected}
      setSelected={setSelected}
      search={search}
      setSearch={setSearch}
      status={status}
      setStatus={setStatus}
      from={from}
      setFrom={setFrom}
      to={to}
      setTo={setTo}
      onRecent={() => {
        const now = new Date();
        const before = new Date(now);
        before.setDate(now.getDate() - 30);
        setFrom(day(before));
        setTo(day(now));
      }}
      onExport={() =>
        call(() =>
          api("/api/export", "POST", { session_ids: selected }),
        )
      }
      onOpenExportDir={() => void call(() => api("/api/data/open-export-dir", "POST"))}
      onDelete={() => setModal("delete")}
      onDetail={(id) =>
        call(async () => {
          setDetail(
            await api<SessionDetail>("/api/sessions/" + encodeURIComponent(id)),
          );
          setModal("detail");
        })
      }
      recordings={recordings}
      recTotal={recTotal}
      recPage={recPage}
      setRecPage={setRecPage}
      recSearch={recSearch}
      setRecSearch={setRecSearch}
      recording={recording}
      setRecording={setRecording}
      replay={replay}
      setReplay={setReplay}
      onInfo={() =>
        call(async () => {
          const r = await api<{ text: string; }>("/api/recordings/info", "POST", {
            name: recording,
          });
          setRecInfo(r.text);
          setModal("recording");
        })
      }
      onReplay={() =>
        call(
          () =>
            api("/api/recordings/replay", "POST", {
              name: recording,
              ...replay,
              follow_actor_id: replay.follow_ego ? 0 : replay.follow_actor_id,
            }),
          zhCN.data.replayStarted,
        )
      }
      onStopReplay={() => void call(() => api("/api/recordings/stop", "POST"), zhCN.data.replayStopped)}
    />
    <Modal title={zhCN.data.deleteSessions} open={modal === "delete"} onClose={() => { if (!deleting) setModal(""); }}
      footer={<>
        <Button variant="outline" disabled={deleting} onClick={() => setModal("")}>{zhCN.common.cancel}</Button>
        <Button variant="destructive" disabled={deleting || !online} onClick={() => void call(async () => {
          setDeleting(true);
          try {
            await api("/api/sessions/delete", "POST", { session_ids: selected });
            setSelected([]);
            setModal("");
            setRevision(value => value + 1);
          } finally { setDeleting(false); }
        }, zhCN.data.sessionsDeleted)}>{zhCN.common.delete}</Button>
      </>}>
      <p>{format(zhCN.data.deleteSelectedPrompt, { count: selected.length })}</p>
    </Modal>
    <Modal
      title={zhCN.data.sessionDetails}
      open={modal === "detail"}
      onClose={() => setModal("")}
    >
      <h3>{zhCN.data.sessionInfo}</h3>
      {detail && (
        <Table>
          <TableBody>
            {[
              [zhCN.data.sessionId, detail.session.session_id],
              [zhCN.data.subjectId, detail.session.subject_id],
              [zhCN.data.startedAt, date(detail.session.started_at)],
              [zhCN.data.endedAt, detail.session.finished_at ? date(detail.session.finished_at) : ""],
              [zhCN.data.status, { running: zhCN.data.running, committed: zhCN.data.completed, aborted: zhCN.data.aborted }[detail.session.status]],
              [zhCN.data.map, detail.session.map_name],
              [zhCN.data.vehicle, detail.session.ego_type_id],
              [zhCN.data.frameCount, detail.frame_count],
              [zhCN.data.notes, detail.session.note],
            ].map(([label, v]) => (
              <TableRow key={label}>
                <TableHead>{label}</TableHead>
                <TableCell>{String(v ?? "")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Collapsible>
        <CollapsibleTrigger asChild><Button variant="ghost">{zhCN.data.runConfig}<ChevronDown /></Button></CollapsibleTrigger>
        <CollapsibleContent><pre>{detail && JSON.stringify(detail.run_config, null, 2)}</pre></CollapsibleContent>
      </Collapsible>
      <h3>{zhCN.data.events}</h3>
      {detail && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{zhCN.data.time}</TableHead>
              <TableHead>{zhCN.data.frame}</TableHead>
              <TableHead>{zhCN.data.event}</TableHead>
              <TableHead>{zhCN.data.source}</TableHead>
              <TableHead>{zhCN.common.details}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {detail.events.map((e, i) => (
              <TableRow key={i}>
                <TableCell>{date(e.timestamp)}</TableCell>
                <TableCell>{e.frame_no}</TableCell>
                <TableCell>{e.name}</TableCell>
                <TableCell>{e.source}</TableCell>
                <TableCell>{e.payload_json}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Modal>
    <Modal
      title={zhCN.data.recordingInfo}
      open={modal === "recording"}
      onClose={() => setModal("")}
    >
      <pre>{recInfo}</pre>
    </Modal>
  </>;
}
