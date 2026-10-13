import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Telemetry } from "../types";

export function TemperatureChart({
  data,
  range = "recent",
  onRangeChange,
}: {
  data: Telemetry[];
  range?: string;
  onRangeChange?: (range: string) => void;
}) {
  const points = data
    .filter(item => item.inside_temperature != null || item.outside_temperature != null)
    .map(item => {
      const dt = new Date(item.timestamp);
      return {
        timestamp: item.timestamp,
        time: dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        date: dt.toLocaleDateString([], { month: "short", day: "numeric" }),
        inside: item.inside_temperature !== null && item.inside_temperature !== undefined ? Number(item.inside_temperature.toFixed(1)) : null,
        outside: item.outside_temperature !== null && item.outside_temperature !== undefined ? Number(item.outside_temperature.toFixed(1)) : null,
      };
    });

  const ranges = [
    { id: "recent", label: "Recent (Trip)" },
    { id: "1h", label: "1 Hour" },
    { id: "6h", label: "6 Hours" },
    { id: "24h", label: "24 Hours" },
    { id: "all", label: "All Telemetry" },
  ];

  return (
    <div>
      <div className="chart-header">
        <span className="eyebrow">TEMPERATURE TELEMETRY</span>
        {onRangeChange && (
          <div className="chart-ranges">
            {ranges.map(r => (
              <button
                key={r.id}
                type="button"
                className={`range-btn ${range === r.id ? "active" : ""}`}
                onClick={() => onRangeChange(r.id)}
              >
                {r.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {!points.length ? (
        <div className="empty-state">No temperature telemetry records found for this time range.</div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={points} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
            <XAxis
              dataKey="time"
              minTickGap={24}
              tick={{ fontSize: 11 }}
            />
            <YAxis
              unit="°C"
              domain={["auto", "auto"]}
              tick={{ fontSize: 11 }}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload;
                return (
                  <div
                    style={{
                      background: "var(--bg-card, #111c2a)",
                      border: "1px solid var(--border-color, #1f2b3a)",
                      padding: "8px 12px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      color: "var(--text-main, #dbe5f2)",
                      boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: "4px" }}>
                      {d.date} at {d.time}
                    </div>
                    {d.inside !== null && (
                      <div style={{ color: "#3b82f6" }}>
                        Cargo Temp: <strong>{d.inside} °C</strong>
                      </div>
                    )}
                    {d.outside !== null && (
                      <div style={{ color: "#f59e0b" }}>
                        Ambient Temp: <strong>{d.outside} °C</strong>
                      </div>
                    )}
                  </div>
                );
              }}
            />
            <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
            <Line
              type="monotone"
              dataKey="inside"
              name="Inside Cargo Temp"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="outside"
              name="Outside Ambient Temp"
              stroke="#f59e0b"
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
