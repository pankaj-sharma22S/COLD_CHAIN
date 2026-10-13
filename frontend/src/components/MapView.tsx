import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import { Fragment, useEffect, useRef, useState } from "react";
import type { Route, Truck, UpcomingWaypoint, Weather } from "../types";

const tileUrl = import.meta.env.VITE_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";

const truckIcon = (risk: string, isSelected: boolean) => L.divIcon({
  className: "truck-marker",
  html: `<span class="truck-dot ${risk === "RISKY" ? "risk" : "normal"}" style="${isSelected ? "transform: scale(1.25); box-shadow: 0 0 0 4px #3b82f6aa;" : ""}">🚚</span>`,
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

function getRiskColor(status?: string, severity?: string | null): string {
  const sev = (severity || "").toUpperCase();
  const stat = (status || "").toUpperCase();
  if (sev === "CRITICAL" || sev === "RED") return "#ef4444";
  if (sev === "HIGH" || sev === "ORANGE") return "#f97316";
  if (sev === "MEDIUM" || sev === "YELLOW") return "#f59e0b";
  if (sev === "LOW" || sev === "BLUE") return "#06b6d4";
  if (stat === "RISKY") return "#ef4444";
  return "#10b981"; // NORMAL (green)
}

function formatEta(value?: string | null) {
  if (!value) return "Unavailable";
  try {
    return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return String(value);
  }
}

function MapViewController({
  selectedTruck,
  allPoints,
}: {
  selectedTruck?: Truck;
  allPoints: L.LatLngExpression[];
}) {
  const map = useMap();
  const fitted = useRef(false);

  // Fit all bounds once on initial load
  useEffect(() => {
    if (allPoints.length && !fitted.current) {
      map.fitBounds(L.latLngBounds(allPoints), { padding: [36, 36], maxZoom: 10 });
      fitted.current = true;
    }
  }, [map, allPoints]);

  // When selected truck changes, pan gently to it
  useEffect(() => {
    if (selectedTruck) {
      map.panTo([selectedTruck.latitude, selectedTruck.longitude], { animate: true, duration: 0.6 });
    }
  }, [map, selectedTruck?.truck_id]);

  return null;
}

export function MapView({
  trucks,
  routes,
  selected,
  selectedTruck,
  weather,
  onSelect,
}: {
  trucks: Truck[];
  routes: Record<string, Route>;
  selected?: string;
  selectedTruck?: Truck;
  weather?: Weather;
  onSelect: (id: string) => void;
}) {
  const allPoints: L.LatLngExpression[] = trucks.map(t => [t.latitude, t.longitude]);
  Object.values(routes).forEach(route => {
    const pts = (route.geometry && route.geometry.length > 0) ? route.geometry : [route.source, ...route.waypoints, route.destination];
    pts.forEach(p => allPoints.push([p.latitude, p.longitude]));
  });

  const selectedRoute = selectedTruck?.route_id ? routes[selectedTruck.route_id] : undefined;
  const progressPoints: L.LatLngExpression[] = selectedRoute && selectedTruck ? calculateProgressPath(selectedRoute, selectedTruck) : [];
  const upcomingWaypoints: UpcomingWaypoint[] = selectedTruck?.upcoming_waypoints || [];

  return (
    <div>
      {/* Fleet Selector Toolbar */}
      {trucks.length > 0 && (
        <div className="map-toolbar">
          <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-muted)" }}>Active Fleet:</span>
          <select
            className="truck-select"
            value={selected || ""}
            onChange={e => onSelect(e.target.value)}
            aria-label="Select truck to focus"
          >
            {trucks.map(t => (
              <option key={t.truck_id} value={t.truck_id}>
                {t.truck_id} — {t.current_point_name || "En route"} ({t.risk.status})
              </option>
            ))}
          </select>
          <span style={{ fontSize: "11px", color: "var(--text-dim)", marginLeft: "auto" }}>
            Showing {trucks.length} active truck{trucks.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {!allPoints.length ? (
        <div className="map-empty">Map waiting for backend route or telemetry data.</div>
      ) : (
        <MapContainer center={allPoints[0]} zoom={8} className="map" scrollWheelZoom>
          <TileLayer attribution='&copy; OpenStreetMap contributors' url={tileUrl} />
          <MapViewController selectedTruck={selectedTruck} allPoints={allPoints} />

          {/* Actual Road-Following Routes for All Trucks */}
          {Object.values(routes).map(route => {
            const isSelectedRoute = selectedTruck?.route_id === route.route_id;
            const roadCoords: L.LatLngExpression[] = (route.geometry && route.geometry.length >= 2)
              ? route.geometry.map(p => [p.latitude, p.longitude] as [number, number])
              : [route.source, ...route.waypoints, route.destination].map(p => [p.latitude, p.longitude] as [number, number]);

            return (
              <Fragment key={route.route_id}>
                {/* Road-following Polyline */}
                <Polyline
                  positions={roadCoords}
                  pathOptions={{
                    color: isSelectedRoute ? "#3b82f6" : "#64748b",
                    weight: isSelectedRoute ? 5 : 3.5,
                    opacity: isSelectedRoute ? 0.9 : 0.65,
                  }}
                />

                {/* Origin and Destination markers */}
                <StationCircle point={route.source} label={`Origin: ${route.source.name || "Origin"}`} color="#3b82f6" />
                <StationCircle point={route.destination} label={`Destination: ${route.destination.name || "Destination"}`} color="#10b981" />
              </Fragment>
            );
          })}

          {/* Blue progress path for currently focused truck along the road */}
          {progressPoints.length > 1 && (
            <Polyline positions={progressPoints} pathOptions={{ color: "#2563eb", weight: 6, opacity: 0.95 }} />
          )}

          {/* Upcoming Waypoints for Focused Truck */}
          {upcomingWaypoints.map(wp => (
            <WaypointMarker key={String(wp.waypoint_id)} wp={wp} />
          ))}

          {/* All Trucks displayed simultaneously with continuous markers */}
          {trucks.map(truck => (
            <AnimatedTruckMarker
              key={truck.truck_id}
              truck={truck}
              isSelected={truck.truck_id === selected}
              onSelect={onSelect}
            />
          ))}
        </MapContainer>
      )}
    </div>
  );
}

function calculateProgressPath(route: Route, truck: Truck): L.LatLngExpression[] {
  const road = (route.geometry && route.geometry.length >= 2) ? route.geometry : [route.source, ...route.waypoints, route.destination];
  if (!road.length) return [];

  let minD = Infinity;
  let closestIdx = 0;
  for (let i = 0; i < road.length; i++) {
    const d = Math.hypot(road[i].latitude - truck.latitude, road[i].longitude - truck.longitude);
    if (d < minD) {
      minD = d;
      closestIdx = i;
    }
  }

  const traversed = road.slice(0, closestIdx + 1).map(p => [p.latitude, p.longitude] as [number, number]);
  traversed.push([truck.latitude, truck.longitude]);
  return traversed;
}

function StationCircle({ point, label, color }: { point: { latitude: number; longitude: number; name?: string | null }; label: string; color: string }) {
  return (
    <CircleMarker
      center={[point.latitude, point.longitude]}
      radius={6}
      pathOptions={{ color, fillColor: color, fillOpacity: 0.9, weight: 2 }}
    >
      <Tooltip direction="top" offset={[0, -6]}>
        <strong>{label}</strong>
      </Tooltip>
      <Popup>
        <strong>{label}</strong>
        <div style={{ fontSize: "11px", color: "#64748b" }}>
          {point.latitude.toFixed(4)}, {point.longitude.toFixed(4)}
        </div>
      </Popup>
    </CircleMarker>
  );
}

function WaypointMarker({ wp }: { wp: UpcomingWaypoint }) {
  const [hovered, setHovered] = useState(false);
  const color = getRiskColor(wp.risk_status, wp.risk_severity);
  const isRisky = wp.risk_status === "RISKY";

  return (
    <CircleMarker
      center={[wp.latitude, wp.longitude]}
      radius={hovered || isRisky ? 9 : 7}
      pathOptions={{
        color,
        fillColor: color,
        fillOpacity: hovered || isRisky ? 0.95 : 0.8,
        weight: isRisky ? 3 : 2,
      }}
      eventHandlers={{
        mouseover: () => setHovered(true),
        mouseout: () => setHovered(false),
      }}
    >
      <Tooltip direction="top" offset={[0, -8]} sticky>
        <div style={{ textAlign: "center", lineHeight: "1.4" }}>
          <strong>{wp.location_name}</strong>
          <div>ETA: {formatEta(wp.eta)}</div>
          <div>
            {wp.temperature !== null && wp.temperature !== undefined ? `${wp.temperature} °C` : "—"}{" "}
            {wp.humidity !== null && wp.humidity !== undefined ? `| ${wp.humidity}%` : ""}
          </div>
          <div style={{ color, fontWeight: 700, fontSize: "11px" }}>
            {wp.risk_status} ({wp.risk_severity || "NORMAL"})
          </div>
        </div>
      </Tooltip>

      <Popup>
        <div style={{ minWidth: 200, fontSize: "13px", lineHeight: "1.5" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "4px" }}>
            <strong style={{ fontSize: "15px" }}>{wp.location_name}</strong>
            <span
              style={{
                fontSize: "11px",
                padding: "2px 6px",
                borderRadius: "4px",
                background: isRisky ? "rgba(239, 68, 68, 0.15)" : "rgba(16, 185, 129, 0.15)",
                color: isRisky ? "#ef4444" : "#10b981",
                fontWeight: 700,
              }}
            >
              {wp.risk_status}
            </span>
          </div>

          <div><strong>ETA:</strong> {formatEta(wp.eta)}</div>
          <div><strong>Distance:</strong> {wp.distance_km} km</div>
          <div><strong>Temperature:</strong> {wp.temperature !== null && wp.temperature !== undefined ? `${wp.temperature} °C` : "—"}</div>
          <div><strong>Humidity:</strong> {wp.humidity !== null && wp.humidity !== undefined ? `${wp.humidity} %` : "—"}</div>
          <div>
            <strong>Risk: </strong>
            <span style={{ color, fontWeight: 700 }}>
              {wp.risk_status} ({wp.risk_severity || "NORMAL"})
            </span>
          </div>
          <div style={{ marginTop: "4px", fontSize: "12px", color: "var(--text-muted, #64748b)" }}>
            <strong>Reason:</strong> {wp.risk_reason || "Operating within safe limits"}
          </div>
          <div style={{ marginTop: "6px", fontSize: "11px", color: "var(--text-dim, #94a3b8)" }}>
            Coordinates: {wp.latitude.toFixed(4)}, {wp.longitude.toFixed(4)}
          </div>
        </div>
      </Popup>
    </CircleMarker>
  );
}

function AnimatedTruckMarker({
  truck,
  isSelected,
  onSelect,
}: {
  truck: Truck;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const [position, setPosition] = useState<[number, number]>([truck.latitude, truck.longitude]);
  const previous = useRef<[number, number]>(position);

  useEffect(() => {
    const from = previous.current;
    const to: [number, number] = [truck.latitude, truck.longitude];
    if (from[0] === to[0] && from[1] === to[1]) return;

    const duration = Number(import.meta.env.VITE_TELEMETRY_INTERVAL_MS || 20000);
    const started = performance.now();
    let frame = 0;

    const animate = (now: number) => {
      const progress = Math.min((now - started) / duration, 1);
      setPosition([
        from[0] + (to[0] - from[0]) * progress,
        from[1] + (to[1] - from[1]) * progress,
      ]);
      if (progress < 1) {
        frame = requestAnimationFrame(animate);
      } else {
        previous.current = to;
      }
    };

    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [truck.latitude, truck.longitude]);

  const riskColor = truck.risk.status === "RISKY" ? "#ef4444" : "#10b981";
  const primaryReason = truck.risk.reasons?.[0]?.message || (truck.risk.status === "RISKY" ? "Active telemetry risk detected" : "Operating within safe limits");

  return (
    <Marker
      position={position}
      icon={truckIcon(truck.risk.status, isSelected)}
      eventHandlers={{ click: () => onSelect(truck.truck_id) }}
    >
      <Popup minWidth={240}>
        <div style={{ fontSize: "12px", lineHeight: 1.5, color: "var(--text-main, #1e293b)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
            <strong style={{ fontSize: "15px", color: "var(--text-heading, #0f172a)" }}>{truck.truck_id}</strong>
            <span
              style={{
                fontSize: "10px",
                fontWeight: 700,
                padding: "2px 7px",
                borderRadius: "10px",
                background: truck.risk.status === "RISKY" ? "rgba(239, 68, 68, 0.15)" : "rgba(16, 185, 129, 0.15)",
                color: riskColor,
              }}
            >
              {truck.risk.status}
            </span>
          </div>

          {truck.trip_id && (
            <div style={{ fontSize: "11px", color: "var(--text-muted, #64748b)", marginBottom: "4px" }}>
              Trip: <strong>{truck.trip_id}</strong>
            </div>
          )}

          <div style={{ borderTop: "1px solid var(--border-color, #e2e8f0)", paddingTop: "6px", marginBottom: "6px" }}>
            <div><strong>Location:</strong> {truck.current_point_name || "En route"}</div>
            <div><strong>Speed:</strong> {truck.speed_kmh ?? 0} km/h</div>
            <div>
              <strong>Cargo Temp:</strong>{" "}
              <span style={{ fontWeight: 700, color: truck.risk.status === "RISKY" ? "#ef4444" : "inherit" }}>
                {truck.inside_temperature !== null && truck.inside_temperature !== undefined ? `${truck.inside_temperature} °C` : "—"}
              </span>
              {truck.policy_min_temp !== null && truck.policy_min_temp !== undefined && (
                <span style={{ fontSize: "10px", color: "var(--text-dim, #94a3b8)", marginLeft: "4px" }}>
                  (Safe: {truck.policy_min_temp}°C to {truck.policy_max_temp}°C)
                </span>
              )}
            </div>
            <div><strong>Outside Temp:</strong> {truck.outside_temperature ?? "—"} °C | <strong>Humidity:</strong> {truck.humidity ?? "—"}%</div>
            <div><strong>Door:</strong> {truck.door_status || "CLOSED"} | <strong>Reefer:</strong> {truck.refrigeration_status || "ON"}</div>
          </div>

          <div style={{ borderTop: "1px solid var(--border-color, #e2e8f0)", paddingTop: "6px", marginBottom: "6px" }}>
            <div><strong>Next Station:</strong> {truck.next_station?.name || truck.next_point_name || "—"}</div>
            {truck.remaining_distance_km !== undefined && truck.remaining_distance_km !== null && (
              <div><strong>Distance Left:</strong> {truck.remaining_distance_km} km</div>
            )}
            {truck.eta && (
              <div><strong>ETA:</strong> {formatEta(truck.eta)}</div>
            )}
          </div>

          {truck.risk.status === "RISKY" && (
            <div style={{ marginTop: "4px", fontSize: "11px", color: "#ef4444", background: "rgba(239, 68, 68, 0.08)", padding: "4px 6px", borderRadius: "4px" }}>
              <strong>Risk Reason:</strong> {primaryReason}
            </div>
          )}
        </div>
      </Popup>
    </Marker>
  );
}
