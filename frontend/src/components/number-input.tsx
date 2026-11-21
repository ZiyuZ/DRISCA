import { useState, type ComponentProps } from "react";
import { Input } from "./ui/input";

type Props = Omit<ComponentProps<typeof Input>, "type" | "value" | "defaultValue" | "onChange"> & {
  value: number;
  onValueChange: (value: number) => void;
};

export function NumberInput({ value, onValueChange, onFocus, onBlur, onKeyDown, step = "any", ...props }: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  return <Input {...props} type="number" step={step} value={draft ?? value}
    onFocus={event => { setDraft(event.currentTarget.value); onFocus?.(event); }}
    onChange={event => setDraft(event.currentTarget.value)}
    onBlur={event => {
      const input = event.currentTarget;
      if (input.value !== "" && input.validity.valid && Number.isFinite(input.valueAsNumber)) {
        onValueChange(input.valueAsNumber);
      } else if (input.value !== "" || input.validity.badInput) {
        input.reportValidity();
      }
      setDraft(null);
      onBlur?.(event);
    }}
    onKeyDown={event => {
      onKeyDown?.(event);
      if (!event.defaultPrevented && event.key === "Enter" && !event.nativeEvent.isComposing) {
        event.preventDefault();
        event.currentTarget.blur();
      }
    }} />;
}
