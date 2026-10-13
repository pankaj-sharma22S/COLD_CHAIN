import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bell,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleStop,
  Compass,
  FileText,
  Filter,
  History,
  Info,
  LayoutDashboard,
  MapPin,
  MapPinned,
  Moon,
  Navigation,
  Play,
  Radio,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sliders,
  Snowflake,
  Sun,
  Thermometer,
  Truck as TruckIcon,
  X,
} from "lucide-react";
import { api, REFRESH_INTERVAL } from "./api/client";
import { MapView } from "./components/MapView";
import { TemperatureChart } from "./components/TemperatureChart";
import type {
  AlertEvent,
  CargoPolicy,
  ChatMessage,
  FleetResponse,
  Route,
  Simulation,
  Telemetry,
  Trip,
  TripReport,
  Truck,
  Weather,
} from "./types";

type PageTab = "overview" | "fleet" | "trips" | "trip-detail" | "incidents" | "assistant" | "policies";

const value = (item: unknown, suffix = "") =>
  item === null || item === undefined || item === "" ? "—" : `${item}${suffix}`;

const ago = (timestamp?: string | null) => {
  if (!timestamp) return "—";
  const diffSec = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  return `${Math.round(diffSec / 3600)}h ago`;
};

const formatDuration = (seconds?: number | null) => {
  if (seconds === undefined || seconds === null || seconds < 0) return "0s";
  const sec = Math.floor(seconds);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m < 60) return `${m}m ${s.toString().padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return `${h}h ${remM.toString().padStart(2, "0")}m`;
};

export default function App() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    return (localStorage.getItem("dispatch_theme") as "dark" | "light") || "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("dispatch_theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme((prev) => (prev === "dark" ? "light" : "dark"));

  // State Management
  const [page, setPage] = useState<PageTab>("overview");
  const [fleet, setFleet] = useState<FleetResponse | null>(null);
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [policies, setPolicies] = useState<CargoPolicy[]>([]);
  const [routes, setRoutes] = useState<Record<string, Route>>({});
  const [selectedId, setSelectedId] = useState<string>();
  const [inspectedTripId, setInspectedTripId] = useState<string>();
  const [telemetry, setTelemetry] = useState<Telemetry[]>([]);
  const [telemetryRange, setTelemetryRange] = useState<string>("recent");
  const [weather, setWeather] = useState<Weather>();
  const [report, setReport] = useState<TripReport>();
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Conversational Assistant State
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const threadId = useMemo(() => `session_${Date.now()}`, []);

  const selected = fleet?.active_trucks.find((item) => item.truck_id === selectedId);

  // Central Data Fetcher
  const refresh = useCallback(async () => {
    try {
      const [fleetData, simulationData, tripData, alertData, policyData] = await Promise.all([
        api.fleet(),
        api.simulation(),
        api.trips(),
        api.alerts(),
        api.policies().catch(() => []),
      ]);

      setFleet(fleetData);
      setSimulation(simulationData);
      setTrips(tripData);
      setAlerts(alertData);
      setPolicies(policyData);
      setError(undefined);

      setSelectedId((current) =>
        current && fleetData.active_trucks.some((truck) => truck.truck_id === current)
          ? current
          : fleetData.active_trucks[0]?.truck_id
      );

      const routeIds = [
        ...new Set(fleetData.active_trucks.map((t) => t.route_id).filter((id): id is string => Boolean(id))),
      ];
      const routeResults = await Promise.all(routeIds.map(async (id) => [id, await api.route(id)] as const));
      setRoutes(Object.fromEntries(routeResults));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load telemetry and fleet data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_INTERVAL);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // Telemetry Fetcher for Selected Vehicle
  useEffect(() => {
    if (!selected?.truck_id) {
      setTelemetry([]);
      return;
    }
    if (telemetryRange === "recent") {
      if (!selected.trip_id) {
        setTelemetry([]);
        return;
      }
      void api.telemetry(selected.trip_id).then(setTelemetry).catch(() => setTelemetry([]));
    } else {
      const hoursMap: Record<string, number> = { "1h": 1, "6h": 6, "24h": 24, all: 0 };
      const hrs = hoursMap[telemetryRange] ?? 1;
      void api.truckTelemetry(selected.truck_id, hrs).then(setTelemetry).catch(() => setTelemetry([]));
    }
  }, [selected?.truck_id, selected?.trip_id, telemetryRange, fleet?.timestamp]);

  // Weather Fetcher
  useEffect(() => {
    if (!selected?.truck_id) {
      setWeather(undefined);
      return;
    }
    void api.weather(selected.truck_id).then(setWeather).catch(() => setWeather({ status: "UNAVAILABLE" }));
  }, [selected?.truck_id, fleet?.timestamp]);

  // Simulation Controls
  const controlSimulation = async (action: "start" | "stop") => {
    setBusy(true);
    try {
      const next = action === "start" ? await api.startSimulation() : await api.stopSimulation();
      setSimulation(next);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Simulation control failed.");
    } finally {
      setBusy(false);
    }
  };

  // Completed Trip Report Fetcher
  const openReport = async (tripId: string) => {
    setBusy(true);
    try {
      setReport(await api.report(tripId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Report generation failed.");
    } finally {
      setBusy(false);
    }
  };

  // Inspect Trip in Dedicated View
  const viewTripDetail = (tripId: string) => {
    setInspectedTripId(tripId);
    setPage("trip-detail");
  };

  // Ask Operations Assistant
  const askAgent = async (promptText: string) => {
    if (!promptText.trim()) return;
    const userMsg: ChatMessage = {
      id: `u_${Date.now()}`,
      sender: "user",
      text: promptText,
      timestamp: new Date().toISOString(),
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setBusy(true);

    try {
      const res = await api.agent(promptText, selected?.truck_id, inspectedTripId || selected?.trip_id, threadId);
      const assistantMsg: ChatMessage = {
        id: `a_${Date.now()}`,
        sender: "assistant",
        text: res.response,
        timestamp: new Date().toISOString(),
        evidence: res.evidence,
      };
      setChatMessages((prev) => [...prev, assistantMsg]);
    } catch (e) {
      const errorMsg: ChatMessage = {
        id: `err_${Date.now()}`,
        sender: "assistant",
        text: `⚠️ Request failed: ${e instanceof Error ? e.message : "Unable to reach Operations Assistant."}`,
        timestamp: new Date().toISOString(),
      };
      setChatMessages((prev) => [...prev, errorMsg]);
    } finally {
      setBusy(false);
    }
  };

  // Incident Acknowledgment
  const dismissAlert = async (id: number) => {
    try {
      await api.acknowledgeAlert(id);
      void refresh();
    } catch (e) {
      console.error("Failed to dismiss alert:", e);
    }
  };

  const riskyTrucks = useMemo(
    () => (fleet?.active_trucks || []).filter((truck) => truck.risk.status === "RISKY"),
    [fleet]
  );

  return (
    <div className="app-shell">
      {/* ---------------- Topbar ---------------- */}
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand">
            <div className="brand-icon">
              <Snowflake size={20} />
            </div>
            <div>
              <strong>Cold Chain Logistics</strong>
              <span>Control Center</span>
            </div>
          </div>

          <div className="topbar-search">
            <Search size={14} />
            <input
              placeholder="Search trips, vehicles, or locations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        <div className="topbar-right">
          <div className="topbar-status">
            <span className={`status-dot ${simulation?.status === "RUNNING" ? "live" : "idle"}`} />
            <span>Sim: {simulation?.status || "STOPPED"}</span>
            <span className="separator" />
            <span>{fleet?.timestamp ? `Updated ${ago(fleet.timestamp)}` : "Waiting for telemetry"}</span>
          </div>

          <button
            type="button"
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label="Toggle theme"
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
            <span>{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>
          </button>

          <div className="user-profile">
            <div className="user-avatar">JD</div>
            <div className="user-info">
              <strong>John Doe</strong>
              <span>Operations Lead</span>
            </div>
          </div>
        </div>
      </header>

      {/* ---------------- Sidebar Navigation ---------------- */}
      <aside className="sidebar">
        <nav className="sidebar-nav">
          <button
            className={`nav ${page === "overview" ? "active" : ""}`}
            onClick={() => setPage("overview")}
          >
            <LayoutDashboard size={18} />
            <span>Overview</span>
          </button>

          <button
            className={`nav ${page === "fleet" ? "active" : ""}`}
            onClick={() => setPage("fleet")}
          >
            <Compass size={18} />
            <span>Live Fleet</span>
          </button>

          <button
            className={`nav ${page === "trips" || page === "trip-detail" ? "active" : ""}`}
            onClick={() => setPage("trips")}
          >
            <TruckIcon size={18} />
            <span>Trips</span>
          </button>

          <button
            className={`nav ${page === "incidents" ? "active" : ""}`}
            onClick={() => setPage("incidents")}
          >
            <ShieldAlert size={18} />
            <span>Incidents & Alerts</span>
          </button>

          <button
            className={`nav ${page === "assistant" ? "active" : ""}`}
            onClick={() => setPage("assistant")}
          >
            <Bot size={18} />
            <span>AI Assistant</span>
          </button>

          <button
            className={`nav ${page === "policies" ? "active" : ""}`}
            onClick={() => setPage("policies")}
          >
            <FileText size={18} />
            <span>Policies & SOPs</span>
          </button>
        </nav>

        {/* Fleet Simulation Controls */}
        <div className="sidebar-bottom">
          <div className="sim-card">
            <div className="eyebrow">SIMULATION CONTROLLER</div>
            <div className="sim-state">
              <span className={`status-dot ${simulation?.status === "RUNNING" ? "live" : "idle"}`} />
              {simulation?.status === "RUNNING" ? "Fleet Active" : "Stopped"}
            </div>
            <p className="muted" style={{ margin: "4px 0 12px 0", fontSize: "11px" }}>
              Runs 3 synchronized trucks traversing road geometry.
            </p>

            <button
              className={`control ${simulation?.status === "RUNNING" ? "danger" : "primary"}`}
              style={{ width: "100%" }}
              disabled={busy || !simulation}
              onClick={() => void controlSimulation(simulation?.status === "RUNNING" ? "stop" : "start")}
            >
              {simulation?.status === "RUNNING" ? (
                <>
                  <CircleStop size={15} /> Stop Fleet
                </>
              ) : (
                <>
                  <Play size={15} /> Start Simulation
                </>
              )}
            </button>
          </div>
        </div>
      </aside>

      {/* ---------------- Main Content Body ---------------- */}
      <main className="main-content">
        {error && (
          <div className="banner error">
            <AlertTriangle size={16} />
            <span>{error}</span>
            <button
              onClick={() => void refresh()}
              style={{ background: "transparent", border: 0, color: "inherit", cursor: "pointer", marginLeft: "auto" }}
            >
              <RefreshCw size={14} /> Retry
            </button>
          </div>
        )}

        {/* PAGE 1: OPERATIONS OVERVIEW */}
        {page === "overview" && (
          <OverviewPage
            fleet={fleet}
            simulation={simulation}
            routes={routes}
            selected={selected}
            selectedId={selectedId}
            onSelect={setSelectedId}
            alerts={alerts}
            trips={trips}
            weather={weather}
            onViewTrip={viewTripDetail}
            onNavigate={(p) => setPage(p)}
            onControlSimulation={controlSimulation}
            onDismissAlert={dismissAlert}
          />
        )}

        {/* PAGE 2: LIVE FLEET */}
        {page === "fleet" && (
          <LiveFleetPage
            fleet={fleet}
            routes={routes}
            selected={selected}
            selectedId={selectedId}
            onSelect={setSelectedId}
            telemetry={telemetry}
            telemetryRange={telemetryRange}
            onRangeChange={setTelemetryRange}
            weather={weather}
            onAskAssistant={(truckId, tripId) => {
              setSelectedId(truckId);
              setInspectedTripId(tripId);
              setPage("assistant");
            }}
          />
        )}

        {/* PAGE 3: TRIPS LISTING */}
        {page === "trips" && (
          <TripsPage
            trips={trips}
            searchQuery={searchQuery}
            onViewTrip={viewTripDetail}
            onGenerateReport={openReport}
            onAskAI={(tripId) => {
              setInspectedTripId(tripId);
              setPage("assistant");
            }}
          />
        )}

        {/* PAGE 4: TRIP DETAILS & REPORT */}
        {page === "trip-detail" && (
          <TripDetailPage
            tripId={inspectedTripId || trips[0]?.trip_id}
            trips={trips}
            routes={routes}
            onBack={() => setPage("trips")}
            onGenerateReport={openReport}
            onAskAI={(tripId) => {
              setInspectedTripId(tripId);
              setPage("assistant");
            }}
          />
        )}

        {/* PAGE 5: INCIDENTS & ALERTS */}
        {page === "incidents" && (
          <IncidentsPage
            alerts={alerts}
            simulation={simulation}
            fleet={fleet}
            onDismiss={dismissAlert}
            onSelectTruck={(tId) => {
              setSelectedId(tId);
              setPage("fleet");
            }}
          />
        )}

        {/* PAGE 6: AI OPERATIONS ASSISTANT */}
        {page === "assistant" && (
          <AssistantPage
            chatMessages={chatMessages}
            busy={busy}
            selectedTruck={selected}
            inspectedTripId={inspectedTripId}
            trips={trips}
            onAsk={askAgent}
            onSelectTrip={(tId) => setInspectedTripId(tId)}
          />
        )}

        {/* PAGE 7: POLICIES & SOPS */}
        {page === "policies" && <PoliciesPage policies={policies} />}
      </main>

      {/* Modal Report Viewer */}
      {report && <ReportModal report={report} onClose={() => setReport(undefined)} />}
    </div>
  );
}

/* =======================================================================
   SUB-PAGE COMPONENTS
======================================================================= */

// 1. OPERATIONS OVERVIEW
function OverviewPage({
  fleet,
  simulation,
  routes,
  selected,
  selectedId,
  onSelect,
  alerts,
  trips,
  weather,
  onViewTrip,
  onNavigate,
  onControlSimulation,
  onDismissAlert,
}: {
  fleet: FleetResponse | null;
  simulation?: Simulation | null;
  routes: Record<string, Route>;
  selected?: Truck;
  selectedId?: string;
  onSelect: (id: string) => void;
  alerts: AlertEvent[];
  trips: Trip[];
  weather?: Weather;
  onViewTrip: (tripId: string) => void;
  onNavigate: (page: PageTab) => void;
  onControlSimulation?: (action: "start" | "stop") => Promise<void>;
  onDismissAlert?: (id: number) => Promise<void>;
}) {
  // Live ticking clock state for second-by-second dynamic timers
  const [nowTime, setNowTime] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowTime(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const isSimRunning = simulation?.status === "RUNNING";
  const activeTrucks = isSimRunning ? fleet?.active_trucks || [] : [];
  const activeTripsCount = isSimRunning ? trips.filter((t) => t.status === "ACTIVE").length : 0;

  // Filter alerts for UPDATED DATA of CURRENT SIMULATOR RUN only (not previous)
  const activeTripIds = useMemo(
    () => new Set(activeTrucks.map((t) => t.trip_id).filter((id): id is string => Boolean(id))),
    [activeTrucks]
  );
  const simStartedTime = simulation?.started_at ? new Date(simulation.started_at).getTime() : 0;

  const currentRunAlerts = useMemo(() => {
    if (!isSimRunning) return [];
    return alerts.filter((a) => {
      const isTripMatch = Boolean(a.trip_id && activeTripIds.has(a.trip_id));
      const isTimeMatch = simStartedTime > 0 ? new Date(a.created_at).getTime() >= simStartedTime - 5000 : true;
      return isTripMatch && isTimeMatch;
    });
  }, [alerts, isSimRunning, activeTripIds, simStartedTime]);

  const activeAlertsList = currentRunAlerts.filter((a) => a.status === "ACTIVE" && !a.acknowledged);
  const resolvedAlertsList = currentRunAlerts.filter((a) => a.status === "RESOLVED");

  // Check if all simulation units have finished their trip
  const allTripsCompleted =
    isSimRunning &&
    activeTrucks.length > 0 &&
    activeTrucks.every((t) => t.trip_status === "COMPLETED");

  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>Operations Overview</h1>
          <p>Real-time fleet activity, exception monitoring, and cold-chain compliance</p>
        </div>
      </div>

      {/* ---------------- Dynamic Alert Banner (Updates across 4 states) ---------------- */}
      {!isSimRunning ? (
        /* STATE 1: NOT ACTIVE (Simulator is stopped) */
        <div
          className="banner"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "rgba(100, 116, 139, 0.12)",
            border: "1px solid rgba(100, 116, 139, 0.25)",
            padding: "12px 18px",
            borderRadius: "var(--radius-md)",
            marginBottom: "20px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <Radio size={22} color="var(--text-muted)" />
            <div>
              <div style={{ fontWeight: 700, fontSize: "14px", color: "var(--text-heading)" }}>
                ⏸ Fleet Telemetry Simulator Inactive / Stopped
              </div>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "2px" }}>
                Simulation is currently paused. No active alerts or live excursions are running.
              </div>
            </div>
          </div>
          {onControlSimulation && (
            <button
              className="control primary"
              style={{ padding: "6px 14px", fontSize: "12px", display: "flex", alignItems: "center", gap: "6px" }}
              onClick={() => void onControlSimulation("start")}
            >
              <Play size={14} /> Start Simulation
            </button>
          )}
        </div>
      ) : activeAlertsList.length > 0 ? (
        /* STATE 2: ACTIVE ALERT (Live Excursion with dynamic timer) */
        (() => {
          const primaryAlert = activeAlertsList[0];
          const alertStartTime = new Date(primaryAlert.created_at).getTime();
          const liveElapsed = Math.max(0, Math.floor((nowTime - alertStartTime) / 1000));
          const durationStr = formatDuration(liveElapsed || primaryAlert.duration_seconds);

          return (
            <div
              className="banner error"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: "rgba(239, 68, 68, 0.14)",
                border: "1px solid rgba(239, 68, 68, 0.35)",
                padding: "12px 18px",
                borderRadius: "var(--radius-md)",
                marginBottom: "20px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <AlertTriangle size={22} color="#ef4444" className="pulse-icon" />
                <div>
                  <div style={{ fontWeight: 700, fontSize: "14px", color: "#ef4444" }}>
                    ⚠️ Active Risk Detected: {primaryAlert.type} ({primaryAlert.truck_id})
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--text-main)", marginTop: "2px" }}>
                    {primaryAlert.message}
                  </div>
                  {primaryAlert.threshold_violated && (
                    <div style={{ fontSize: "11px", color: "var(--text-dim)", marginTop: "3px" }}>
                      Reading: <strong>{primaryAlert.current_value !== null ? `${primaryAlert.current_value}°C` : "N/A"}</strong> | Allowed: <strong>{primaryAlert.threshold_violated}</strong>
                    </div>
                  )}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <div style={{ textAlign: "right" }}>
                  <span className="badge danger" style={{ fontSize: "11px", fontWeight: 700 }}>
                    ACTIVE EXCURSION
                  </span>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-heading)", marginTop: "4px" }}>
                    ⏱ In alert state for: <strong>{durationStr}</strong>
                  </div>
                </div>
                {onDismissAlert && (
                  <button
                    className="control secondary"
                    style={{ padding: "6px 12px", fontSize: "12px" }}
                    onClick={() => void onDismissAlert(primaryAlert.id)}
                  >
                    Acknowledge
                  </button>
                )}
                <button
                  className="control secondary"
                  style={{ padding: "6px 12px", fontSize: "12px" }}
                  onClick={() => onNavigate("incidents")}
                >
                  View All ({activeAlertsList.length})
                </button>
              </div>
            </div>
          );
        })()
      ) : allTripsCompleted ? (
        /* STATE 3: COMPLETED (Trips have finished) */
        <div
          className="banner"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "rgba(59, 130, 246, 0.12)",
            border: "1px solid rgba(59, 130, 246, 0.3)",
            padding: "12px 18px",
            borderRadius: "var(--radius-md)",
            marginBottom: "20px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <CheckCircle2 size={20} color="#3b82f6" />
            <div>
              <div style={{ fontSize: "13px", color: "#3b82f6", fontWeight: 700 }}>
                🏁 Simulation Trips Completed — All units reached destinations safely
              </div>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "2px" }}>
                Cold chain compliance verified. All prior excursions resolved and archived.
              </div>
            </div>
          </div>
          <span className="badge blue" style={{ fontSize: "11px", fontWeight: 700 }}>
            COMPLETED
          </span>
        </div>
      ) : (
        /* STATE 4: SAFE STATE (All readings nominal) */
        <div
          className="banner"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "rgba(16, 185, 129, 0.12)",
            border: "1px solid rgba(16, 185, 129, 0.3)",
            padding: "12px 18px",
            borderRadius: "var(--radius-md)",
            marginBottom: "20px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <CheckCircle2 size={20} color="#10b981" />
            <div>
              <div style={{ fontSize: "13px", color: "#10b981", fontWeight: 700 }}>
                ✓ Fleet Operating in Safe State — All sensors within permitted thresholds
              </div>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "2px" }}>
                {resolvedAlertsList.length > 0
                  ? `Prior excursion on ${resolvedAlertsList[0].truck_id} resolved after ${formatDuration(resolvedAlertsList[0].duration_seconds)} (returned to safe range).`
                  : `All ${activeTrucks.length} reporting vehicles maintaining compliant temperatures and closed doors.`}
              </div>
            </div>
          </div>
          <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
            Telemetry pings nominal
          </span>
        </div>
      )}

      {/* Top 4 KPI Cards (Derived strictly from current run data) */}
      <div className="kpi-grid">
        <div className="kpi" onClick={() => onNavigate("trips")}>
          <div className="kpi-content">
            <span>Active Trips</span>
            <strong>{activeTripsCount || activeTrucks.length}</strong>
            <div className="kpi-subtext positive">
              <CheckCircle2 size={12} /> {activeTrucks.length} in transit
            </div>
          </div>
          <div className="kpi-icon">
            <Navigation size={22} />
          </div>
        </div>

        <div className="kpi" onClick={() => onNavigate("fleet")}>
          <div className="kpi-content">
            <span>Reporting Vehicles</span>
            <strong>{activeTrucks.length}</strong>
            <div className="kpi-subtext positive">
              <CheckCircle2 size={12} /> {isSimRunning ? "100% telemetry online" : "Idle"}
            </div>
          </div>
          <div className="kpi-icon">
            <TruckIcon size={22} />
          </div>
        </div>

        <div
          className={`kpi ${activeAlertsList.length > 0 ? "danger" : "success"}`}
          onClick={() => onNavigate("incidents")}
        >
          <div className="kpi-content">
            <span>Open Incidents</span>
            <strong>{activeAlertsList.length}</strong>
            <div className={activeAlertsList.length > 0 ? "kpi-subtext negative" : "kpi-subtext positive"}>
              <AlertTriangle size={12} /> {activeAlertsList.length > 0 ? "Requires attention" : "Zero active alerts"}
            </div>
          </div>
          <div className="kpi-icon">
            <ShieldAlert size={22} />
          </div>
        </div>

        <div className="kpi warning" onClick={() => onNavigate("policies")}>
          <div className="kpi-content">
            <span>Temperature Exceptions</span>
            <strong>{isSimRunning ? (fleet?.risky_truck_count ?? 0) : 0}</strong>
            <div className="kpi-subtext">
              <Thermometer size={12} /> Active policy boundaries
            </div>
          </div>
          <div className="kpi-icon">
            <Thermometer size={22} />
          </div>
        </div>
      </div>

      {/* Overview Grid: Fleet Map + Recent Events */}
      <div className="overview-grid">
        <div className="panel map-panel">
          <div className="panel-heading">
            <h2>
              <MapPin size={16} /> Fleet Map
            </h2>
            <span className="badge blue">{activeTrucks.length} Units Active</span>
          </div>
          <MapView
            trucks={activeTrucks}
            routes={routes}
            selected={selectedId}
            selectedTruck={selected}
            weather={weather}
            onSelect={onSelect}
          />
        </div>

        {/* Activity & Recent Events Feed */}
        <div className="panel">
          <div className="panel-heading">
            <h2>
              <History size={16} /> Recent Events
            </h2>
            <span className="badge neutral">
              {isSimRunning ? `${currentRunAlerts.length} Current Run` : "Simulation Paused"}
            </span>
          </div>

          <div className="activity-feed">
            {!isSimRunning ? (
              <div className="empty-state">
                ⏸ Simulation stopped. Start simulation to record and view real-time events.
              </div>
            ) : currentRunAlerts.length === 0 ? (
              <div className="empty-state" style={{ color: "#10b981" }}>
                ✓ No operational anomalies detected in current simulation run. Telemetry safe.
              </div>
            ) : (
              currentRunAlerts.slice(0, 6).map((a) => {
                const isItemActive = a.status === "ACTIVE" && !a.acknowledged;
                const itemElapsed = isItemActive
                  ? Math.max(0, Math.floor((nowTime - new Date(a.created_at).getTime()) / 1000))
                  : a.duration_seconds;

                return (
                  <div key={a.id} className="activity-item">
                    <div className="activity-icon">
                      {a.status === "RESOLVED" ? (
                        <CheckCircle2 size={18} color="#10b981" />
                      ) : a.severity === "CRITICAL" ? (
                        <AlertTriangle size={18} color="#ef4444" />
                      ) : (
                        <Info size={18} color="#f59e0b" />
                      )}
                    </div>
                    <div className="activity-content">
                      <div className="activity-title">
                        <span>{a.truck_id || a.type}</span>
                        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                          <span
                            className={`badge ${
                              a.status === "ACTIVE"
                                ? "danger"
                                : a.status === "RESOLVED"
                                ? "success"
                                : "neutral"
                            }`}
                            style={{ fontSize: "10px", padding: "1px 6px" }}
                          >
                            {a.status}
                          </span>
                          <span className="activity-time">{ago(a.created_at)}</span>
                        </div>
                      </div>
                      <div className="activity-desc">{a.message}</div>
                      <div style={{ fontSize: "11px", color: "var(--text-dim)", marginTop: "4px" }}>
                        ⏱ {isItemActive ? "Active for: " : "Incident duration: "}
                        <strong>{formatDuration(itemElapsed)}</strong>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Recent Trips Table */}
      <div className="panel table-panel">
        <div className="panel-heading">
          <h2>
            <TruckIcon size={16} /> Recent Trips
          </h2>
          <button className="link-button" onClick={() => onNavigate("trips")}>
            View All Trips <ChevronRight size={14} />
          </button>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Trip ID</th>
                <th>Vehicle</th>
                <th>Origin ➔ Destination</th>
                <th>Status</th>
                <th>Cargo Policy</th>
                <th>ETA</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {trips.slice(0, 5).map((t) => (
                <tr key={t.trip_id} onClick={() => onViewTrip(t.trip_id)}>
                  <td>
                    <strong>{t.trip_id}</strong>
                  </td>
                  <td>{t.truck_id}</td>
                  <td>{t.route_id}</td>
                  <td>
                    <span className={`badge ${t.status === "ACTIVE" ? "success" : "neutral"}`}>
                      {t.status === "ACTIVE" ? "In Progress" : t.status}
                    </span>
                  </td>
                  <td>{t.cargo_type || t.cargo_policy_id || "Pharmaceuticals"}</td>
                  <td>{t.completed_at ? "Completed" : "Calculating"}</td>
                  <td>
                    <button
                      className="link-button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onViewTrip(t.trip_id);
                      }}
                    >
                      Inspect <ChevronRight size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// 2. LIVE FLEET PAGE
function LiveFleetPage({
  fleet,
  routes,
  selected,
  selectedId,
  onSelect,
  telemetry,
  telemetryRange,
  onRangeChange,
  weather,
  onAskAssistant,
}: {
  fleet: FleetResponse | null;
  routes: Record<string, Route>;
  selected?: Truck;
  selectedId?: string;
  onSelect: (id: string) => void;
  telemetry: Telemetry[];
  telemetryRange: string;
  onRangeChange: (range: string) => void;
  weather?: Weather;
  onAskAssistant: (truckId: string, tripId?: string) => void;
}) {
  const activeTrucks = fleet?.active_trucks || [];

  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>Live Fleet</h1>
          <p>Real-time location, thermal status, and road telemetry of all active vehicles</p>
        </div>
      </div>

      <div className="fleet-grid">
        {/* Main Road Map */}
        <div className="panel map-panel">
          <div className="panel-heading">
            <h2>
              <MapPinned size={16} /> Live Road Traversal
            </h2>
            <span className="badge blue">{activeTrucks.length} Vehicles Reporting</span>
          </div>
          <MapView
            trucks={activeTrucks}
            routes={routes}
            selected={selectedId}
            selectedTruck={selected}
            weather={weather}
            onSelect={onSelect}
          />
        </div>

        {/* Selected Vehicle Details Panel */}
        <div className="panel" style={{ display: "flex", flexDirection: "column" }}>
          <div className="panel-heading">
            <div>
              <h2>{selected ? selected.truck_id : "Vehicle Details"}</h2>
              <span className="muted">{selected?.current_point_name || "Select a truck"}</span>
            </div>
            {selected && (
              <span className={`badge ${selected.risk.status === "RISKY" ? "danger" : "success"}`}>
                {selected.risk.status}
              </span>
            )}
          </div>

          {selected ? (
            <div style={{ padding: "16px", display: "flex", flexDirection: "column", gap: "14px", flex: 1 }}>
              <div className="detail-grid">
                <div className="stat">
                  <span>Speed</span>
                  <strong>{value(selected.speed_kmh, " km/h")}</strong>
                </div>
                <div className="stat">
                  <span>Cargo Temp</span>
                  <strong>{value(selected.inside_temperature, " °C")}</strong>
                </div>
                <div className="stat">
                  <span>Ambient Temp</span>
                  <strong>{value(selected.outside_temperature, " °C")}</strong>
                </div>
                <div className="stat">
                  <span>Humidity</span>
                  <strong>{value(selected.humidity, " %")}</strong>
                </div>
                <div className="stat">
                  <span>Door State</span>
                  <strong>{value(selected.door_status)}</strong>
                </div>
                <div className="stat">
                  <span>Cooling</span>
                  <strong>{value(selected.refrigeration_status)}</strong>
                </div>
                <div className="stat">
                  <span>Next Station</span>
                  <strong>{value(selected.next_point_name || "Destination")}</strong>
                </div>
                <div className="stat">
                  <span>Destination ETA</span>
                  <strong>
                    {selected.eta
                      ? new Date(selected.eta).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      : "—"}
                  </strong>
                </div>
              </div>

              {/* Action Button to Launch AI Investigation */}
              <button
                className="control primary"
                style={{ width: "100%", marginTop: "auto" }}
                onClick={() => onAskAssistant(selected.truck_id, selected.trip_id)}
              >
                <Bot size={16} /> Investigate Current State
              </button>
            </div>
          ) : (
            <div className="empty-state">Select a vehicle from the map or list to inspect real-time telemetry.</div>
          )}
        </div>
      </div>

      {/* Temperature Telemetry Chart */}
      <div className="panel" style={{ marginBottom: "20px" }}>
        <TemperatureChart data={telemetry} range={telemetryRange} onRangeChange={onRangeChange} />
      </div>

      {/* Active Fleet Table */}
      <div className="panel table-panel">
        <div className="panel-heading">
          <h2>Fleet Telemetry Grid</h2>
          <span className="muted">Live status & sensor updates</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Vehicle ID</th>
                <th>Status</th>
                <th>Location</th>
                <th>Speed</th>
                <th>Temp</th>
                <th>Permitted Band</th>
                <th>Last Update</th>
              </tr>
            </thead>
            <tbody>
              {activeTrucks.map((t) => (
                <tr
                  key={t.truck_id}
                  className={selectedId === t.truck_id ? "selected-row" : ""}
                  onClick={() => onSelect(t.truck_id)}
                >
                  <td>
                    <strong>{t.truck_id}</strong>
                    <small>{t.trip_id || "Trip pending"}</small>
                  </td>
                  <td>
                    <span className={`badge ${t.risk.status === "RISKY" ? "danger" : "success"}`}>
                      {t.risk.status}
                    </span>
                  </td>
                  <td>{t.current_point_name || "In transit"}</td>
                  <td>{value(t.speed_kmh, " km/h")}</td>
                  <td>{value(t.inside_temperature, " °C")}</td>
                  <td>
                    {t.policy_min_temp !== undefined && t.policy_min_temp !== null
                      ? `${t.policy_min_temp}°C to ${t.policy_max_temp}°C`
                      : "2.0°C to 8.0°C"}
                  </td>
                  <td>{ago(t.timestamp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// 3. TRIPS LISTING PAGE
function TripsPage({
  trips,
  searchQuery,
  onViewTrip,
  onGenerateReport,
  onAskAI,
}: {
  trips: Trip[];
  searchQuery: string;
  onViewTrip: (tripId: string) => void;
  onGenerateReport: (tripId: string) => void;
  onAskAI: (tripId: string) => void;
}) {
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const filteredTrips = trips.filter((t) => {
    const matchSearch =
      t.trip_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.truck_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.route_id.toLowerCase().includes(searchQuery.toLowerCase());
    const matchStatus = statusFilter === "ALL" || t.status === statusFilter;
    return matchSearch && matchStatus;
  });

  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>Trips</h1>
          <p>Search, filter, and inspect historical and live cold-chain shipments</p>
        </div>
      </div>

      <div className="filter-toolbar">
        <div className="filter-group">
          <label>Status:</label>
          <select
            className="filter-input"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="ALL">All Statuses</option>
            <option value="ACTIVE">In Progress (Active)</option>
            <option value="COMPLETED">Completed</option>
            <option value="CANCELLED">Cancelled</option>
          </select>
        </div>
        <div style={{ marginLeft: "auto", fontSize: "12px", color: "var(--text-muted)" }}>
          Showing {filteredTrips.length} of {trips.length} trips
        </div>
      </div>

      <div className="panel table-panel">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Trip ID</th>
                <th>Vehicle</th>
                <th>Route</th>
                <th>Cargo Policy</th>
                <th>Started</th>
                <th>Completed</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredTrips.map((t) => (
                <tr key={t.trip_id}>
                  <td>
                    <strong>{t.trip_id}</strong>
                  </td>
                  <td>{t.truck_id}</td>
                  <td>{t.route_id}</td>
                  <td>{t.cargo_type || t.cargo_policy_id || "PHARMA_VACCINE"}</td>
                  <td>{t.started_at ? new Date(t.started_at).toLocaleString() : "—"}</td>
                  <td>{t.completed_at ? new Date(t.completed_at).toLocaleString() : "—"}</td>
                  <td>
                    <span
                      className={`badge ${
                        t.status === "ACTIVE" ? "blue" : t.status === "COMPLETED" ? "success" : "neutral"
                      }`}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "6px" }}>
                      <button className="link-button" onClick={() => onViewTrip(t.trip_id)}>
                        View
                      </button>
                      {t.status === "COMPLETED" && (
                        <button className="link-button" onClick={() => onGenerateReport(t.trip_id)}>
                          Report
                        </button>
                      )}
                      <button className="link-button" onClick={() => onAskAI(t.trip_id)}>
                        Ask AI
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// 4. TRIP DETAILS & REPORT PAGE
function TripDetailPage({
  tripId,
  trips,
  routes,
  onBack,
  onGenerateReport,
  onAskAI,
}: {
  tripId?: string;
  trips: Trip[];
  routes: Record<string, Route>;
  onBack: () => void;
  onGenerateReport: (tripId: string) => void;
  onAskAI: (tripId: string) => void;
}) {
  const [tripTelemetry, setTripTelemetry] = useState<Telemetry[]>([]);
  const [loadingTelem, setLoadingTelem] = useState(false);

  const trip = trips.find((t) => t.trip_id === tripId) || trips[0];
  const route = trip ? routes[trip.route_id] : undefined;

  useEffect(() => {
    if (trip?.trip_id) {
      setLoadingTelem(true);
      void api
        .telemetry(trip.trip_id)
        .then(setTripTelemetry)
        .finally(() => setLoadingTelem(false));
    }
  }, [trip?.trip_id]);

  if (!trip) {
    return <div className="empty-state">Trip not found.</div>;
  }

  return (
    <div>
      <div className="page-heading">
        <div>
          <button className="link-button" onClick={onBack} style={{ marginBottom: "6px" }}>
            ← Back to Trips
          </button>
          <h1>Trip Details: {trip.trip_id}</h1>
          <p>
            Vehicle: <strong>{trip.truck_id}</strong> | Route: <strong>{trip.route_id}</strong>
          </p>
        </div>

        <div className="heading-actions">
          <button className="control secondary" onClick={() => onAskAI(trip.trip_id)}>
            <Bot size={15} /> Ask AI About Trip
          </button>
          {trip.status === "COMPLETED" && (
            <button className="control primary" onClick={() => onGenerateReport(trip.trip_id)}>
              <FileText size={15} /> Generate Report
            </button>
          )}
        </div>
      </div>

      {/* Summary KPI Grid */}
      {(() => {
        const temps = tripTelemetry.map(t => t.inside_temperature).filter((t): t is number => typeof t === "number");
        const minTemp = temps.length ? Math.min(...temps) : null;
        const maxTemp = temps.length ? Math.max(...temps) : null;
        const speeds = tripTelemetry.map(t => t.speed_kmh).filter((s): s is number => typeof s === "number");
        const avgSpeed = speeds.length ? (speeds.reduce((a, b) => a + b, 0) / speeds.length).toFixed(1) : "—";
        const maxSpeed = speeds.length ? Math.max(...speeds).toFixed(1) : "—";

        // Distance from first to last telemetry sample
        const totalDist = tripTelemetry.length > 0 && tripTelemetry[tripTelemetry.length - 1].total_distance_km !== undefined
          ? tripTelemetry[tripTelemetry.length - 1].total_distance_km
          : "—";

        return (
          <div className="kpi-grid" style={{ marginBottom: "20px" }}>
            <div className="kpi">
              <div className="kpi-content">
                <span>Trip Status</span>
                <strong style={{ color: trip.status === "ACTIVE" ? "#3b82f6" : trip.status === "COMPLETED" ? "#10b981" : "inherit" }}>
                  {trip.status}
                </strong>
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-content">
                <span>Cargo Policy</span>
                <strong style={{ fontSize: "14px" }}>{trip.cargo_type || trip.cargo_policy_id || "PHARMA_VACCINE"}</strong>
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-content">
                <span>Distance & Speed</span>
                <strong>{totalDist !== "—" ? `${totalDist} km` : `${avgSpeed} km/h avg`}</strong>
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-content">
                <span>Observed Temp Range</span>
                <strong>{minTemp !== null && maxTemp !== null ? `${minTemp}°C to ${maxTemp}°C` : "—"}</strong>
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-content">
                <span>Telemetry Records</span>
                <strong>{tripTelemetry.length} samples</strong>
              </div>
            </div>
            <div className="kpi">
              <div className="kpi-content">
                <span>Peak Speed</span>
                <strong>{maxSpeed !== "—" ? `${maxSpeed} km/h` : "—"}</strong>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Temperature Telemetry Chart */}
      <div className="panel" style={{ marginBottom: "20px" }}>
        <TemperatureChart data={tripTelemetry} range="all" />
      </div>

      {/* Telemetry Log */}
      <div className="panel table-panel">
        <div className="panel-heading">
          <h2>Recorded Telemetry Log</h2>
          <span className="muted">{tripTelemetry.length} Samples</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Location</th>
                <th>Speed</th>
                <th>Cargo Temp</th>
                <th>Outside Temp</th>
                <th>Door</th>
                <th>Reefer</th>
              </tr>
            </thead>
            <tbody>
              {tripTelemetry.map((t, idx) => (
                <tr key={idx}>
                  <td>{new Date(t.timestamp).toLocaleTimeString()}</td>
                  <td>{t.current_point_name || `${t.latitude.toFixed(4)}, ${t.longitude.toFixed(4)}`}</td>
                  <td>{value(t.speed_kmh, " km/h")}</td>
                  <td>{value(t.inside_temperature, " °C")}</td>
                  <td>{value(t.outside_temperature, " °C")}</td>
                  <td>{t.door_status}</td>
                  <td>{t.refrigeration_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// 5. INCIDENTS & ALERTS PAGE
function IncidentsPage({
  alerts,
  simulation,
  fleet,
  onDismiss,
  onSelectTruck,
}: {
  alerts: AlertEvent[];
  simulation?: Simulation | null;
  fleet?: FleetResponse | null;
  onDismiss: (id: number) => void;
  onSelectTruck: (truckId: string) => void;
}) {
  // Live ticking timer state
  const [nowTime, setNowTime] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowTime(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const isSimRunning = simulation?.status === "RUNNING";
  const activeTripIds = useMemo(
    () => new Set((fleet?.active_trucks || []).map((t) => t.trip_id).filter((id): id is string => Boolean(id))),
    [fleet]
  );
  const simStartedTime = simulation?.started_at ? new Date(simulation.started_at).getTime() : 0;

  const [scopeFilter, setScopeFilter] = useState<string>("CURRENT_RUN");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [selectedIncident, setSelectedIncident] = useState<AlertEvent | null>(null);

  const filtered = alerts.filter((a) => {
    if (scopeFilter === "CURRENT_RUN") {
      if (!isSimRunning) return false;
      const isTripMatch = Boolean(a.trip_id && activeTripIds.has(a.trip_id));
      const isTimeMatch = simStartedTime > 0 ? new Date(a.created_at).getTime() >= simStartedTime - 5000 : true;
      if (!isTripMatch && !isTimeMatch) return false;
    }
    const matchStatus =
      statusFilter === "ALL" ||
      (statusFilter === "ACTIVE" && a.status === "ACTIVE") ||
      (statusFilter === "RESOLVED" && a.status === "RESOLVED") ||
      (statusFilter === "ACKNOWLEDGED" && a.acknowledged);
    const matchSeverity =
      severityFilter === "ALL" || (a.severity || "HIGH").toUpperCase() === severityFilter;
    return matchStatus && matchSeverity;
  });

  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>Incidents & Alerts</h1>
          <p>Real-time audit trail of temperature violations, door events, and operational risks</p>
        </div>
      </div>

      <div className="filter-toolbar">
        <div className="filter-group">
          <label>Scope:</label>
          <select className="filter-input" value={scopeFilter} onChange={(e) => setScopeFilter(e.target.value)}>
            <option value="CURRENT_RUN">Current Simulator Run ({isSimRunning ? "Live" : "Inactive"})</option>
            <option value="ALL">All Historical Incidents</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Status:</label>
          <select className="filter-input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="ALL">All Statuses</option>
            <option value="ACTIVE">Active (Ongoing Excursion)</option>
            <option value="RESOLVED">Resolved (Safe State Restored)</option>
            <option value="ACKNOWLEDGED">Acknowledged</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Severity:</label>
          <select className="filter-input" value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
            <option value="ALL">All Severities</option>
            <option value="CRITICAL">Critical</option>
            <option value="HIGH">High</option>
            <option value="WARNING">Warning / Normal</option>
          </select>
        </div>

        <div style={{ marginLeft: "auto", fontSize: "12px", color: "var(--text-muted)" }}>
          Showing {filtered.length} of {alerts.length} alerts
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: selectedIncident ? "1fr 340px" : "1fr", gap: "20px" }}>
        <div className="panel table-panel">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Incident</th>
                  <th>Status</th>
                  <th>Severity</th>
                  <th>Type</th>
                  <th>Vehicle / Trip</th>
                  <th>Message</th>
                  <th>Duration</th>
                  <th>Detected At</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={9} style={{ textAlign: "center", padding: "30px", color: "var(--text-muted)" }}>
                      {scopeFilter === "CURRENT_RUN" && !isSimRunning
                        ? "Simulation is stopped. No active alerts for the current run."
                        : "No incidents found matching current filters."}
                    </td>
                  </tr>
                ) : (
                  filtered.map((a) => {
                    const isItemActive = a.status === "ACTIVE" && !a.acknowledged;
                    const itemElapsed = isItemActive
                      ? Math.max(0, Math.floor((nowTime - new Date(a.created_at).getTime()) / 1000))
                      : a.duration_seconds;

                    return (
                      <tr
                        key={a.id}
                        onClick={() => setSelectedIncident(a)}
                        style={{
                          cursor: "pointer",
                          background: selectedIncident?.id === a.id ? "var(--bg-table-hover)" : "inherit",
                        }}
                      >
                        <td>
                          <strong>#{a.id}</strong>
                        </td>
                        <td>
                          <span
                            className={`badge ${
                              a.status === "ACTIVE"
                                ? "danger"
                                : a.status === "RESOLVED"
                                ? "success"
                                : "neutral"
                            }`}
                            style={{ fontSize: "10px", padding: "2px 6px" }}
                          >
                            {a.status}
                          </span>
                        </td>
                        <td>
                          <span className={`badge ${a.severity === "CRITICAL" ? "danger" : "warning"}`}>
                            {a.severity || "HIGH"}
                          </span>
                        </td>
                        <td>{a.type}</td>
                        <td>
                          <button
                            className="link-button"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (a.truck_id) onSelectTruck(a.truck_id);
                            }}
                          >
                            {a.truck_id || "FLEET"}
                          </button>
                          <br />
                          <small className="muted">{a.trip_id || "—"}</small>
                        </td>
                        <td style={{ maxWidth: "260px" }}>{a.message}</td>
                        <td>
                          {isItemActive ? (
                            <span style={{ color: "#ef4444", fontWeight: 700 }}>
                              ⏱ {formatDuration(itemElapsed)}
                            </span>
                          ) : a.status === "RESOLVED" ? (
                            <span style={{ color: "#10b981", fontWeight: 600 }}>
                              ✓ {formatDuration(a.duration_seconds)}
                            </span>
                          ) : (
                            formatDuration(a.duration_seconds)
                          )}
                        </td>
                        <td>{new Date(a.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</td>
                        <td>
                          {!a.acknowledged ? (
                            <button
                              className="control secondary"
                              onClick={(e) => {
                                e.stopPropagation();
                                onDismiss(a.id);
                              }}
                            >
                              Acknowledge
                            </button>
                          ) : (
                            <span className="badge neutral">Acknowledged</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {selectedIncident && (
          <div className="panel" style={{ height: "fit-content" }}>
            <div className="panel-heading">
              <h2>Alert Details: #{selectedIncident.id}</h2>
              <button className="icon-button" onClick={() => setSelectedIncident(null)} aria-label="Close">
                <X size={16} />
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "13px" }}>
              <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                <span
                  className={`badge ${
                    selectedIncident.status === "ACTIVE"
                      ? "danger"
                      : selectedIncident.status === "RESOLVED"
                      ? "success"
                      : "neutral"
                  }`}
                  style={{ fontSize: "11px", fontWeight: 700 }}
                >
                  {selectedIncident.status}
                </span>
                <span className={`badge ${selectedIncident.severity === "CRITICAL" ? "danger" : "warning"}`}>
                  {selectedIncident.severity || "HIGH"}
                </span>
              </div>

              <div>
                <span className="muted" style={{ display: "block", fontSize: "11px" }}>RISK TYPE</span>
                <strong>{selectedIncident.type}</strong>
              </div>

              <div>
                <span className="muted" style={{ display: "block", fontSize: "11px" }}>VEHICLE & TRIP</span>
                <strong>{selectedIncident.truck_id || "Fleet wide"}</strong> (Trip: {selectedIncident.trip_id || "—"})
              </div>

              <div>
                <span className="muted" style={{ display: "block", fontSize: "11px" }}>EXCURSION DURATION</span>
                <strong>
                  ⏱{" "}
                  {selectedIncident.status === "ACTIVE"
                    ? formatDuration(Math.max(0, Math.floor((nowTime - new Date(selectedIncident.created_at).getTime()) / 1000)))
                    : formatDuration(selectedIncident.duration_seconds)}
                </strong>
              </div>

              <div>
                <span className="muted" style={{ display: "block", fontSize: "11px" }}>REASON / EXPLANATION</span>
                <p style={{ margin: "4px 0", color: "var(--text-main)" }}>{selectedIncident.message}</p>
              </div>

              {selectedIncident.current_value !== null && selectedIncident.current_value !== undefined && (
                <div>
                  <span className="muted" style={{ display: "block", fontSize: "11px" }}>MEASURED SENSOR VALUE</span>
                  <strong>{selectedIncident.current_value}°C</strong>
                </div>
              )}

              {selectedIncident.threshold_violated && (
                <div>
                  <span className="muted" style={{ display: "block", fontSize: "11px" }}>POLICY THRESHOLD</span>
                  <code>{selectedIncident.threshold_violated}</code>
                </div>
              )}

              <div>
                <span className="muted" style={{ display: "block", fontSize: "11px" }}>TIMESTAMPS</span>
                <div>Detected: {new Date(selectedIncident.created_at).toLocaleString()}</div>
                {selectedIncident.last_observed_at && (
                  <div>Last Observed: {new Date(selectedIncident.last_observed_at).toLocaleString()}</div>
                )}
                {selectedIncident.resolved_at && (
                  <div>Resolved: {new Date(selectedIncident.resolved_at).toLocaleString()}</div>
                )}
              </div>

              <div style={{ borderTop: "1px solid var(--border-color)", paddingTop: "12px", marginTop: "6px" }}>
                {!selectedIncident.acknowledged ? (
                  <button
                    className="control primary"
                    style={{ width: "100%", justifyContent: "center" }}
                    onClick={() => onDismiss(selectedIncident.id)}
                  >
                    Acknowledge Alert
                  </button>
                ) : (
                  <div style={{ textAlign: "center", color: "var(--accent-green)", fontWeight: 600 }}>
                    ✓ Alert Acknowledged
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Refined StrOutput / Markdown Content Formatter for Chat Assistant
function RefinedMessageContent({ text, isUser }: { text: string; isUser: boolean }) {
  // Clean accidental raw prefixes like '*#', '* #', '#*', or duplicate hashes
  const cleanText = text
    .replace(/^\s*[*+-]\s*#+\s*/gm, "")
    .replace(/\*+#+|\*+\s*#+|#+\s*\*+/g, "")
    .trim();

  // Helper to parse inline bold and code
  const renderInline = (str: string) => {
    const parts = str.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith("`") && part.endsWith("`")) {
        return (
          <code
            key={i}
            style={{
              background: isUser ? "rgba(255,255,255,0.2)" : "var(--bg-table-hover)",
              padding: "1px 5px",
              borderRadius: "4px",
              fontSize: "12px",
              fontFamily: "monospace",
              color: isUser ? "#fff" : "var(--brand-color)",
            }}
          >
            {part.slice(1, -1)}
          </code>
        );
      }
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });
  };

  const lines = cleanText.split("\n");
  const elements: React.ReactNode[] = [];
  let tableRows: string[][] = [];
  let inTable = false;

  const flushTable = (keyPrefix: number) => {
    if (tableRows.length === 0) return;
    const headerRow = tableRows[0];
    const dataRows = tableRows.slice(1).filter((r) => !r.every((c) => /^:?-+:?$/.test(c.trim())));
    elements.push(
      <table
        key={`tbl_${keyPrefix}`}
        style={{
          width: "100%",
          borderCollapse: "collapse",
          margin: "8px 0",
          fontSize: "12px",
          background: isUser ? "rgba(255,255,255,0.08)" : "var(--bg-card-subtle)",
          borderRadius: "6px",
          overflow: "hidden",
        }}
      >
        <thead>
          <tr style={{ background: isUser ? "rgba(255,255,255,0.15)" : "var(--bg-table-hover)" }}>
            {headerRow.map((cell, cIdx) => (
              <th key={cIdx} style={{ padding: "6px 10px", textAlign: "left", borderBottom: "1px solid rgba(255,255,255,0.2)" }}>
                {renderInline(cell.trim())}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dataRows.map((row, rIdx) => (
            <tr key={rIdx} style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
              {row.map((cell, cIdx) => (
                <td key={cIdx} style={{ padding: "5px 10px" }}>
                  {renderInline(cell.trim())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
    tableRows = [];
    inTable = false;
  };

  for (let idx = 0; idx < lines.length; idx++) {
    const rawLine = lines[idx];
    const line = rawLine.trim();

    // Markdown Table Detection
    if (line.startsWith("|") && line.endsWith("|")) {
      const cells = line
        .slice(1, -1)
        .split("|")
        .map((c) => c.trim());
      tableRows.push(cells);
      inTable = true;
      continue;
    } else if (inTable) {
      flushTable(idx);
    }

    if (!line) {
      elements.push(<div key={`sp_${idx}`} style={{ height: "6px" }} />);
      continue;
    }

    // Header 3 (###)
    if (line.startsWith("### ")) {
      elements.push(
        <div
          key={`h3_${idx}`}
          style={{
            fontWeight: 700,
            fontSize: "14px",
            marginTop: idx === 0 ? "0px" : "10px",
            marginBottom: "4px",
            color: isUser ? "#ffffff" : "var(--text-heading)",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          {renderInline(line.replace(/^###\s+/, ""))}
        </div>
      );
      continue;
    }

    // Header 4 (####)
    if (line.startsWith("#### ")) {
      elements.push(
        <div
          key={`h4_${idx}`}
          style={{
            fontWeight: 600,
            fontSize: "13px",
            marginTop: "8px",
            marginBottom: "3px",
            color: isUser ? "#ffffff" : "var(--brand-color)",
          }}
        >
          {renderInline(line.replace(/^####\s+/, ""))}
        </div>
      );
      continue;
    }

    // Bullet List (- or *)
    if (line.startsWith("- ") || line.startsWith("* ")) {
      elements.push(
        <div
          key={`li_${idx}`}
          style={{
            paddingLeft: "16px",
            position: "relative",
            margin: "2px 0",
            lineHeight: "1.4",
          }}
        >
          <span style={{ position: "absolute", left: "4px", opacity: 0.7 }}>•</span>
          {renderInline(line.replace(/^[-*]\s+/, ""))}
        </div>
      );
      continue;
    }

    // Regular line
    elements.push(
      <div key={`p_${idx}`} style={{ margin: "2px 0", lineHeight: "1.45" }}>
        {renderInline(line)}
      </div>
    );
  }

  if (inTable) {
    flushTable(lines.length);
  }

  return <div>{elements}</div>;
}

// 6. AI OPERATIONS ASSISTANT PAGE
function AssistantPage({
  chatMessages,
  busy,
  selectedTruck,
  inspectedTripId,
  trips,
  onAsk,
  onSelectTrip,
}: {
  chatMessages: ChatMessage[];
  busy: boolean;
  selectedTruck?: Truck;
  inspectedTripId?: string;
  trips: Trip[];
  onAsk: (prompt: string) => Promise<void>;
  onSelectTrip: (tripId: string) => void;
}) {
  const [input, setInput] = useState("");
  const endRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, busy]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || busy) return;
    const text = input;
    setInput("");
    void onAsk(text);
  };

  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>AI Operations Assistant</h1>
          <p>Conversational investigation grounded in verified database telemetry and cold-chain calculations</p>
        </div>

        {/* Target Context Pill */}
        <div className="heading-actions">
          <label style={{ fontSize: "12px", color: "var(--text-muted)" }}>Target Trip:</label>
          <select
            className="filter-input"
            value={inspectedTripId || ""}
            onChange={(e) => onSelectTrip(e.target.value)}
          >
            <option value="">Auto-detect / All</option>
            {trips.map((t) => (
              <option key={t.trip_id} value={t.trip_id}>
                {t.trip_id} ({t.truck_id})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Main Chat Interface */}
      <div className="panel" style={{ display: "flex", flexDirection: "column", height: "620px" }}>
        <div className="panel-heading">
          <h2>
            <Bot size={16} /> Operations Dialogue
          </h2>
          {inspectedTripId && <span className="badge blue">Context: {inspectedTripId}</span>}
        </div>

        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "16px 20px",
            display: "flex",
            flexDirection: "column",
            gap: "12px",
          }}
        >
          {chatMessages.length === 0 ? (
            <div className="empty-state" style={{ margin: "auto", textAlign: "center", maxWidth: "480px" }}>
              <Bot size={40} style={{ margin: "0 auto 12px auto", opacity: 0.7, color: "var(--brand-color)" }} />
              <h3 style={{ fontSize: "16px", fontWeight: 600, margin: "0 0 6px 0", color: "var(--text-heading)" }}>
                Cold Chain Logistics Analyst
              </h3>
              <p className="muted" style={{ fontSize: "13px", margin: "0 0 16px 0", lineHeight: 1.5 }}>
                Ask natural questions about any vehicle, shipment, zero-speed event, stop timeline, delay calculation, or temperature excursion. Answers are grounded in real telemetry and database calculations.
              </p>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", background: "var(--bg-table-hover)", padding: "10px 14px", borderRadius: "8px", textAlign: "left" }}>
                <div>💡 <strong>Try asking:</strong></div>
                <div style={{ marginTop: "4px" }}>• <em>"Why was speed recorded as 0 at the last ping?"</em></div>
                <div>• <em>"Explain the temperature limits and whether any excursions occurred."</em></div>
                <div>• <em>"Show the formula and calculation for the average speed."</em></div>
                <div>• <em>"Where did the vehicle stop and for how long?"</em></div>
              </div>
            </div>
          ) : (
            chatMessages.map((msg) => (
              <div
                key={msg.id}
                style={{
                  alignSelf: msg.sender === "user" ? "flex-end" : "flex-start",
                  maxWidth: "85%",
                  background: msg.sender === "user" ? "var(--primary-btn)" : "var(--bg-table-hover)",
                  color: msg.sender === "user" ? "#ffffff" : "var(--text-main)",
                  padding: "12px 16px",
                  borderRadius: msg.sender === "user" ? "14px 14px 2px 14px" : "14px 14px 14px 2px",
                  fontSize: "13px",
                  lineHeight: "1.5",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.15)",
                }}
              >
                <RefinedMessageContent text={msg.text} isUser={msg.sender === "user"} />

                {msg.evidence && (
                  <div
                    style={{
                      marginTop: "10px",
                      paddingTop: "8px",
                      borderTop: "1px solid rgba(255,255,255,0.15)",
                      fontSize: "11px",
                      opacity: 0.9,
                      display: "flex",
                      gap: "10px",
                      flexWrap: "wrap",
                    }}
                  >
                    {msg.evidence.data_freshness && (
                      <span>
                        📡 {msg.evidence.data_freshness.freshness_status} (
                        {msg.evidence.data_freshness.age_seconds ?? 0}s ago)
                      </span>
                    )}
                    {msg.evidence.calculated_metrics?.total_distance_km !== undefined && (
                      <span>🚗 {msg.evidence.calculated_metrics.total_distance_km} km</span>
                    )}
                    {msg.evidence.stops?.stop_count !== undefined && (
                      <span>🛑 {msg.evidence.stops.stop_count} stops</span>
                    )}
                    {msg.evidence.temperature_analysis?.excursion_count !== undefined && (
                      <span>❄️ {msg.evidence.temperature_analysis.excursion_count} excursions</span>
                    )}
                  </div>
                )}
              </div>
            ))
          )}

          {busy && (
            <div
              style={{
                alignSelf: "flex-start",
                background: "var(--bg-table-hover)",
                padding: "10px 14px",
                borderRadius: "12px",
                fontSize: "12px",
                color: "var(--text-muted)",
              }}
            >
              ⏳ Querying database telemetry and performing deterministic metric calculations...
            </div>
          )}
          <div ref={endRef} />
        </div>

        <form
          onSubmit={handleSubmit}
          style={{
            display: "flex",
            gap: "10px",
            padding: "12px 16px",
            borderTop: "1px solid var(--border-color)",
            background: "var(--bg-card-subtle)",
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              inspectedTripId
                ? `Ask about trip ${inspectedTripId}, stops, temperatures...`
                : "Ask any operational question..."
            }
            disabled={busy}
            style={{
              flex: 1,
              background: "var(--bg-input)",
              border: "1px solid var(--border-input)",
              color: "var(--text-main)",
              borderRadius: "var(--radius-sm)",
              padding: "10px 14px",
              outline: "none",
            }}
          />
          <button className="control primary" type="submit" disabled={busy || !input.trim()}>
            <Bot size={16} /> Ask Assistant
          </button>
        </form>
      </div>
    </div>
  );
}

// 7. POLICIES & SOPS PAGE
function PoliciesPage({ policies }: { policies: CargoPolicy[] }) {
  return (
    <div>
      <div className="page-heading">
        <div>
          <h1>Policies & SOPs</h1>
          <p>Database-backed cargo temperature boundaries and operational SLA thresholds</p>
        </div>
      </div>

      <div className="panel table-panel">
        <div className="panel-heading">
          <h2>Active Temperature Policies</h2>
          <span className="badge blue">{policies.length} Policies</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Policy ID</th>
                <th>Cargo Classification</th>
                <th>Permitted Minimum</th>
                <th>Permitted Maximum</th>
                <th>Target Temp</th>
                <th>Warning Margin</th>
                <th>Max Door Open</th>
                <th>Max Stopped</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.id}>
                  <td>
                    <strong>{p.id}</strong>
                  </td>
                  <td>{p.cargo_type}</td>
                  <td>{p.min_temperature}°C</td>
                  <td>{p.max_temperature}°C</td>
                  <td>{p.target_temperature}°C</td>
                  <td>±{p.warning_margin}°C</td>
                  <td>{p.door_open_allowed_seconds}s</td>
                  <td>{p.stopped_allowed_seconds}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// REPORT MODAL VIEWER
function ReportModal({ report, onClose }: { report: TripReport; onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <article
        className="report-modal"
        role="dialog"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="panel-heading" style={{ background: "transparent" }}>
          <div>
            <div className="eyebrow">COMPLETED TRIP REPORT</div>
            <h2>{report.trip_id || report.truck_id}</h2>
            <span className="muted">{report.record_count} telemetry records analyzed</span>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="report-grid">
          <div className="stat">
            <span>Safety Status</span>
            <strong style={{ color: report.safety_analysis?.overall_status === "VIOLATION" ? "#ef4444" : "#10b981" }}>
              {report.safety_analysis?.overall_status || "COMPLIANT"}
            </strong>
          </div>
          <div className="stat">
            <span>Excursions</span>
            <strong>{report.temperature_excursions?.length ?? 0}</strong>
          </div>
          <div className="stat">
            <span>Door Events</span>
            <strong>{report.door_events?.length ?? 0}</strong>
          </div>
          <div className="stat">
            <span>Stoppages</span>
            <strong>{report.stoppage_events?.length ?? 0}</strong>
          </div>
        </div>

        <section style={{ margin: "16px 0" }}>
          <h3 style={{ fontSize: "14px", color: "var(--text-heading)" }}>Safety Assessment</h3>
          <p style={{ fontSize: "13px", color: "var(--text-main)", lineHeight: 1.6 }}>
            {report.safety_analysis?.explanation}
          </p>
        </section>

        {report.key_findings && (
          <section style={{ margin: "16px 0" }}>
            <h3 style={{ fontSize: "14px", color: "var(--text-heading)" }}>Key Findings</h3>
            <ul style={{ fontSize: "13px", paddingLeft: "20px", color: "var(--text-main)" }}>
              {report.key_findings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </section>
        )}
      </article>
    </div>
  );
}
