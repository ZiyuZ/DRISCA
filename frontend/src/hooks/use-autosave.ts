import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

export function useAutosave<T>(key: string, value: T | null, enabled: boolean,
  write: (value: T) => Promise<T>, onSaved: (value: T) => void) {
  const current = useRef({ key, value, enabled, write, onSaved });
  current.current = { key, value, enabled, write, onSaved };
  const baseline = useRef<{ key: string; json: string; } | null>(null);
  const pending = useRef<Promise<void> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [status, setStatus] = useState("已保存");

  const flush = useCallback(async (override?: T) => {
    clearTimeout(timer.current);
    if (override !== undefined) current.current.value = override;
    while (pending.current) await pending.current;
    const work = async () => {
      while (current.current.value !== null && current.current.enabled) {
        const snapshot = current.current;
        const value = snapshot.value as T;
        const json = JSON.stringify(value);
        if (baseline.current?.key === snapshot.key && baseline.current.json === json) break;
        setStatus("正在保存…");
        const result = await snapshot.write(value);
        if (current.current.key !== snapshot.key) return;
        baseline.current = { key: snapshot.key, json };
        snapshot.onSaved(result);
      }
      setStatus("已保存");
    };
    const task = work();
    pending.current = task;
    try { await task; }
    catch (error) { setStatus("保存失败"); throw error; }
    finally { if (pending.current === task) pending.current = null; }
  }, []);

  useEffect(() => {
    if (value === null) return;
    const json = JSON.stringify(value);
    if (!baseline.current || baseline.current.key !== key) {
      baseline.current = { key, json };
      setStatus("已保存");
      return;
    }
    if (baseline.current.json === json) return;
    setStatus("待保存");
    if (!enabled) return;
    timer.current = setTimeout(() => { void flush().catch(error => toast.error(String(error))); }, 600);
    return () => clearTimeout(timer.current);
  }, [key, value, enabled, flush]);
  return { flush, status };
}
