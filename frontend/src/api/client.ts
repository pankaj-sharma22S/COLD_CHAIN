import type { AlertEvent, FleetResponse, Route, Simulation, Telemetry, Trip, TripReport, Weather, Truck } from "../types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
export const REFRESH_INTERVAL = Number(import.meta.env.VITE_REFRESH_INTERVAL_MS || 5000);

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) { const body = await response.text(); throw new Error(body || `${response.status} ${response.statusText}`); }
  return response.json() as Promise<T>;
}

export const api = {
  fleet: () => request<FleetResponse>("/trucks/active"),
  truck: (id: string) => request<Truck>(`/trucks/${encodeURIComponent(id)}`),
  simulation: () => request<Simulation>("/simulation"),
  alerts: (currentRunOnly?: boolean, tripId?: string) => {
    const params = new URLSearchParams();
    if (currentRunOnly) params.set("current_run_only", "true");
    if (tripId) params.set("trip_id", tripId);
    const q = params.toString();
    return request<AlertEvent[]>(`/alerts${q ? `?${q}` : ""}`);
  },
  acknowledgeAlert: (id: number) => request<AlertEvent>(`/alerts/${id}/acknowledge`, { method: "POST" }),
  startSimulation: () => request<Simulation>("/simulation/start", { method: "POST" }),
  stopSimulation: () => request<Simulation>("/simulation/stop", { method: "POST" }),
  trips: (status?: string) => request<Trip[]>(`/trips${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  trip: (id: string) => request<Trip>(`/trips/${encodeURIComponent(id)}`),
  telemetry: (id: string) => request<Telemetry[]>(`/trips/${encodeURIComponent(id)}/telemetry`),
  truckTelemetry: (id: string, hours?: number) => request<Telemetry[]>(`/trucks/${encodeURIComponent(id)}/telemetry${hours ? `?hours=${hours}` : ""}`),
  route: (id: string) => request<Route>(`/routes/${encodeURIComponent(id)}`),
  weather: (id: string) => request<Weather>(`/trucks/${encodeURIComponent(id)}/weather`),
  report: (id: string) => request<TripReport>(`/trips/${encodeURIComponent(id)}/report`),
  policies: () => request<import("../types").CargoPolicy[]>("/policies"),
  agent: (requestText: string, truckId?: string, tripId?: string, threadId?: string) =>
    request<import("../types").AgentChatResponse>("/agent/query", {
      method: "POST",
      body: JSON.stringify({ request: requestText, truck_id: truckId, trip_id: tripId, thread_id: threadId }),
    }),
};
