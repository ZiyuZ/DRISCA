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
    <Button variant="ghost" className="title-preset" onClick={() => onOpenChange(true)}>实验预设：{name || "未选择"}</Button>
    <Modal title={stage === "new" ? "新建预设" : stage === "delete" ? "删除预设" : "实验预设"} open={open} onClose={close} footer={stage === "select" ? <>
      <Button variant="outline" disabled={disabled || pending} onClick={() => { setNewName(""); setStage("new"); }}><Plus />新建</Button>
      <Button variant="outline" disabled={disabled || pending || !name} onClick={() => setStage("delete")}>删除</Button>
    </> : <>
      <Button variant="outline" disabled={pending} onClick={() => setStage("select")}>取消</Button>
      <Button variant={stage === "delete" ? "destructive" : "default"}
        disabled={disabled || pending || (stage === "new" && (!newName.trim() || presets.some(p => p.name === newName.trim())))}
        onClick={() => void perform(() => stage === "new" ? onCreate(newName.trim()) : onDelete())}>
        {stage === "new" ? "新建" : "删除"}
      </Button>
    </>}>
      {stage === "select" ? <>
        <label className="field"><span>实验预设</span><SharedSelect value={name} options={presets.map(p => [p.name, p.name])} disabled={disabled || pending}
          onValueChange={name => void perform(() => onSelect(name))} /></label>
        <label className="switch-row"><Checkbox checked={run.save_data} disabled={disabled} onCheckedChange={value => onRunChange({ ...run, save_data: value === true, enable_carla_recorder: value === true && run.enable_carla_recorder })} />保存数据</label>
        <label className="switch-row"><Checkbox checked={run.enable_carla_recorder} disabled={disabled || !run.save_data} onCheckedChange={value => onRunChange({ ...run, enable_carla_recorder: value === true })} />录像</label>
      </> : stage === "new" ? <label className="field"><span>预设名称</span><Input value={newName} disabled={pending} onChange={event => setNewName(event.target.value)} /></label>
        : <p>删除预设 {name}？</p>}
    </Modal>
  </>;
}
