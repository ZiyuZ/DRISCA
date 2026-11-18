import type { ReactNode } from "react";
import { Tabs, TabsList } from "./ui/tabs";

export function PageTabs({
  value,
  onValueChange,
  children,
  actions,
}: {
  value: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-tabs-row">
      <Tabs value={value} onValueChange={onValueChange}>
        <TabsList className="dr-tabs">{children}</TabsList>
      </Tabs>
      {actions}
    </div>
  );
}
