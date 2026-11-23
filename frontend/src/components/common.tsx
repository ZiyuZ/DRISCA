import { ChevronDown } from "lucide-react";
import { useState, type ReactNode } from "react";
import { SharedSelect } from "./shared-select";
import { Button } from "./ui/button";
import { CommandDialog, CommandEmpty, CommandInput, CommandItem, CommandList } from "./ui/command";
import { DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, Dialog as DialogRoot, DialogTitle } from "./ui/dialog";
import { Input } from "./ui/input";
import { NumberInput } from "./number-input";
export function Modal({ title, open, onClose, children, footer }: {
  title: string; open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode;
}) {
  return (
    <DialogRoot open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="app-dialog flex flex-col gap-0 overflow-hidden p-0 sm:max-w-xl">
        <DialogHeader className="shrink-0 border-b px-6 py-5 text-left">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="sr-only">{title}</DialogDescription>
        </DialogHeader>
        <div className="dialog-body min-h-0 overflow-y-auto p-6">
          {children}
        </div>
        <DialogFooter className="shrink-0 border-t px-6 py-4">
          {footer === undefined ? (
            <DialogClose asChild>
              <Button variant="outline">关闭</Button>
            </DialogClose>
          ) : footer}
        </DialogFooter>
      </DialogContent>
    </DialogRoot>
  );
}
export function SearchSelect({ value, options, onChange, label, disabled }: {
  value: string; options: readonly (string | { value: string; label: string; })[];
  onChange: (value: string) => void; label: string; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        disabled={disabled}
        variant="outline"
        type="button"
        className="search-select"
        onClick={() => setOpen(true)}
      >
        {options.filter((o): o is { value: string; label: string; } => typeof o !== "string").find((o) => o.value === value)
          ?.label ||
          value ||
          "请选择"}{" "}
        <ChevronDown className="size-4 shrink-0 opacity-50" />
      </Button>
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title={label}
        description={"搜索" + label}
      >
        <CommandInput placeholder={"搜索" + label} />
        <CommandList>
          <CommandEmpty>没有匹配结果</CommandEmpty>
          {options.map((o) => {
            const v = typeof o === "string" ? o : o.value;
            const l = typeof o === "string" ? o : o.label;
            return (
              <CommandItem
                key={v}
                value={l}
                onSelect={() => {
                  onChange(v);
                  setOpen(false);
                }}
              >
                {l}
              </CommandItem>
            );
          })}
        </CommandList>
      </CommandDialog>
    </>
  );
}
export function Field<T extends string | number>({ label, value, onChange, type = "text", options, disabled, step }: {
  label: string; value: T; onChange: (value: T) => void; type?: string;
  options?: readonly (string | { value: string; label: string; })[]; disabled?: boolean; step?: number;
}) {
  return <label className="field"><span>{label}</span>{options ?
    <SharedSelect value={String(value)} disabled={disabled}
      options={options.map(option => typeof option === "string" ? [option, option] : [option.value, option.label])}
      onValueChange={value => onChange(value as T)} />
    : type === "number" ? <NumberInput disabled={disabled} step={step} value={Number(value)}
      onValueChange={value => onChange(value as T)} />
    : <Input type={type} disabled={disabled} value={value}
      onChange={event => onChange(event.target.value as T)} />}
  </label>;
}
