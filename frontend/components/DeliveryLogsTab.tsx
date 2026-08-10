"use client";

import { useState, useEffect, useMemo } from "react";
import {
  getInsightsEndpoints,
  getInsightsTimeseries,
  InsightsEndpoint,
  InsightsTimeseriesResponse,
} from "@/lib/api";

interface DeliveryLogsTabProps {
  destinations: any[];
}

const WINDOW_OPTIONS = [
  { value: "15m", label: "Last 15 minutes" },
  { value: "1h", label: "Last hour" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
] as const;

const METRIC_OPTIONS = [
  { value: "deliveries", label: "Deliveries" },
  { value: "success_rate", label: "Success Rate" },
  { value: "latency_p95", label: "Latency (p95)" },
] as const;

const BUCKET_OPTIONS = [
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
] as const;

const FAILURE_REASON_LABELS: Record<string, string> = {
  "5xx": "Server Error (5xx)",
  "4xx": "Client Error (4xx)",
  timeout: "Timeout",
  connection: "Connection Error",
  other: "Other",
};

export function DeliveryLogsTab({ destinations }: DeliveryLogsTabProps) {
  const [window, setWindow] = useState<"15m" | "1h" | "24h" | "7d">("24h");
  const [metric, setMetric] = useState<"deliveries" | "success_rate" | "latency_p95">("deliveries");
  const [bucket, setBucket] = useState<"hourly" | "daily">("hourly");
  const [endpointsData, setEndpointsData] = useState<InsightsEndpoint[]>([]);
  const [timeseriesData, setTimeseriesData] = useState<InsightsTimeseriesResponse["buckets"]>([]);
  const [isLoadingEndpoints, setIsLoadingEndpoints] = useState(false);
  const [isLoadingTimeseries, setIsLoadingTimeseries] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch endpoints data
  useEffect(() => {
    let mounted = true;
    setIsLoadingEndpoints(true);
    setError(null);

    getInsightsEndpoints(window)
      .then((res) => {
        if (mounted) {
          setEndpointsData(res.endpoints);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load delivery stats");
        }
      })
      .finally(() => {
        if (mounted) setIsLoadingEndpoints(false);
      });

    return () => {
      mounted = false;
    };
  }, [window]);

  // Fetch timeseries data
  useEffect(() => {
    let mounted = true;
    setIsLoadingTimeseries(true);

    getInsightsTimeseries(metric, window, bucket)
      .then((res) => {
        if (mounted) {
          setTimeseriesData(res.buckets);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load time series");
        }
      })
      .finally(() => {
        if (mounted) setIsLoadingTimeseries(false);
      });

    return () => {
      mounted = false;
    };
  }, [metric, window, bucket]);

  // Merge insights with destination info
  const enrichedEndpoints = useMemo(() => {
    return endpointsData.map((ep) => {
      const dest = destinations.find((d) => d.destination_id === ep.endpoint_id);
      return {
        ...ep,
        destination: dest,
        url: dest?.url || ep.endpoint_id,
        bin_id: dest?.bin_id,
      };
    });
  }, [endpointsData, destinations]);

  const formatNumber = (num: number | null | undefined) => {
    if (num === null || num === undefined) return "—";
    if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
    if (num >= 1000) return (num / 1000).toFixed(1) + "K";
    return num.toString();
  };

  const formatPercent = (rate: number | null | undefined) => {
    if (rate === null || rate === undefined) return "—";
    return `${(rate * 100).toFixed(1)}%`;
  };

  const formatLatency = (ms: number | null | undefined) => {
    if (ms === null || ms === undefined) return "—";
    if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
    return `${ms.toFixed(0)}ms`;
  };

  const getFailureReasonLabel = (reason: string | null) => {
    if (!reason) return "—";
    return FAILURE_REASON_LABELS[reason] || reason;
  };

  const getStatusColor = (rate: number | null | undefined) => {
    if (rate === null || rate === undefined) return "text-neutral-500";
    if (rate >= 0.99) return "text-green-600";
    if (rate >= 0.95) return "text-yellow-600";
    return "text-red-600";
  };

  if (destinations.length === 0) {
    return (
      <div className="panel">
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">📊</span>
          <h2>No destinations configured</h2>
          <p>Add destinations in the Destinations tab to see delivery logs and insights.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Delivery Logs</p>
          <h2>Delivery Insights</h2>
          <p className="muted">Monitor webhook delivery performance across all destinations.</p>
        </div>
      </div>

      {/* Controls */}
      <div className="controls-bar">
        <div className="controls-group">
          <label htmlFor="logs-window" className="visually-hidden">Time window</label>
          <select
            id="logs-window"
            value={window}
            onChange={(e) => setWindow(e.target.value as "15m" | "1h" | "24h" | "7d")}
            className="input input-sm"
          >
            {WINDOW_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>

          <label htmlFor="logs-metric" className="visually-hidden">Metric</label>
          <select
            id="logs-metric"
            value={metric}
            onChange={(e) => setMetric(e.target.value as "deliveries" | "success_rate" | "latency_p95")}
            className="input input-sm"
          >
            {METRIC_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>

          <label htmlFor="logs-bucket" className="visually-hidden">Bucket size</label>
          <select
            id="logs-bucket"
            value={bucket}
            onChange={(e) => setBucket(e.target.value as "hourly" | "daily")}
            className="input input-sm"
          >
            {BUCKET_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        {(isLoadingEndpoints || isLoadingTimeseries) && (
          <span className="loading-indicator" aria-live="polite">Loading…</span>
        )}
      </div>

      {error && <div className="status-error" role="alert">{error}</div>}

      {/* Summary Cards */}
      <div className="summary-cards" role="region" aria-label="Delivery summary">
        <article className="summary-card">
          <span className="summary-label">Total Deliveries</span>
          <span className="summary-value">
            {enrichedEndpoints.reduce((sum, ep) => sum + ep.deliveries, 0).toLocaleString()}
          </span>
        </article>
        <article className="summary-card">
          <span className="summary-label">Overall Success Rate</span>
          <span className="summary-value">
            {(() => {
              const totalDelivered = enrichedEndpoints.reduce((sum, ep) => sum + ep.deliveries * ep.success_rate, 0);
              const total = enrichedEndpoints.reduce((sum, ep) => sum + ep.deliveries, 0);
              return total > 0 ? formatPercent(totalDelivered / total) : "—";
            })()}
          </span>
        </article>
        <article className="summary-card">
          <span className="summary-label">Active Destinations</span>
          <span className="summary-value">
            {enrichedEndpoints.filter((ep) => ep.destination?.enabled).length} / {enrichedEndpoints.length}
          </span>
        </article>
        <article className="summary-card">
          <span className="summary-label">Avg Latency (p95)</span>
          <span className="summary-value">
            {(() => {
              const valid = enrichedEndpoints.filter((ep) => ep.p95_ms !== null);
              if (valid.length === 0) return "—";
              const avg = valid.reduce((sum, ep) => sum + (ep.p95_ms || 0), 0) / valid.length;
              return formatLatency(avg);
            })()}
          </span>
        </article>
      </div>

      {/* Time Series Chart Area */}
      <div className="chart-section">
        <h3 className="chart-title">{metric.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase())} Over Time</h3>
        <div className="chart-container" role="img" aria-label={`${metric} chart over ${window}`}>
          {timeseriesData.length === 0 ? (
            <div className="chart-empty">
              <p className="muted">No data available for this period</p>
            </div>
          ) : (
            <div className="chart-bars" role="list" aria-label="Time series bars">
              {timeseriesData.map((bucket, i) => {
                const value = bucket.value;
                const maxValue = Math.max(...timeseriesData.map((b) => b.value ?? 0), 1);
                const height = value !== null ? Math.max((value / maxValue) * 100, 2) : 0;
                const isNull = value === null;

                return (
                  <div key={i} className="chart-bar-wrapper" role="listitem" aria-label={`${bucket.bucket}: ${isNull ? "no data" : metric === "success_rate" ? formatPercent(value) : formatNumber(value)}`}>
                    <div
                      className={`chart-bar ${isNull ? "null" : ""}`}
                      style={{ height: `${height}%` }}
                      title={`${bucket.bucket}: ${isNull ? "no data" : metric === "success_rate" ? formatPercent(value) : metric === "latency_p95" ? formatLatency(value) : formatNumber(value)}`}
                    />
                    <span className="chart-bar-label">{new Date(bucket.bucket).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <div className="chart-legend">
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: metric === "deliveries" ? "var(--primary)" : metric === "success_rate" ? "#22c55e" : "#f97316" }}></span>
            {metric === "deliveries" && "Deliveries (delivered + failed)"}
            {metric === "success_rate" && "Success Rate"}
            {metric === "latency_p95" && "Latency p95"}
          </span>
        </div>
      </div>

      {/* Per-Destination Table */}
      <div className="table-section">
        <h3 className="table-title">Per-Destination Breakdown</h3>
        {isLoadingEndpoints ? (
          <div className="table-loading">Loading destination stats…</div>
        ) : enrichedEndpoints.length === 0 ? (
          <div className="empty-inline">
            <p>No delivery data for this window.</p>
          </div>
        ) : (
          <div className="table-wrapper">
            <table className="data-table" role="table">
              <thead>
                <tr>
                  <th scope="col">Destination</th>
                  <th scope="col">Bin</th>
                  <th scope="col">Status</th>
                  <th scope="col" style={{ textAlign: "right" }}>Deliveries</th>
                  <th scope="col" style={{ textAlign: "right" }}>Success Rate</th>
                  <th scope="col" style={{ textAlign: "right" }}>Latency p50</th>
                  <th scope="col" style={{ textAlign: "right" }}>Latency p95</th>
                  <th scope="col" style={{ textAlign: "right" }}>Latency p99</th>
                  <th scope="col">Top Failure</th>
                </tr>
              </thead>
              <tbody>
                {enrichedEndpoints.map((ep) => (
                  <tr key={ep.endpoint_id}>
                    <td>
                      <div className="destination-cell">
                        <code className="destination-url">{ep.url}</code>
                        <span className="endpoint-id">{ep.endpoint_id.slice(0, 8)}…</span>
                      </div>
                    </td>
                    <td>
                      <span className="bin-badge">{ep.bin_id || "—"}</span>
                    </td>
                    <td>
                      <span className={`status-badge ${ep.destination?.enabled ? "enabled" : "disabled"}`}>
                        {ep.destination?.enabled ? "Active" : "Disabled"}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className="mono">{formatNumber(ep.deliveries)}</span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className={`mono ${getStatusColor(ep.success_rate)}`}>
                        {formatPercent(ep.success_rate)}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className="mono">{formatLatency(ep.p50_ms)}</span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className="mono">{formatLatency(ep.p95_ms)}</span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className="mono">{formatLatency(ep.p99_ms)}</span>
                    </td>
                    <td>
                      <span className="failure-reason">{getFailureReasonLabel(ep.top_failure_reason)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent Activity Hint */}
      <div className="panel-hint">
        <p className="muted">
          Data refreshed from insights API. For real-time delivery logs, check the
          <code>/api/deliveries</code> and <code>/api/dlq</code> endpoints directly.
        </p>
      </div>
    </div>
  );
}