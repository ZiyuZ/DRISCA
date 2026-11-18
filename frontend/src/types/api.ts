export type Camera = {
  x: number;
  y: number;
  z: number;
  pitch: number;
  yaw: number;
  roll: number;
  fov: number;
};
export type CameraViewport = {
  screen_position: [number, number];
  image_size: [number, number];
};
export type DisplayLayout = {
  show_rearview: boolean;
  rear_top: CameraViewport;
  rear_left: CameraViewport;
  rear_right: CameraViewport;
};
export type Instruction = {
  id: string;
  name: string;
  command: string;
  params: Record<string, string | number | boolean | null>;
};
export type SpawnPoint = {
  x: number;
  y: number;
  z: number;
  pitch: number;
  yaw: number;
  roll: number;
};
export type MachineConfig = {
  carla: { host: string; port: number; tm_port: number; timeout: number; };
  display: {
    resolution: [number, number];
    fullscreen: boolean;
    borderless: boolean;
    target_fps: number;
    layout: DisplayLayout;
  };
  service: {
    launcher_host: string;
    launcher_port: number;
    enable_tts: boolean;
    debug: boolean;
  };
  db_path: string;
  recorder_dir: string;
  export_dir: string;
};
export type ControlConfig = {
  keyboard: Record<string, string>;
  wheel: Record<string, string | number | boolean>;
};
export type PresetConfig = {
  world: {
    map_name: string;
    load_map: boolean;
    sync_mode: boolean;
    simulation_fps: number;
    weather: Record<string, string | number>;
  };
  ego: {
    role_name: string;
    blueprint: string;
    spawn_point: SpawnPoint;
    default_speed_limit: number;
    dynamic_speed_limit: boolean;
    init_autopilot: boolean;
  };
  cameras: {
    front: Camera;
    rear_top: Camera;
    rear_left: Camera;
    rear_right: Camera;
  };
  instructions: Instruction[];
  markers: string[];
};
export type Weather = PresetConfig["world"]["weather"];
export type Telemetry = {
  frame_no: number;
  server_fps: number;
  simulator_fps: number;
  speed_mps: number;
  speed_limit_mps: number;
  gear: number;
  steer: number;
  throttle: number;
  brake: number;
  control_mode: string;
  takeover_requested: boolean;
  location_x: number;
  location_y: number;
  location_z: number;
  rotation_pitch: number;
  rotation_yaw: number;
  rotation_roll: number;
};
export type RuntimeState = {
  phase: "idle" | "starting" | "running" | "stopping";
  active_preset: PresetConfig | null;
  active_preset_name: string | null;
  active_run: {
    subject_id: string;
    note: string;
    save_data: boolean;
    enable_carla_recorder: boolean;
  } | null;
  carla_connected: boolean;
  carla_connecting: boolean;
  world_loading: boolean;
  clients: { console: number; hud: number; };
  carla_detail: string;
  worker_state: string;
  session_id: string | null;
  telemetry: Telemetry | null;
  cameras: PresetConfig["cameras"] | null;
  weather: Weather | null;
  display_layout: DisplayLayout | null;
  vehicle_box: {
    location: { x: number; y: number; z: number; };
    extent: { x: number; y: number; z: number; };
    rotation: { pitch: number; yaw: number; roll: number; };
  } | null;
  error: string | null;
  catalog: {
    map_name: string | null;
    maps: string[];
    vehicles: string[];
    spawn_points: SpawnPoint[];
  };
  export: {
    running: boolean;
    progress: number;
    path: string | null;
    error: string | null;
  };
};
export type CommandField = {
  key: string;
  label: string;
  type: "text" | "number" | "boolean" | "select";
  required: boolean;
  default: string | number | boolean | null;
  options?: string[];
};
export type CommandDefinition = {
  id: string;
  label: string;
  description: string;
  fields: CommandField[];
};
export type Bootstrap = {
  machine: MachineConfig;
  control: ControlConfig;
  presets: { name: string; config: PresetConfig; }[];
  commands: CommandDefinition[];
  keyboard_labels: Record<string, string>;
  wheel_labels: Record<string, string>;
  weather_presets: Record<string, Weather>;
  state: RuntimeState;
  logs: Record<string, unknown>[];
  events: Record<string, unknown>[];
  urls: { console: string; hud: string; };
};
