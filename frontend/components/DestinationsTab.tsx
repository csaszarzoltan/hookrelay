"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  listDestinations,
  createDestination,
  updateDestination,
  deleteDestination,
  listBins,
  listTransformations,
  Destination,
  CreateDestinationRequest,
  UpdateDestinationRequest,
  CaptureBin,
  Transformation,
} from "@/lib/api";

interface DestinationsTabProps {
  destinations: Destination[];
  bins: CaptureBin[];
  transformations: Transformation[];
  onSaved: () => void;
}

const SIGNING_ALGORITHMS = [
  { value: "svix", label: "Svix (HMAC-SHA256)", description: "Standard webhook signing" },
  { value: "hookdeck", label: "Hookdeck", description: "Hookdeck-compatible signature" },
  { value: "github", label: "GitHub", description: "GitHub webhook signature format" },
  { value: "custom", label: "Custom", description: "Custom algorithm and header" },
] as const;

const DELIVERY_MODES = [
  { value: "broadcast", label: "Broadcast", description: "Send to all destinations" },
  { value: "round_robin", label: "Round Robin", description: "Cycle through destinations" },
  { value: "weighted", label: "Weighted", description: "Distribute by weight" },
] as const;

const DEFAULT_RETRY_POLICY = {
  max_attempts: 5,
  base_delay_ms: 1000,
  max_delay_ms: 300000,
  backoff_multiplier: 2,
  retry_on: [408, 429, 500, 502, 503, 504],
};

