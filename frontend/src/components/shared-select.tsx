import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import { cn } from "../lib/utils";

type Props = {
  value: string;
  onValueChange: (value: string) => void;
  options: readonly (readonly [string, string])[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
};
export function SharedSelect({
  value,
  onValueChange,
  options,
  placeholder,
  className,
  disabled,
  "aria-label": label,
}: Props) {
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger className={cn("w-full", className)} aria-label={label}>
        <SelectValue placeholder={placeholder}>{options.find(([key]) => key === value)?.[1]}</SelectValue>
      </SelectTrigger>
      <SelectContent position="popper">
        {options.map(([key, text]) => (
          <SelectItem key={key} value={key}>
            {text}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
