import { useId, type ReactNode } from "react";
import { Card } from "./ui/card";

export function FloatingActionCard({ title, description, icon, badge, headerAction, children }: {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  badge?: ReactNode;
  headerAction?: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  return (
    <Card role="region" aria-labelledby={titleId}
      className="floating-action-card pointer-events-auto w-[320px] max-w-full shrink-0 gap-0 overflow-hidden p-0 shadow-lg">
      <header className="grid gap-2 border-b bg-muted/30 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          {icon}
          <h2 id={titleId} className="min-w-0 flex-1 text-sm font-semibold">{title}</h2>
          {badge && <span className="ml-auto rounded border bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground">{badge}</span>}
          {headerAction}
        </div>
        {description && <div className="break-all font-mono text-xs text-muted-foreground">{description}</div>}
      </header>
      <div className="grid gap-3 p-4">{children}</div>
    </Card>
  );
}
