import { zhCN } from "../i18n";
import type { ReactNode } from "react";
import type { CommandDefinition, CommandField } from "../types/api";
import { ActionTooltip } from "./action-tooltip";
import { NumberInput } from "./number-input";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";

export type EventFieldValue = string | number | boolean;

export const defaultEventFieldValue = (field: CommandField): EventFieldValue => {
  if (field.default !== null) return field.default;
  if (field.type === "boolean") return false;
  if (field.type === "number") return 0;
  return "";
};

type Props = {
  command: CommandDefinition;
  values: Record<string, EventFieldValue>;
  disabled: boolean;
  disabledReason?: string;
  busy: boolean;
  headerAction?: ReactNode;
  onChange: (key: string, value: EventFieldValue) => void;
  onTrigger: () => void;
};

export function EventCard({ command, values, disabled, disabledReason, busy, headerAction, onChange, onTrigger }: Props) {
  return (
    <Card className="dr-card flex h-full flex-col gap-0">
      <div className="card-head">
        <div>
          <h2>{command.label}</h2>
          <p className="small">{command.description}</p>
        </div>
        {headerAction}
      </div>
      <div className="form flex-1">
        {command.fields.map(field => {
          const value = values[field.key] ?? defaultEventFieldValue(field);
          const label = `${field.label}${field.required ? " *" : ""}`;
          if (field.type === "boolean") {
            return (
              <label className="check" key={field.key}>
                <Checkbox
                  checked={value === true}
                  disabled={disabled}
                  onCheckedChange={checked => onChange(field.key, checked === true)}
                />
                {label}
              </label>
            );
          }
          return (
            <label className={`field-row${field.type === "text" ? " wide" : ""}`} key={field.key}>
              <span>{label}</span>
              {field.type === "number" ? (
                <NumberInput
                  className="input mono"
                  step="any"
                  disabled={disabled}
                  value={typeof value === "number" ? value : Number(value) || 0}
                  onValueChange={next => onChange(field.key, next)}
                />
              ) : field.type === "select" ? (
                <SharedSelect
                  value={String(value)}
                  disabled={disabled}
                  options={(field.options ?? []).map(option =>
                    typeof option === "string"
                      ? ([option, option] as const)
                      : ([option.value, option.label] as const),
                  )}
                  onValueChange={next => onChange(field.key, next)}
                />
              ) : (
                <Input
                  className="input"
                  disabled={disabled}
                  value={String(value)}
                  onChange={event => onChange(field.key, event.target.value)}
                />
              )}
            </label>
          );
        })}
      </div>
      <div className="mt-4 flex items-center justify-end border-t border-border/50 pt-3">
        <ActionTooltip reason={disabled ? disabledReason : null}>
          <Button disabled={disabled || busy} onClick={onTrigger}>
            {busy ? zhCN.console.triggering : zhCN.console.triggerNow}
          </Button>
        </ActionTooltip>
      </div>
    </Card>
  );
}
