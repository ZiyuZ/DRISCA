import { zhCN } from "../i18n";
import type { ReactNode } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";

export function PageTabs({
  value,
  onValueChange,
  children,
  actions,
  items,
}: {
  value: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
  actions?: ReactNode;
  items: readonly (readonly [string, string])[];
}) {
  return (
    <Tabs value={value} onValueChange={onValueChange} className="tabbed-page tabs">
      <div className="page-tabs-row">
        <TabsList className="dr-tabs" aria-label={zhCN.common.pageTabs}>
          {items.map(([value, label]) => <TabsTrigger key={value} value={value}>{label}</TabsTrigger>)}
        </TabsList>
        {actions}
      </div>
      {items.map(([panel]) => <TabsContent key={panel} value={panel} className="page-tab-panel">
        {panel === value ? children : null}
      </TabsContent>)}
    </Tabs>
  );
}
