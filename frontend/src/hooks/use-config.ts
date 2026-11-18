import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "../lib/api";
import type { Bootstrap, ControlConfig, MachineConfig, PresetConfig, RuntimeState } from "../types/api";
import { useAutosave } from "./use-autosave";

function changeAtPath<T>(source: T, path: string[], value: unknown): T {
  const result = structuredClone(source);
  let target = result as Record<string, unknown>;
  for (const key of path.slice(0, -1)) target = target[key] as Record<string, unknown>;
  target[path[path.length - 1]] = value;
  return result;
}

export function useConfig(boot: Bootstrap | null, setBoot: Dispatch<SetStateAction<Bootstrap | null>>, state: RuntimeState | null, online: boolean) {
  const initialized = useRef(false);
  const [presetName, setPresetName] = useState("");
  const [preset, setPreset] = useState<PresetConfig | null>(null);
  const [machine, setMachine] = useState<MachineConfig | null>(null);
  const [control, setControl] = useState<ControlConfig | null>(null);
  useEffect(() => {
    if (!boot || initialized.current) return;
    initialized.current = true;
    setMachine(structuredClone(boot.machine));
    setControl(structuredClone(boot.control));
    const selected = boot.presets.find(p => p.name === boot.state.active_preset_name) ?? boot.presets[0];
    if (selected) { setPresetName(selected.name); setPreset(structuredClone(selected.config)); }
  }, [boot]);
  useEffect(() => {
    if (!state?.carla_connected || !preset?.ego.blueprint) return;
    if (!state.catalog.vehicles.includes(preset.ego.blueprint)) {
      setPreset(value => value ? { ...value, ego: { ...value.ego, blueprint: "" } } : value);
    }
  }, [state?.carla_connected, state?.catalog.vehicles, preset?.ego.blueprint]);
  const presetSave = useAutosave(presetName, preset, online,
    async value => (await api<{ name: string; config: PresetConfig; }>("/api/presets/" + encodeURIComponent(presetName), "PUT", value)).config,
    value => setBoot(b => b ? { ...b, presets: b.presets.map(p => p.name === presetName ? { ...p, config: value } : p) } : b));
  const machineSave = useAutosave("machine", machine, online && state?.phase === "idle" && !state.carla_connecting,
    value => api<MachineConfig>("/api/config/machine", "PUT", value),
    value => setBoot(b => b ? { ...b, machine: value } : b));
  const controlSave = useAutosave("control", control, online && state?.phase === "idle",
    value => api<ControlConfig>("/api/config/control", "PUT", value),
    value => setBoot(b => b ? { ...b, control: value } : b));
  const choosePreset = async (name: string) => {
    await presetSave.flush();
    const selected = boot?.presets.find(p => p.name === name);
    if (selected) { setPresetName(name); setPreset(structuredClone(selected.config)); }
  };
  const update = (path: string[], value: unknown) => setPreset(p => p ? changeAtPath(p, path, value) : p);
  const updateMachine = (path: string[], value: unknown) => setMachine(m => m ? changeAtPath(m, path, value) : m);
  const createPreset = async (name: string) => {
    await presetSave.flush();
    const saved = await api<{ name: string; config: PresetConfig; }>("/api/presets/" + encodeURIComponent(name), "PUT", {
      ego: { spawn_point: { x: 0, y: 0, z: 0, pitch: 0, yaw: 0, roll: 0 } },
    });
    setBoot(b => b ? { ...b, presets: [...b.presets, saved] } : b);
    setPresetName(saved.name); setPreset(structuredClone(saved.config));
  };
  const deletePreset = async () => {
    await presetSave.flush();
    await api("/api/presets/" + encodeURIComponent(presetName), "DELETE");
    const remaining = boot!.presets.filter(p => p.name !== presetName);
    setBoot(b => b ? { ...b, presets: remaining } : b);
    setPresetName(remaining[0]?.name ?? "");
    setPreset(remaining[0] ? structuredClone(remaining[0].config) : null);
  };
  return { presetName, preset, machine, setMachine, control, setControl, presetSave, machineSave, controlSave, choosePreset, createPreset, deletePreset, update, updateMachine };
}
