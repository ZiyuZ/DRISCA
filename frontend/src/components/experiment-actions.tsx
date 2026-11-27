import { zhCN } from "../i18n";
import { X } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { CommandDefinition, Instruction } from "../types/api";
import { Field, Modal } from "./common";

import { Button } from "./ui/button";

import { Input } from "./ui/input";
import { Switch } from "./ui/switch";
const clone = <T,>(value: T): T => structuredClone(value);

export function ExperimentActions({
  instructions,
  markers,
  commands,
  onInstructions,
  onMarkers,
  children,
}: {
  instructions: Instruction[];
  markers: string[];
  commands: CommandDefinition[];
  onInstructions: (items: Instruction[]) => void;
  onMarkers: (items: string[]) => void;
  children: (actions: { editInstruction: (item?: Instruction) => void; editMarkers: () => void }) => ReactNode;
}) {
  const [modal, setModal] = useState("");
  const [instruction, setInstruction] = useState<Instruction | null>(null);
  const [markerDraft, setMarkerDraft] = useState<string[]>([]);
  const editInstruction = (item?: Instruction) => {
    const def = commands[0];
    if (!item && !def) return;
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
    {children({ editInstruction: onInstruction, editMarkers })}
    <Modal
      title={zhCN.console.markerDialog}
      className={markerDraft.length >= 4 ? "sm:max-w-2xl" : undefined}
      open={modal === "markers"}
      onClose={() => setModal("")}
      footer={
        <>
          <span className="marker-add">
            <Button onClick={() => setMarkerDraft([...markerDraft, zhCN.console.newMarker])}>
              {zhCN.console.addMarker}</Button>
          </span>
          <Button
            variant="default"
            onClick={() => {
              onMarkers(markerDraft.map((v) => v.trim()).filter(Boolean));
              setModal("");
            }}
          >
            {zhCN.common.done}</Button>
        </>
      }
    >
      <div className={markerDraft.length >= 4 ? "marker-editor dialog-parameters" : "marker-editor"}>
        {markerDraft.map((label, index) => (
          <div className="row" key={index}>
            <Input
              className="input"
              value={label}
              placeholder={zhCN.console.markerName}
              onChange={(e) =>
                setMarkerDraft(
                  markerDraft.map((item, i) =>
                    i === index ? e.target.value : item,
                  ),
                )
              }
            />
            <Button
              variant="destructive"
              size="icon"
              aria-label={zhCN.console.deleteMarker}
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
      title={zhCN.console.instructionDialog}
      className="sm:max-w-2xl"
      open={modal === "instruction"}
      onClose={() => setModal("")}
      footer={
        <>
          <Button variant="outline" onClick={() => setModal("")}>{zhCN.common.cancel}</Button>
          {instruction &&
            instructions.some(
              (i: Instruction) => i.id === instruction.id,
            ) && (
              <Button
                variant="destructive"
                onClick={() => {
                  saveInstructions(
                    instructions.filter(
                      (i: Instruction) => i.id !== instruction.id,
                    ),
                  );
                }}
              >
                {zhCN.common.delete}</Button>
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
            {zhCN.common.done}</Button>
        </>
      }
    >
      {instruction && (
        <div className="dialog-parameters">
          <div className="parameter-wide">
          <Field
            label={zhCN.console.instructionName}
            value={instruction.name}
            onChange={(v: string) =>
              setInstruction({ ...instruction, name: v })
            }
          />
          </div>
          <div className="parameter-wide">
          <Field
            label={zhCN.console.instructionType}
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
          </div>
          {commands
            .find((d) => d.id === instruction.command)
            ?.fields.map((f) =>
              f.type === "boolean" ? (
                <label className="switch-row parameter-wide" key={f.key}>
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
                </label>
              ) : (
                <div className={f.type === "text" ? "parameter-wide" : "min-w-0"} key={f.key}>
                <Field
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
                </div>
              ),
            )}
        </div>
      )}
    </Modal>

  </>
  );
}
