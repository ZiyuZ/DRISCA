import { useCallback, useState } from "react";

const rememberedTabs = new Map<string, string>();

export function useRememberedTab(pageKey: string, defaultTab: string) {
  const [tab, setTab] = useState(() => rememberedTabs.get(pageKey) ?? defaultTab);
  const remember = useCallback((value: string) => {
    rememberedTabs.set(pageKey, value);
    setTab(value);
  }, [pageKey]);
  return [tab, remember] as const;
}
