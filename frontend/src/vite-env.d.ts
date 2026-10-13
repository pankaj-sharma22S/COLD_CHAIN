/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_TILE_URL?: string;
  readonly VITE_REFRESH_INTERVAL_MS?: string;
  readonly VITE_TELEMETRY_INTERVAL_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
