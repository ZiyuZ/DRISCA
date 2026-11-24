import type { ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

export function ActionTooltip({
  reason,
  children,
}: {
  reason?: string | null;
  children: ReactNode;
}) {
  if (!reason) return <>{children}</>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex" tabIndex={0}>
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent sideOffset={6}>{reason}</TooltipContent>
    </Tooltip>
  );
}
