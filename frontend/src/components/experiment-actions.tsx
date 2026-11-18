import { Pencil, Plus, X } from "lucide-react";
import { useState } from "react";
import type { CommandDefinition, Instruction } from "../types/api";
import { Field, Modal } from "./common";
import { IconAction } from "./icon-action";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Switch } from "./ui/switch";
const clone = <T,>(value: T): T => structuredClone(value);

export function ExperimentActions({
  instructions,
  markers,
  commands,
  onInstructions,
  onMarkers,
}: {
  instructions: Instruction[];
  markers: string[];
  commands: CommandDefinition[];
  onInstructions: (items: Instruction[]) => void;
  onMarkers: (items: string[]) => void;
}) {
  const [modal, setModal] = useState("");
  const [instruction, setInstruction] = useState<Instruction | null>(null);
  const [markerDraft, setMarkerDraft] = useState<string[]>([]);
  const editInstruction = (item?: Instruction) => {
    const def = commands[0];
    setInstruction(
      item
        ? clone(item)
        : {
          id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`,
          name: "",
          command: def.id,
          params: Object.fromEntries(
            def.fields.map((f) => [f.key, f.default]),
          ),
        },
    );
    setModal("instruction");
  };
  const saveInstructions = (items: Instruction[]) => {
    onInstructions(items);
    setModal("");
  };
  const onInstruction = editInstruction;
  const editMarkers = () => { setMarkerDraft([...markers]); setModal("markers"); };
  return (<>
    <div className="grid2 equal">
      <Card className="dr-card gap-0">
        <div className="card-head">
          <h2>快捷指令</h2>
          <IconAction label="添加指令" onClick={() => onInstruction()}>
            <Plus />
          </IconAction>
        </div>
        <div className="stack">
          {instructions.map((item) => (
            <Button
              key={item.id}
              variant="outline"
              onClick={() => onInstruction(item)}
            >
              {item.name}
            </Button>
          ))}
        </div>
      </Card>
      <Card className="dr-card gap-0">
        <div className="card-head">
          <h2>事件标记</h2>
          <IconAction label="编辑打点" onClick={editMarkers}>
            <Pencil />
          </IconAction>
        </div>
        <div className="stack">
          {markers.map((label, i) => (
            <div key={i}>{label}</div>
          ))}
        </div>
      </Card>
    </div>
    <Modal
      title="预设事件标记"
      open={modal === "markers"}
      onClose={() => setModal("")}
      footer={
        <>
          <span className="marker-add">
            <Button onClick={() => setMarkerDraft([...markerDraft, "新打点"])}>
              添加打点
            </Button>
          </span>
          <Button
            variant="default"
            onClick={() => {
              onMarkers(markerDraft.map((v) => v.trim()).filter(Boolean));
              setModal("");
            }}
          >
            完成
          </Button>
        </>
      }
    >
      <div className="marker-editor">
        {markerDraft.map((label, index) => (
          <div className="row" key={index}>
            <Input
              className="input"
              value={label}
              placeholder="打点名称"
              onChange={(e) =>
                setMarkerDraft(
                  markerDraft.map((item, i) =>
                    i === index ? e.target.value : item,
                  ),
                )
              }
            />
            <Button
              variant="ghost"
              size="icon"
              aria-label="删除打点"
              onClick={() =>
                setMarkerDraft(markerDraft.filter((_, i) => i !== index))
              }
            >
              <X size={16} />
            </Button>
          </div>
        ))}
      </div>
    </Modal>
    <Modal
      title="快捷指令"
      open={modal === "instruction"}
      onClose={() => setModal("")}
      footer={
        <>
          <Button onClick={() => setModal("")}>取消</Button>
          {instruction &&
            instructions.some(
              (i: Instruction) => i.id === instruction.id,
            ) && (
              <Button
                onClick={() => {
                  saveInstructions(
                    instructions.filter(
                      (i: Instruction) => i.id !== instruction.id,
                    ),
                  );
                }}
              >
                删除
              </Button>
            )}
          <Button
            variant="default"
            disabled={!instruction?.name.trim()}
            onClick={() => {
              if (instruction) {
                saveInstructions([
                  ...instructions.filter(
                    (i: Instruction) => i.id !== instruction.id,
                  ),
                  instruction,
                ]);
              }
            }}
          >
            完成
          </Button>
        </>
      }
    >
      {instruction && (
        <>
          <Field
            label="按钮名称"
            value={instruction.name}
            onChange={(v: string) =>
              setInstruction({ ...instruction, name: v })
            }
          />
          <Field
            label="指令类型"
            value={instruction.command}
            options={commands.map((d) => ({
              value: d.id,
              label: d.label,
            }))}
            onChange={(v: string) => {
              const d = commands.find((x) => x.id === v)!;
              setInstruction({
                ...instruction,
                command: v,
                params: Object.fromEntries(
                  d.fields.map((f) => [f.key, f.default]),
                ),
              });
            }}
          />
          {commands
            .find((d) => d.id === instruction.command)
            ?.fields.map((f) =>
              f.type === "boolean" ? (
                <div className="switch-row" key={f.key}>
                  <Switch
                    checked={instruction.params[f.key] === true}
                    onCheckedChange={(v: boolean) =>
                      setInstruction({
                        ...instruction,
                        params: { ...instruction.params, [f.key]: v },
                      })
                    }
                  />
                  {f.label}
                </div>
              ) : (
                <Field
                  key={f.key}
                  label={f.label}
                  type={f.type === "number" ? "number" : "text"}
                  options={f.options}
                  value={f.type === "number" ? Number(instruction.params[f.key]) : String(instruction.params[f.key] ?? "")}
                  onChange={(v: string | number) =>
                    setInstruction({
                      ...instruction,
                      params: { ...instruction.params, [f.key]: v },
                    })
                  }
                />
              ),
            )}
        </>
      )}
    </Modal>

  </>
  );
}
