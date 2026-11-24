import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { CommandCategory, CommandDefinition, CommandField } from "../types/api";
import { NumberInput } from "./number-input";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";

type Value = string | number | boolean;
type Props = {
  commands: CommandDefinition[];
  category: CommandCategory;
  disabled: boolean;
  title: string;
  description?: string;
};
const defaultFor = (field: CommandField): Value => {
  if (field.default !== null) return field.default;
  if (field.type === "boolean") return false;
  if (field.type === "number") return 0;
  return "";
};
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export function EventActionPanel({ commands, category, disabled, title, description }: Props) {
  const items = commands.filter(command => command.category === category);
  const [values, setValues] = useState<Record<string, Record<string, Value>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => {
    setValues(current => {
      let changed = false;
      const next = { ...current };
      for (const command of commands) {
        if (command.category !== category || next[command.id]) continue;
        next[command.id] = Object.fromEntries(
          command.fields.map(field => [field.key, defaultFor(field)]),
        );
        changed = true;
      }
      return changed ? next : current;
    });
  }, [commands, category]);
  const setValue = (commandId: string, key: string, value: Value) =>
    setValues(current => ({
      ...current,
      [commandId]: { ...(current[commandId] ?? {}), [key]: value },
    }));
  const trigger = async (command: CommandDefinition) => {
    setBusy(command.id);
    const params = values[command.id]
      ?? Object.fromEntries(command.fields.map(field => [field.key, defaultFor(field)]));
    try {
      await api(`/api/commands/${encodeURIComponent(command.id)}/trigger`, "POST", params);
      toast.success(`${command.label}已触发`);
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setBusy(null);
    }
  };
  return (
    <section className="stack event-panel">
      <div className="card-head">
        <div>
          <h2>{title}</h2>
          {description && <p className="small">{description}</p>}
        </div>
      </div>
      {items.length === 0 && <p className="small">当前没有可触发的事件。</p>}
      {items.length > 0 && (
        <div className="grid2 equal">
          {items.map(command => (
            <Card className="dr-card gap-0" key={command.id}>
              <div className="card-head">
                <div>
                  <h2>{command.label}</h2>
                  <p className="small">{command.description}</p>
                </div>
              </div>
              <div className="form">
                {command.fields.map(field => {
                  const value = values[command.id]?.[field.key] ?? defaultFor(field);
                  const label = `${field.label}${field.required ? " *" : ""}`;
                  if (field.type === "boolean") {
                    return (
                      <label className="check" key={field.key}>
                        <Checkbox checked={value === true} disabled={disabled}
                          onCheckedChange={checked => setValue(command.id, field.key, checked === true)} />
                        {label}
                      </label>
                    );
                  }
                  return (
                    <label className="dr-field" key={field.key}>
                      <span>{label}</span>
                      {field.type === "number" ? (
                        <NumberInput className="input mono" step="any" disabled={disabled}
                          value={typeof value === "number" ? value : Number(value) || 0}
                          onValueChange={next => setValue(command.id, field.key, next)} />
                      ) : field.type === "select" ? (
                        <SharedSelect value={String(value)} disabled={disabled}
                          options={(field.options ?? []).map(option => [option, option] as const)}
                          onValueChange={next => setValue(command.id, field.key, next)} />
                      ) : (
                        <Input className="input" disabled={disabled} value={String(value)}
                          onChange={event => setValue(command.id, field.key, event.target.value)} />
                      )}
                    </label>
                  );
                })}
                <Button className="justify-self-start" disabled={disabled || busy === command.id}
                  onClick={() => void trigger(command)}>
                  {busy === command.id ? "触发中…" : "立即触发"}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
