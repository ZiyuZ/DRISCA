import { zhCN, format } from "../i18n";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import type { Bootstrap, RuntimeState } from "../types/api";
import { Modal } from "./common";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
type Run = NonNullable<RuntimeState["active_run"]>;

export function PresetManager({ open, onOpenChange, name, presets, disabled, run, onRunChange, onSelect, onCreate, onDelete }: {
  open: boolean; onOpenChange: (open: boolean) => void; name: string; presets: Bootstrap["presets"];
  disabled: boolean; run: Run; onRunChange: (run: Run) => void;
  onSelect: (name: string) => Promise<void>; onCreate: (name: string) => Promise<void>; onDelete: () => Promise<void>;
}) {
  const [stage, setStage] = useState("select");
  const [newName, setNewName] = useState("");
  const [pending, setPending] = useState(false);
  const close = () => { onOpenChange(false); setStage("select"); };
  const perform = async (action: () => Promise<void>) => {
    setPending(true);
    try { await action(); setStage("select"); }
    catch (error) { toast.error(String(error)); }
    finally { setPending(false); }
  };
  return <>
    <Button variant="ghost" className="title-preset" onClick={() => onOpenChange(true)}>{format(zhCN.preset.trigger, { name: name || zhCN.preset.noSelection })}</Button>
    <Modal title={stage === "new" ? zhCN.preset.createDialog : stage === "delete" ? zhCN.preset.deleteDialog : zhCN.preset.dialog} open={open} onClose={close} footer={stage === "select" ? <div className="flex w-full flex-wrap items-center justify-between gap-3">
      <div className="flex gap-2">
        <Button variant="outline" disabled={disabled || pending} onClick={() => { setNewName(""); setStage("new"); }}><Plus />{zhCN.preset.create}</Button>
        <Button variant="destructive" disabled={disabled || pending || !name} onClick={() => setStage("delete")}>{zhCN.preset.deleteDialog}</Button>
      </div>
      <Button onClick={close}>{zhCN.common.done}</Button>
    </div> : <>
      <Button variant="outline" disabled={pending} onClick={() => setStage("select")}>{zhCN.common.cancel}</Button>
      <Button variant={stage === "delete" ? "destructive" : "default"}
        disabled={disabled || pending || (stage === "new" && (!newName.trim() || presets.some(p => p.name === newName.trim())))}
        onClick={() => void perform(() => stage === "new" ? onCreate(newName.trim()) : onDelete())}>
        {stage === "new" ? zhCN.preset.create : zhCN.common.delete}
      </Button>
    </>}>
      {stage === "select" ? <div className="grid gap-5">
        <label className="grid gap-2 text-sm"><span className="font-medium">{zhCN.preset.current}</span><SharedSelect value={name} options={presets.map(p => [p.name, p.name])} disabled={disabled || pending}
          onValueChange={name => void perform(() => onSelect(name))} /></label>
        <section className="grid gap-4 rounded-lg border bg-muted/30 p-4">
          <h3 className="text-sm font-semibold">{zhCN.preset.runSettings}</h3>
          <label className="flex items-start gap-3"><Checkbox className="mt-0.5" checked={run.save_data} disabled={disabled} onCheckedChange={value => onRunChange({ ...run, save_data: value === true, enable_carla_recorder: value === true && run.enable_carla_recorder })} /><span className="grid gap-1 text-sm">{zhCN.preset.saveData}<span className="text-xs text-muted-foreground">{zhCN.preset.saveDataHint}</span></span></label>
          <label className="flex items-start gap-3 border-t pt-4"><Checkbox className="mt-0.5" checked={run.enable_carla_recorder} disabled={disabled || !run.save_data} onCheckedChange={value => onRunChange({ ...run, enable_carla_recorder: value === true })} /><span className="grid gap-1 text-sm">{zhCN.preset.recordReplay}<span className="text-xs text-muted-foreground">{zhCN.preset.recordReplayHint}</span></span></label>
        </section>
      </div> : stage === "new" ? <div className="grid gap-3"><p className="text-sm text-muted-foreground">{zhCN.preset.createHint}</p><label className="grid gap-2 text-sm"><span className="font-medium">{zhCN.preset.name}</span><Input autoFocus placeholder={zhCN.preset.namePlaceholder} value={newName} disabled={pending} onChange={event => setNewName(event.target.value)} /></label></div>
        : <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4"><p className="text-sm">{zhCN.preset.deletePrompt}<strong className="break-all">{name}</strong>？</p></div>}
    </Modal>
  </>;
}
