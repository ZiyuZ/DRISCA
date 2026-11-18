import type { ReactElement } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

export function Hint({
  children,
  text,
  enabled = true,
  side = "top",
}: {
  children: ReactElement;
  text: string;
  enabled?: boolean;
  side?: "top" | "right" | "bottom" | "left";
}) {
  if (!enabled) return children;
  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} sideOffset={6}>
        {text}
      </TooltipContent>
    </Tooltip>
  );
}
