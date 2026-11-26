import { useEffect, useMemo, useState } from "react";
import { apiRequest, readBootstrapContext } from "./apiClient.js";
import { AlertBanner } from "./components/AlertBanner.jsx";
import { EmptyState } from "./components/EmptyState.jsx";
import { ResultWorkspace } from "./components/ResultWorkspace.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { DEFAULT_CONTEXT_FIELDS, PRESETS, normalizeLanguageValue } from "./constants.js";

const INITIAL_FORM_BASE = {
  topic: "",
  objective: "Get agency leads",
  ...DEFAULT_CONTEXT_FIELDS,
  platform: "Instagram Reels",
  duration: 30,
  language: "Tanglish",
};

function toErrorState(err, fallbackTitle) {
  return {
    title: err.title || fallbackTitle,
    message: err.message,
    details: err.details || [],
    variant: err.variant || "error",
  };
}

export function App({ bootstrapOverride = null }) {
  const bootstrap = useMemo(() => bootstrapOverride || readBootstrapContext(), [bootstrapOverride]);

  const [form, setForm] = useState({
    ...INITIAL_FORM_BASE,
    mode: bootstrap.defaultMode || "standalone",
    clientId: bootstrap.defaultClientId || "vg_demo_clinic",
  });

  const [health, setHealth] = useState(null);
  const [recentScripts, setRecentScripts] = useState([]);
  const [deliverable, setDeliverable] = useState(null);
  const [markdown, setMarkdown] = useState("");
  const [clipfalconHandoff, setClipfalconHandoff] = useState(null);
  const [quotaStatus, setQuotaStatus] = useState(null);
  const [regenObjective, setRegenObjective] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState("Generating...");
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    apiRequest("/api/v1/health", {}, bootstrap)
      .then((h) => active && setHealth(h))
      .catch(() => active && setHealth(null));
    apiRequest("/api/v1/scripts/recent?limit=4", {}, bootstrap)
      .then((r) => active && Array.isArray(r?.items) && setRecentScripts(r.items))
      .catch(() => active && setRecentScripts([]));
    return () => {
      active = false;
    };
  }, [bootstrap]);

  function handleFormChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleSelectPreset(index) {
    const preset = PRESETS[index];
    if (!preset) return;
    setError(null);
    setForm((prev) => ({
      ...prev,
      topic: preset.topic,
      platform: preset.platform,
      duration: preset.duration,
      language: preset.language,
      objective: preset.objective,
      audience: preset.audience,
      niche: preset.niche,
      // A reference URL belongs to one client brief; never carry it into a preset topic.
      referenceUrl: "",
    }));
  }

  function handleResetContext() {
    setForm((prev) => ({ ...prev, ...DEFAULT_CONTEXT_FIELDS }));
  }

  function handleNewScript() {
    // Start clean: drop the old topic and any audience/niche/URL left from the last run.
    setDeliverable(null);
    setMarkdown("");
    setClipfalconHandoff(null);
    setError(null);
    setForm((prev) => ({ ...prev, topic: "", objective: INITIAL_FORM_BASE.objective, ...DEFAULT_CONTEXT_FIELDS }));
  }

  function applyResultPayload(data) {
    setDeliverable(data.deliverable);
    setMarkdown(data.markdown || "");
    setClipfalconHandoff(data.clipfalcon_handoff || null);
    if (data.quota_status) setQuotaStatus(data.quota_status);
    setRegenObjective(data.deliverable?.input_data?.objective || "");
    const busyWarning = data.deliverable?.generation_warning;
    const liveWarning = data.deliverable?.research?.live_data_warning;
    if (busyWarning) {
      setError({ title: "AI was busy", message: busyWarning, details: liveWarning ? [liveWarning] : [], variant: "warn" });
    } else if (liveWarning) {
      setError({ title: "Live data not fetched", message: liveWarning, details: [], variant: "warn" });
    } else {
      setError(null);
    }
  }

  async function executeScriptRequest(endpoint, body, nextLoadingLabel, fallbackTitle) {
    setError(null);
    setIsLoading(true);
    setLoadingLabel(nextLoadingLabel);
    try {
      const data = await apiRequest(endpoint, { method: "POST", body }, bootstrap);
      applyResultPayload(data);
    } catch (err) {
      setError(toErrorState(err, fallbackTitle));
    } finally {
      setIsLoading(false);
    }
  }

  async function handleGenerate() {
    if (!form.topic.trim()) {
      setError({ title: "Missing Topic", message: "Enter a video topic before generating.", details: [], variant: "error" });
      return;
    }
    const requestBody = {
      topic: form.topic.trim(),
      conversion_objective: form.objective.trim() || "awareness",
      platform: form.platform,
      duration_seconds: form.duration,
      language: normalizeLanguageValue(form.language),
      reference_url: form.referenceUrl.trim() || null,
      audience: form.audience.trim() || null,
      niche: form.niche.trim() || null,
      mode: form.mode,
      client_id: form.mode === "crm" ? form.clientId.trim() : null,
    };
    await executeScriptRequest("/api/v2/scripts/generate", requestBody, "Generating...", "Generation Failed");
  }

  async function handleRegenerate(section) {
    if (!deliverable) return;
    const isCrm = form.mode === "crm" && Boolean(deliverable.deliverable_id);
    const requestBody = {
      section,
      mode: isCrm ? "crm" : "standalone",
      client_id: isCrm ? form.clientId.trim() : null,
      deliverable_id: deliverable.deliverable_id || null,
      deliverable: isCrm ? null : deliverable,
      conversion_objective: section === "cta" ? regenObjective.trim() || null : null,
    };
    const nextLabel = section === "hook" ? "Refreshing hooks..." : "Refreshing CTA...";
    await executeScriptRequest("/api/v2/scripts/regenerate", requestBody, nextLabel, "Regeneration Failed");
  }

  async function handleOpenRecent(stem) {
    setError(null);
    try {
      const data = await apiRequest(`/api/v1/scripts/recent/${encodeURIComponent(stem)}`, {}, bootstrap);
      applyResultPayload(data);
    } catch (err) {
      setError(toErrorState(err, "Failed to Load Script"));
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        form={form}
        onChange={handleFormChange}
        onResetContext={handleResetContext}
        onGenerate={handleGenerate}
        isLoading={isLoading}
        loadingLabel={loadingLabel}
        quotaStatus={quotaStatus}
        bootstrap={bootstrap}
      />
      <main className="workspace">
        <TopBar health={health} bootstrap={bootstrap} />
        <AlertBanner error={error} />
        {deliverable ? (
          <ResultWorkspace
            deliverable={deliverable}
            markdown={markdown}
            clipfalconHandoff={clipfalconHandoff}
            regenObjective={regenObjective}
            onChangeRegenObjective={setRegenObjective}
            onRegenerateHooks={() => handleRegenerate("hook")}
            onRegenerateCta={() => handleRegenerate("cta")}
            onBack={handleNewScript}
            isLoading={isLoading}
          />
        ) : (
          <EmptyState onSelectPreset={handleSelectPreset} recentScripts={recentScripts} onOpenRecent={handleOpenRecent} />
        )}
      </main>
    </div>
  );
}

export default App;
