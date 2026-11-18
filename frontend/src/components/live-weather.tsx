import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "../lib/api";
import type { Weather } from "../types/api";
import { Modal } from "./common";
import { WeatherEditor } from "./weather-editor";

export function LiveWeather({ weather, presets, onClose }: {
  weather: Weather;
  presets: Record<string, Weather>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(weather);
  const pending = useRef<Weather | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const apply = async () => {
    const value = pending.current;
    if (!value) return;
    pending.current = null;
    try { await api("/api/weather", "POST", value); }
    catch (error) { toast.error(String(error)); }
  };
  useEffect(() => () => clearTimeout(timer.current), []);
  const change = (value: Weather) => {
    setDraft(value);
    pending.current = value;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void apply(), 300);
  };
  const close = () => {
    clearTimeout(timer.current);
    void apply();
    onClose();
  };
  return <Modal title="实时天气" open onClose={close}>
    <WeatherEditor weather={draft} weatherPresets={presets} onChange={change} />
  </Modal>;
}