export function DestinationsTab({ destinations, bins, transformations, onSaved }: DestinationsTabProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingDestination, setEditingDestination] = useState<Destination | null>(null);
  const [formData, setFormData] = useState<Partial<CreateDestinationRequest>>({
    bin_id: "",
    url: "",
    transform_id: "",
    signing_config: {},
    headers: {},
    retry_policy: DEFAULT_RETRY_POLICY,
    enabled: true,
    weight: 1,
    delivery_mode: "broadcast",
  });
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"basic" | "signing" | "retry" | "advanced">("basic");

  // Reset form when modal opens/closes or editing target changes
  const resetForm = useCallback((dest?: Destination) => {
    if (dest) {
      setFormData({
        bin_id: dest.bin_id,
        url: dest.url,
        transform_id: dest.transform_id || "",
        signing_config: dest.signing_config || {},
        headers: dest.headers || {},
        retry_policy: dest.retry_policy || DEFAULT_RETRY_POLICY,
        enabled: dest.enabled,
        weight: dest.weight,
        delivery_mode: dest.delivery_mode,
      });
    } else {
      setFormData({
        bin_id: "",
        url: "",
        transform_id: "",
        signing_config: {},
        headers: {},
        retry_policy: DEFAULT_RETRY_POLICY,
        enabled: true,
        weight: 1,
        delivery_mode: "broadcast",
      });
    }
  }, []);

  const openCreateModal = useCallback(() => {
    setEditingDestination(null);
    resetForm();
    setError(null);
    setSuccess(null);
    setActiveTab("basic");
    setIsModalOpen(true);
  }, [resetForm]);

  const openEditModal = useCallback((dest: Destination) => {
    setEditingDestination(dest);
    resetForm(dest);
    setError(null);
    setSuccess(null);
    setActiveTab("basic");
    setIsModalOpen(true);
  }, [resetForm]);

  const closeModal = useCallback(() => {
    setIsModalOpen(false);
    setEditingDestination(null);
  }, []);

  const updateField = useCallback(<T extends keyof CreateDestinationRequest>(field: T, value: CreateDestinationRequest[T]) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  }, []);

  const updateNestedField = useCallback(<T extends object>(parent: keyof CreateDestinationRequest, field: string, value: any) => {
    setFormData((prev) => ({
      ...prev,
      [parent]: { ...(prev[parent] as T), [field]: value },
    }));
  }, []);

  const handleSave = async () => {
    if (!formData.bin_id) {
      setError("Capture bin is required");
      return;
    }
    if (!formData.url) {
      setError("Destination URL is required");
      return;
    }
    if (!formData.url.startsWith("http://") && !formData.url.startsWith("https://")) {
      setError("URL must start with http:// or https://");
      return;
    }
    if ((formData.weight ?? 1) < 1) {
      setError("Weight must be at least 1");
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      const payload = {
        bin_id: formData.bin_id,
        url: formData.url,
        transform_id: formData.transform_id || undefined,
        signing_config: Object.keys(formData.signing_config || {}).length > 0 ? formData.signing_config : undefined,
        headers: Object.keys(formData.headers || {}).length > 0 ? formData.headers : undefined,
        retry_policy: formData.retry_policy,
        enabled: formData.enabled,
        weight: formData.weight,
        delivery_mode: formData.delivery_mode,
      } as CreateDestinationRequest;

      if (editingDestination) {
        await updateDestination(editingDestination.destination_id, payload);
        setSuccess("Destination updated");
      } else {
        await createDestination(payload);
        setSuccess("Destination created");
      }
      onSaved();
      setTimeout(closeModal, 800);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (dest: Destination) => {
    if (!window.confirm(`Delete destination "${dest.url}"?`)) return;
    try {
      await deleteDestination(dest.destination_id);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  // Group destinations by bin for display
  const destinationsByBin = useMemo(() => {
    const grouped: Record<string, Destination[]> = {};
    destinations.forEach((d) => {
      if (!grouped[d.bin_id]) grouped[d.bin_id] = [];
      grouped[d.bin_id].push(d);
    });
    return grouped;
  }, [destinations]);

  if (bins.length === 0) {
    return (
      <div className="panel">
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">🎯</span>
          <h2>No capture bins available</h2>
          <p>Create a capture bin first to add destinations. Destinations belong to a capture bin and define where webhooks are forwarded.</p>
        </div>
      </div>
    );
  }

  if (destinations.length === 0 && !isModalOpen) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Destinations</p>
            <h2>Forwarding Destinations</h2>
            <p className="muted">Configure where webhooks are delivered. Each destination belongs to a capture bin and can have transformations, signing, and retry policies.</p>
          </div>
          <button className="btn btn-primary" onClick={openCreateModal}>
            + Add Destination
          </button>
        </div>
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">🎯</span>
          <h2>No destinations yet</h2>
          <p>Add your first destination to start forwarding webhooks.</p>
          <button className="btn btn-primary" onClick={openCreateModal}>Add Destination</button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Destinations</p>
            <h2>Forwarding Destinations</h2>
            <p className="muted">Configure where webhooks are delivered. Each destination belongs to a capture bin and can have transformations, signing, and retry policies.</p>
          </div>
          <button className="btn btn-primary" onClick={openCreateModal}>
            + Add Destination
          </button>
        </div>

        {bins.map((bin) => {
          const binDestinations = destinationsByBin[bin.bin_id] || [];
          return (
            <section key={bin.bin_id} className="bin-section">
              <div className="bin-header">
                <div>
                  <h3 className="bin-name">{bin.name || bin.description || bin.bin_id}</h3>
                  <p className="bin-meta">{bin.request_count} requests · {binDestinations.length} destination{binDestinations.length !== 1 ? "s" : ""}</p>
                </div>
              </div>
              {binDestinations.length > 0 ? (
                <div className="destinations-grid">
                  {binDestinations.map((dest) => (
                    <article key={dest.destination_id} className="destination-card">
                      <div className="destination-header">
                        <div className="destination-url">
                          <span className="url-badge">{dest.url}</span>
                          <span className={`status-badge ${dest.enabled ? "enabled" : "disabled"}`}>
                            {dest.enabled ? "Active" : "Disabled"}
                          </span>
                        </div>
                        <div className="destination-actions">
                          <button
                            className="btn btn-sm btn-ghost"
                            onClick={() => openEditModal(dest)}
                            aria-label={`Edit ${dest.url}`}
                          >
                            Edit
                          </button>
                          <button
                            className="btn btn-sm btn-ghost btn-danger"
                            onClick={() => handleDelete(dest)}
                            aria-label={`Delete ${dest.url}`}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                      <div className="destination-details">
                        <div className="detail-row">
                          <span className="detail-label">Mode</span>
                          <span className="detail-value mode-badge">{dest.delivery_mode.replace("_", " ")}</span>
                        </div>
                        {dest.transform_id && (
                          <div className="detail-row">
                            <span className="detail-label">Transform</span>
                            <span className="detail-value">
                              {transformations.find((t) => t.transform_id === dest.transform_id)?.name || dest.transform_id}
                            </span>
                          </div>
                        )}
                        <div className="detail-row">
                          <span className="detail-label">Signing</span>
                          <span className="detail-value">
                            {dest.signing_config?.algorithm ? `${dest.signing_config.algorithm}` : "None"}
                          </span>
                        </div>
                        <div className="detail-row">
                          <span className="detail-label">Stats</span>
                          <span className="detail-value">
                            ✓ {dest.delivered_count} · ✗ {dest.failed_count}
                          </span>
                        </div>
                        {Object.keys(dest.headers || {}).length > 0 && (
                          <div className="detail-row">
                            <span className="detail-label">Headers</span>
                            <span className="detail-value">{Object.keys(dest.headers).length} custom</span>
                          </div>
                        )}
                        <div className="detail-row">
                          <span className="detail-label">Retry</span>
                          <span className="detail-value">
                            {dest.retry_policy?.max_attempts ?? "Default"} attempts
                          </span>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty-inline">
                  <p>No destinations for this bin.</p>
                  <button className="btn btn-sm btn-secondary" onClick={openCreateModal}>Add first destination</button>
                </div>
              )}
            </section>
          );
        })}
      </div>

      {/* Modal */}
      {isModalOpen && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{editingDestination ? "Edit Destination" : "Add Destination"}</h2>
              <button className="modal-close" onClick={closeModal} aria-label="Close">×</button>
            </div>

            <div className="modal-tabs" role="tablist">
              <button role="tab" aria-selected={activeTab === "basic"} onClick={() => setActiveTab("basic")} className={activeTab === "basic" ? "active" : ""}>Basic</button>
              <button role="tab" aria-selected={activeTab === "signing"} onClick={() => setActiveTab("signing")} className={activeTab === "signing" ? "active" : ""}>Signing</button>
              <button role="tab" aria-selected={activeTab === "retry"} onClick={() => setActiveTab("retry")} className={activeTab === "retry" ? "active" : ""}>Retry Policy</button>
              <button role="tab" aria-selected={activeTab === "advanced"} onClick={() => setActiveTab("advanced")} className={activeTab === "advanced" ? "active" : ""}>Advanced</button>
            </div>

            {error && <div className="status-error" role="alert">{error}</div>}
            {success && <div className="status-success" role="status">{success}</div>}

            {activeTab === "basic" && (
              <div className="modal-body">
                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="dest-bin">Capture Bin *</label>
                    <select
                      id="dest-bin"
                      value={formData.bin_id}
                      onChange={(e) => updateField("bin_id", e.target.value)}
                      className="input"
                      required
                    >
                      {bins.map((bin) => (
                        <option key={bin.bin_id} value={bin.bin_id}>
                          {bin.name || bin.description || bin.bin_id} ({bin.bin_id})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label htmlFor="dest-url">Destination URL *</label>
                    <input
                      id="dest-url"
                      type="url"
                      value={formData.url}
                      onChange={(e) => updateField("url", e.target.value)}
                      placeholder="https://example.com/webhook"
                      className="input"
                      required
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label htmlFor="dest-transform">Transformation (optional)</label>
                  <select
                    id="dest-transform"
                    value={formData.transform_id}
                    onChange={(e) => updateField("transform_id", e.target.value || "")}
                    className="input"
                  >
                    <option value="">— No transformation —</option>
                    {transformations.map((t) => (
                      <option key={t.transform_id} value={t.transform_id}>
                        {t.name} ({t.filters.length} filters)
                      </option>
                    ))}
                  </select>
                  <p className="form-hint">Apply a transformation to the payload before delivery</p>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="dest-weight">Weight</label>
                    <input
                      id="dest-weight"
                      type="number"
                      min="1"
                      value={formData.weight ?? 1}
                      onChange={(e) => updateField("weight", parseInt(e.target.value) || 1)}
                      className="input"
                    />
                    <p className="form-hint">Used for weighted delivery mode</p>
                  </div>
                  <div className="form-group">
                    <label htmlFor="dest-mode">Delivery Mode</label>
                    <select
                      id="dest-mode"
                      value={formData.delivery_mode}
                      onChange={(e) => updateField("delivery_mode", e.target.value as "broadcast" | "round_robin" | "weighted")}
                      className="input"
                    >
                      {DELIVERY_MODES.map((mode) => (
                        <option key={mode.value} value={mode.value}>
                          {mode.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="form-group">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={formData.enabled}
                      onChange={(e) => updateField("enabled", e.target.checked)}
                    />
                    <span>Enabled</span>
                  </label>
                  <p className="form-hint">Disable to pause deliveries without deleting</p>
                </div>
              </div>
            )}

            {activeTab === "signing" && (
              <div className="modal-body">
                <div className="form-group">
                  <label>Signing Algorithm</label>
                  <select
                    value={formData.signing_config?.algorithm || ""}
                    onChange={(e) => updateNestedField("signing_config", "algorithm", e.target.value || undefined)}
                    className="input"
                  >
                    <option value="">— None (no signing) —</option>
                    {SIGNING_ALGORITHMS.map((alg) => (
                      <option key={alg.value} value={alg.value}>
                        {alg.label}
                      </option>
                    ))}
                  </select>
                  <p className="form-hint">Choose a signing algorithm to verify webhook authenticity</p>
                </div>

                {(formData.signing_config?.algorithm || "") && (
                  <>
                    <div className="form-group">
                      <label htmlFor="signing-key">Signing Key / Secret *</label>
                      <input
                        id="signing-key"
                        type="password"
                        value={formData.signing_config?.key || ""}
                        onChange={(e) => updateNestedField("signing_config", "key", e.target.value)}
                        placeholder="Enter signing secret"
                        className="input"
                        required
                      />
                      <p className="form-hint">Shared secret used to compute the signature</p>
                    </div>

                    <div className="form-row">
                      <div className="form-group">
                        <label htmlFor="signing-header">Header Name</label>
                        <input
                          id="signing-header"
                          type="text"
                          value={formData.signing_config?.header_name || "x-webhook-signature"}
                          onChange={(e) => updateNestedField("signing_config", "header_name", e.target.value || "x-webhook-signature")}
                          className="input"
                        />
                      </div>
                      <div className="form-group">
                        <label htmlFor="signing-timestamp">Timestamp Header</label>
                        <input
                          id="signing-timestamp"
                          type="text"
                          value={formData.signing_config?.timestamp_header || "x-webhook-timestamp"}
                          onChange={(e) => updateNestedField("signing_config", "timestamp_header", e.target.value || "x-webhook-timestamp")}
                          className="input"
                        />
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {activeTab === "retry" && (
              <div className="modal-body">
                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="retry-max">Max Attempts</label>
                    <input
                      id="retry-max"
                      type="number"
                      min="1"
                      max="20"
                      value={formData.retry_policy?.max_attempts ?? 5}
                      onChange={(e) => updateNestedField("retry_policy", "max_attempts", parseInt(e.target.value) || 5)}
                      className="input"
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="retry-base">Base Delay (ms)</label>
                    <input
                      id="retry-base"
                      type="number"
                      min="100"
                      value={formData.retry_policy?.base_delay_ms ?? 1000}
                      onChange={(e) => updateNestedField("retry_policy", "base_delay_ms", parseInt(e.target.value) || 1000)}
                      className="input"
                    />
                  </div>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="retry-maxdelay">Max Delay (ms)</label>
                    <input
                      id="retry-maxdelay"
                      type="number"
                      min="1000"
                      value={formData.retry_policy?.max_delay_ms ?? 300000}
                      onChange={(e) => updateNestedField("retry_policy", "max_delay_ms", parseInt(e.target.value) || 300000)}
                      className="input"
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="retry-multiplier">Backoff Multiplier</label>
                    <input
                      id="retry-multiplier"
                      type="number"
                      min="1"
                      step="0.1"
                      value={formData.retry_policy?.backoff_multiplier ?? 2}
                      onChange={(e) => updateNestedField("retry_policy", "backoff_multiplier", parseFloat(e.target.value) || 2)}
                      className="input"
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label>Retry on Status Codes</label>
                  <div className="status-code-chips">
                    {[408, 429, 500, 502, 503, 504].map((code) => (
                      <label key={code} className="status-code-chip">
                        <input
                          type="checkbox"
                          checked={(formData.retry_policy?.retry_on || []).includes(code)}
                          onChange={(e) => {
                            const current = formData.retry_policy?.retry_on || [];
                            const next = e.target.checked
                              ? [...current, code]
                              : current.filter((c) => c !== code);
                            updateNestedField("retry_policy", "retry_on", next);
                          }}
                        />
                        {code}
                      </label>
                    ))}
                  </div>
                  <p className="form-hint">HTTP status codes that trigger a retry</p>
                </div>
              </div>
            )}

            {activeTab === "advanced" && (
              <div className="modal-body">
                <div className="form-group">
                  <label>Custom Headers</label>
                  <p className="form-hint">Additional headers to include with each delivery (JSON object)</p>
                  <textarea
                    value={JSON.stringify(formData.headers || {}, null, 2)}
                    onChange={(e) => {
                      try {
                        const parsed = JSON.parse(e.target.value);
                        updateField("headers", parsed);
                      } catch {
                        // ignore invalid JSON while typing
                      }
                    }}
                    className="code-input"
                    rows={8}
                    spellCheck={false}
                    placeholder='{"X-Custom-Header": "value", "Authorization": "Bearer token"}'
                  />
                </div>
              </div>
            )}

            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={closeModal} disabled={isSaving}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleSave} disabled={isSaving}>
                {isSaving ? "Saving…" : editingDestination ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}