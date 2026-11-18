import type { ComponentProps } from "react";
import { Button } from "./ui/button";
import { Hint } from "./hint";

type Props = Omit<ComponentProps<typeof Button>, "variant" | "size"> & {
  label: string;
};

export function IconAction({ label, children, ...props }: Props) {
  return (
    <Hint text={label}>
      <span
        className="inline-flex shrink-0"
        tabIndex={props.disabled ? 0 : undefined}
      >
        <Button {...props} variant="ghost" size="icon-sm" aria-label={label}>
          {children}
        </Button>
      </span>
    </Hint>
  );
}
