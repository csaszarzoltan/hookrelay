"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  listTransformations,
  createTransformation,
  updateTransformation,
  deleteTransformation,
  Transformation,
  CreateTransformationRequest,
  UpdateTransformationRequest,
  BUILTIN_FUNCTIONS,
  BuiltinFunction,
  previewTransformation,
} from "@/lib/api";

interface TransformationsTabProps {
  transformations: Transformation[];
  onSaved: () => void;
}

const SAMPLE_FILTERS = [
  ".created_at = now",
  '.status = "active"',
  ".user.email |= lowercase",
  ".request_id = uuid",
  ".payload_hash = hash",
  ".secret |= mask_secrets",
];

const SAMPLE_PAYLOAD = {
  event: "webhook.received",
  timestamp: "2024-01-15T10:30:00Z",
  user: {
    id: 12345,
    email: "USER@EXAMPLE.COM",
    name: "John Doe",
  },
  data: {
    order_id: "ORD-789",
    amount: 99.99,
    items: [
      { product: "Widget A", quantity: 2 },
      { product: "Widget B", quantity: 1 },
    ],
  },
  secret: "sk_live_abcdef123456",
  request_id: "req_abc123",
};

export function TransformationsTab({ transformations, onSaved }: TransformationsTabProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingTransform, setEditingTransform] = useState<Transformation | null>(null);
  const [name, setName] = useState("");
  const [filters, setFilters] = useState<string[]>([""]);
  const [testPayload, setTestPayload] = useState(JSON.stringify(SAMPLE_PAYLOAD, null, 2));
  const [previewResult, setPreviewResult] = useState<any>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"builder" | "preview">("builder");

  // Update preview when filters or payload change
  useEffect(() => {
    const validFilters = filters.filter((f) => f.trim() !== "");
    if (validFilters.length === 0) {
      setPreviewResult(null);
      setPreviewError(null);
      return;
    }

    let cancelled = false;
    try {
      let payload: any;
      try {
        payload = JSON.parse(testPayload);
      } catch {
        setPreviewError("Invalid JSON in test payload");
        setPreviewResult(null);
        return;
      }

      previewTransformation(validFilters, payload)
        .then((result) => {
          if (!cancelled) {
            setPreviewResult(result);
            setPreviewError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setPreviewError(err instanceof Error ? err.message : "Preview failed");
            setPreviewResult(null);
          }
        });
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "Preview failed");
      setPreviewResult(null);
    }
    return () => {
      cancelled = true;
    };
  }, [filters, testPayload]);

  // Sync with parent transformations
  useEffect(() => {
    if (!editingTransform) return;
    const current = transformations.find((t) => t.transform_id === editingTransform.transform_id);
    if (current && (current.name !== name || JSON.stringify(current.filters) !== JSON.stringify(filters))) {
      // Parent data changed externally, could sync here if needed
    }
  }, [transformations, editingTransform]);

  const openCreateModal = useCallback(() => {
    setEditingTransform(null);
    setName("");
    setFilters([""]);
    setTestPayload(JSON.stringify(SAMPLE_PAYLOAD, null, 2));
    setPreviewResult(null);
    setPreviewError(null);
    setError(null);
    setSuccess(null);
    setIsModalOpen(true);
  }, []);

  const openEditModal = useCallback((transform: Transformation) => {
    setEditingTransform(transform);
    setName(transform.name);
    setFilters(transform.filters.length > 0 ? transform.filters : [""]);
    setTestPayload(JSON.stringify(SAMPLE_PAYLOAD, null, 2));
    setPreviewResult(null);
    setPreviewError(null);
    setError(null);
    setSuccess(null);
    setIsModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setIsModalOpen(false);
    setEditingTransform(null);
    setName("");
    setFilters([""]);
  }, []);

  const addFilter = useCallback(() => {
    setFilters((prev) => [...prev, ""]);
  }, []);

  const removeFilter = useCallback((index: number) => {
    setFilters((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateFilter = useCallback((index: number, value: string) => {
    setFilters((prev) => {
      const next = [...prev];
      next[index] = value;
      return next;
    });
  }, []);

  const insertBuiltin = useCallback((builtin: BuiltinFunction) => {
    const path = ".field"; // default path
    let snippet = "";
    switch (builtin) {
      case "uppercase":
      case "lowercase":
        snippet = `.field |= ${builtin}`;
        break;
      case "timestamp":
      case "uuid":
      case "hash":
      case "mask_secrets":
        snippet = `.field = ${builtin}`;
        break;
    }
    // Insert at the end of the last filter, or create new
    setFilters((prev) => {
      const lastIndex = prev.length - 1;
      const next = [...prev];
      if (next[lastIndex].trim() === "") {
        next[lastIndex] = snippet;
      } else {
        next.push(snippet);
      }
      return next;
    });
  }, []);

  const handleSave = async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    const validFilters = filters.filter((f) => f.trim() !== "");
    if (validFilters.length === 0) {
      setError("At least one filter is required");
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      if (editingTransform) {
        await updateTransformation(editingTransform.transform_id, { name: name.trim(), filters: validFilters });
        setSuccess("Transformation updated");
      } else {
        await createTransformation({ name: name.trim(), filters: validFilters });
        setSuccess("Transformation created");
      }
      onSaved();
      setTimeout(closeModal, 800);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (transform: Transformation) => {
    if (!window.confirm(`Delete transformation "${transform.name}"?`)) return;
    try {
      await deleteTransformation(transform.transform_id);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const formatJson = (obj: any) => {
    return JSON.stringify(obj, null, 2);
  };

  const renderJson = (obj: any, indent = 0): React.ReactNode => {
    if (obj === null) {
      return <span className="json-null">null</span>;
    }
    if (typeof obj !== "object") {
      if (typeof obj === "string") return <span className="json-string">"{obj}"</span>;
      if (typeof obj === "number") return <span className="json-number">{obj}</span>;
      if (typeof obj === "boolean") return <span className="json-boolean">{obj.toString()}</span>;
      return <span>{String(obj)}</span>;
    }
    const pad = (level: number) => ({ marginLeft: `${level * 2}ch` });
    if (Array.isArray(obj)) {
      if (obj.length === 0) return <span className="json-null">[]</span>;
      return (
        <span>
          {"["}
          <br />
          {obj.map((item, i) => (
            <span key={i} style={pad(indent + 1)}>
              {renderJson(item, indent + 1)}
              {i < obj.length - 1 ? "," : ""}
              <br />
            </span>
          ))}
          <span style={pad(indent)}>{"]"}</span>
        </span>
      );
    }
    const keys = Object.keys(obj);
    if (keys.length === 0) return <span className="json-null">{"{}"}</span>;
    return (
      <span>
        {"{"}
        <br />
        {keys.map((key, i) => (
          <span key={key} style={pad(indent + 1)}>
            <span className="json-key">"{key}"</span>: {renderJson(obj[key], indent + 1)}
            {i < keys.length - 1 ? "," : ""}
            <br />
          </span>
        ))}
        <span style={pad(indent)}>{"}"}</span>
      </span>
    );
  };

  if (transformations.length === 0 && !isModalOpen) {
    return (
      <div className="panel">
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">⚙️</span>
          <h2>No transformations yet</h2>
          <p>Create a transformation to modify webhook payloads before delivery. Use JQ-style filters with built-in functions like <code>uppercase</code>, <code>timestamp</code>, <code>uuid</code>, and more.</p>
          <button className="btn btn-primary" onClick={openCreateModal}>Create Transformation</button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Transformations</p>
            <h2>Payload Transformation Rules</h2>
            <p className="muted">Define JQ-style filters to modify webhook payloads before forwarding. Each transformation can be attached to one or more destinations.</p>
          </div>
          <button className="btn btn-primary" onClick={openCreateModal}>
            + Create Transformation
          </button>
        </div>

        {transformations.length > 0 && (
          <div className="transformations-grid">
            {transformations.map((transform) => (
              <article key={transform.transform_id} className="transformation-card">
                <div className="transformation-header">
                  <div>
                    <h3 className="transformation-name">{transform.name}</h3>
                    <p className="transformation-meta">
                      {transform.filters.length} filter{transform.filters.length !== 1 ? "s" : ""} ·
                      Updated {new Date(transform.updated_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="transformation-actions">
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => openEditModal(transform)}
                      aria-label={`Edit ${transform.name}`}
                    >
                      Edit
                    </button>
                    <button
                      className="btn btn-sm btn-ghost btn-danger"
                      onClick={() => handleDelete(transform)}
                      aria-label={`Delete ${transform.name}`}
                    >
                      Delete
                    </button>
                  </div>
                </div>
                <div className="transformation-filters">
                  {transform.filters.map((filter, i) => (
                    <div key={i} className="filter-chip">
                      <code>{filter}</code>
                    </div>
                  ))}
                  {transform.filters.length === 0 && (
                    <span className="muted">No filters</span>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {/* Modal */}
      {isModalOpen && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{editingTransform ? "Edit Transformation" : "Create Transformation"}</h2>
              <button className="modal-close" onClick={closeModal} aria-label="Close">×</button>
            </div>

            <div className="modal-tabs" role="tablist">
              <button
                role="tab"
                aria-selected={activeTab === "builder"}
                onClick={() => setActiveTab("builder")}
                className={activeTab === "builder" ? "active" : ""}
              >
                Builder
              </button>
              <button
                role="tab"
                aria-selected={activeTab === "preview"}
                onClick={() => setActiveTab("preview")}
                className={activeTab === "preview" ? "active" : ""}
              >
                Live Preview
              </button>
            </div>

            {error && <div className="status-error" role="alert">{error}</div>}
            {success && <div className="status-success" role="status">{success}</div>}

            {activeTab === "builder" && (
              <div className="modal-body builder-tab">
                <div className="form-group">
                  <label htmlFor="transform-name">Name</label>
                  <input
                    id="transform-name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g., add-timestamp, normalize-user-email"
                    className="input"
                  />
                  <p className="form-hint">Human-readable name for this transformation</p>
                </div>

                <div className="form-group">
                  <div className="form-group-header">
                    <label>Filters (JQ-style)</label>
                    <span className="muted">Applied in order, top to bottom</span>
                  </div>
                  <div className="filters-editor">
                    {filters.map((filter, index) => (
                      <div key={index} className="filter-row">
                        <input
                          type="text"
                          value={filter}
                          onChange={(e) => updateFilter(index, e.target.value)}
                          placeholder={index === 0 ? '.field = "value" | .other = now' : 'Add another filter...'}
                          className="input filter-input"
                          aria-label={`Filter ${index + 1}`}
                        />
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => removeFilter(index)}
                          disabled={filters.length === 1}
                          aria-label={`Remove filter ${index + 1}`}
                        >
                          −
                        </button>
                      </div>
                    ))}
                    <button type="button" className="btn btn-sm btn-secondary" onClick={addFilter}>
                      + Add Filter
                    </button>
                  </div>

                  {/* Built-in function chips */}
                  <div className="builtins-section">
                    <p className="form-hint">Quick-insert built-in functions:</p>
                    <div className="builtin-chips">
                      {BUILTIN_FUNCTIONS.map((builtin) => (
                        <button
                          key={builtin.name}
                          type="button"
                          className="builtin-chip"
                          onClick={() => insertBuiltin(builtin.name)}
                          title={builtin.description}
                        >
                          {builtin.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <details className="filter-examples">
                    <summary>Filter syntax examples</summary>
                    <div className="code-block">
                      {SAMPLE_FILTERS.map((f, i) => (
                        <div key={i}><code>{f}</code></div>
                      ))}
                    </div>
                  </details>
                </div>
              </div>
            )}

            {activeTab === "preview" && (
              <div className="modal-body preview-tab">
                <div className="preview-layout">
                  <div className="preview-pane">
                    <label>Test Payload (JSON)</label>
                    <textarea
                      value={testPayload}
                      onChange={(e) => setTestPayload(e.target.value)}
                      className="code-input"
                      rows={15}
                      spellCheck={false}
                      aria-label="Test payload JSON"
                    />
                  </div>
                  <div className="preview-pane">
                    <label>Preview Output</label>
                    {previewError && (
                      <div className="preview-output error" role="alert">
                        <pre>{previewError}</pre>
                      </div>
                    )}
                    {previewResult !== null && !previewError && (
                      <div className="preview-output success" role="region" aria-label="Transformation preview">
                        <pre>{formatJson(previewResult)}</pre>
                      </div>
                    )}
                    {previewResult === null && !previewError && (
                      <div className="preview-output empty" aria-live="polite">
                        <p className="muted">Enter valid filters and JSON to see preview</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={closeModal} disabled={isSaving}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleSave} disabled={isSaving}>
                {isSaving ? "Saving…" : editingTransform ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}