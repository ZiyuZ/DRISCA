import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { CommandCategory, CommandDefinition } from "../types/api";
import { defaultEventFieldValue, EventCard, type EventFieldValue } from "./event-card";

type Props = {
  commands: CommandDefinition[];
  category: CommandCategory;
  disabled: boolean;
  disabledReason?: string;
  title: string;
  description?: string;
  cardHeaderAction?: (command: CommandDefinition) => ReactNode;
};
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export function EventActionPanel({ commands, category, disabled, disabledReason, title, description, cardHeaderAction }: Props) {
  const items = commands.filter(command => command.category === category);
  const [values, setValues] = useState<Record<string, Record<string, EventFieldValue>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => {
    setValues(current => {
      let changed = false;
      const next = { ...current };
      for (const command of commands) {
        if (command.category !== category || next[command.id]) continue;
        next[command.id] = Object.fromEntries(
          command.fields.map(field => [field.key, defaultEventFieldValue(field)]),
        );
        changed = true;
      }
      return changed ? next : current;
    });
  }, [commands, category]);
  const setValue = (commandId: string, key: string, value: EventFieldValue) =>
    setValues(current => ({
      ...current,
      [commandId]: { ...(current[commandId] ?? {}), [key]: value },
    }));
  const trigger = async (command: CommandDefinition) => {
    setBusy(command.id);
    const params = values[command.id]
      ?? Object.fromEntries(command.fields.map(field => [field.key, defaultEventFieldValue(field)]));
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
        <div className="grid items-stretch gap-4 [grid-template-columns:repeat(auto-fill,minmax(320px,1fr))]">
          {items.map(command => (
            <EventCard
              key={command.id}
              command={command}
              values={values[command.id] ?? {}}
              disabled={disabled}
              disabledReason={disabledReason}
              busy={busy === command.id}
              headerAction={cardHeaderAction?.(command)}
              onChange={(key, value) => setValue(command.id, key, value)}
              onTrigger={() => void trigger(command)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
