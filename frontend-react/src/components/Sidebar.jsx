import {
  CLIENT_MONTHLY_BUDGET_INR,
  DAILY_USER_RUN_LIMIT,
  DAILY_USER_TOKEN_LIMIT,
  DURATIONS,
  LANGUAGES,
  PLATFORMS,
  getLimitsForTone,
} from "../constants.js";

function QuotaPanel({ quotaStatus, viaPhp }) {
  const budget = Number(quotaStatus?.monthly_budget_inr || CLIENT_MONTHLY_BUDGET_INR);
  const available = quotaStatus ? Number(quotaStatus.available_inr ?? budget) : budget;
  const spent = Math.max(0, Number((budget - available).toFixed(2)));
  const usedPct = budget > 0 ? Math.min(100, Math.max(0, Math.round((spent / budget) * 100))) : 0;
  const isPaused = Boolean(quotaStatus?.auto_paused || available <= 0);
  const isLow = Boolean(quotaStatus?.low_balance_warning || usedPct >= 80);

  const runsUsed = Number(quotaStatus?.daily_runs_used ?? 0);
  const runsLimit = Number(quotaStatus?.daily_runs_limit ?? DAILY_USER_RUN_LIMIT);
  const tokensUsed = Number(quotaStatus?.daily_tokens_used ?? 0);
  const tokensLimit = Number(quotaStatus?.daily_tokens_limit ?? DAILY_USER_TOKEN_LIMIT);

  return (
    <div className="quota-panel" aria-label="CRM Quota Status">
      <div className="quota-row">
        <span>Client Monthly Cap</span>
        <span className="quota-value">
          ₹{available.toFixed(2)} / ₹{budget.toFixed(0)}
        </span>
      </div>
      <div className="quota-meter" role="progressbar" aria-valuenow={usedPct} aria-valuemin={0} aria-valuemax={100}>
        <div
          className={`quota-meter-fill ${isPaused ? "danger" : isLow ? "warn" : ""}`}
          style={{ width: `${usedPct}%` }}
        />
      </div>
      <div className="quota-row">
        <span>Employee Daily Cap</span>
        <span className="quota-value">
          {runsUsed} / {runsLimit} runs
        </span>
      </div>
      <div className="quota-row">
        <span>Daily Token Usage</span>
        <span className="quota-value">
          {tokensUsed.toLocaleString()} / {(tokensLimit / 1000).toFixed(0)}k
        </span>
      </div>
      {isPaused ? (
        <div className="quota-alert-inline">Auto-paused at ₹{budget.toFixed(0)} monthly spend.</div>
      ) : isLow ? (
        <div className="quota-alert-inline">{quotaStatus?.low_balance_message || "80% monthly budget alert."}</div>
      ) : !viaPhp ? (
        <div className="helper-text">PHP gateway signs employee JWT automatically.</div>
      ) : null}
    </div>
  );
}

function ModeSection({ form, onChange, quotaStatus, viaPhp }) {
  return (
    <section className="side-group">
      <h2 className="side-label">1. Mode</h2>
      <div className="segmented" role="group" aria-label="Workspace Mode">
        <button
          type="button"
          className={`seg-btn ${form.mode === "standalone" ? "active" : ""}`}
          onClick={() => onChange("mode", "standalone")}
        >
          Standalone Studio
        </button>
        <button
          type="button"
          className={`seg-btn ${form.mode === "crm" ? "active" : ""}`}
          onClick={() => onChange("mode", "crm")}
        >
          CRM Client Mode
        </button>
      </div>

      {form.mode === "crm" ? (
        <div className="crm-fields">
          <label className="field-label" htmlFor="clientIdInput">
            CRM Client ID
          </label>
          <input
            id="clientIdInput"
            className="input"
            type="text"
            value={form.clientId}
            onChange={(e) => onChange("clientId", e.target.value)}
            placeholder="vg_demo_clinic"
          />
          <QuotaPanel quotaStatus={quotaStatus} viaPhp={viaPhp} />
        </div>
      ) : null}
    </section>
  );
}

function TopicSection({ form, onChange }) {
  return (
    <section className="side-group">
      <h2 className="side-label">2. Topic</h2>
      <label className="field-label" htmlFor="topicInput">
        Primary Video Topic
      </label>
      <textarea
        id="topicInput"
        className="textarea"
        rows={3}
        value={form.topic}
        onChange={(e) => onChange("topic", e.target.value)}
        placeholder="Enter a topic in English, Tamil, or Tanglish..."
      />

      <label className="field-label" htmlFor="objectiveInput">
        Conversion Objective
      </label>
      <input
        id="objectiveInput"
        className="input"
        type="text"
        value={form.objective}
        onChange={(e) => onChange("objective", e.target.value)}
        placeholder="e.g., Get agency leads, Book a free clinic setup call"
      />

      <details className="side-details">
        <summary>
          <span className="material-symbols-rounded" aria-hidden="true">
            tune
          </span>
          <span>Audience &amp; Reference URL</span>
        </summary>
        <div className="details-body">
          <label className="field-label" htmlFor="audienceInput">
            Target Audience
          </label>
          <input
            id="audienceInput"
            className="input"
            type="text"
            value={form.audience}
            onChange={(e) => onChange("audience", e.target.value)}
          />
          <label className="field-label" htmlFor="nicheInput">
            Niche / Category
          </label>
          <input
            id="nicheInput"
            className="input"
            type="text"
            value={form.niche}
            onChange={(e) => onChange("niche", e.target.value)}
          />
          <label className="field-label" htmlFor="refUrlInput">
            Client Reference URL (Optional)
          </label>
          <input
            id="refUrlInput"
            className="input"
            type="url"
            value={form.referenceUrl}
            onChange={(e) => onChange("referenceUrl", e.target.value)}
            placeholder="https://clientwebsite.com/offer"
          />
        </div>
      </details>
    </section>
  );
}

function FormatSection({ form, onChange, limits, paceRate }) {
  return (
    <section className="side-group">
      <h2 className="side-label">3. Format</h2>
      <label className="field-label" htmlFor="platformSelect">
        Platform
      </label>
      <select
        id="platformSelect"
        className="select"
        value={form.platform}
        onChange={(e) => onChange("platform", e.target.value)}
      >
        {PLATFORMS.map((platform) => (
          <option key={platform} value={platform}>
            {platform}
          </option>
        ))}
      </select>

      <span className="field-label">Duration</span>
      <div className="segmented" role="group" aria-label="Target Duration">
        {DURATIONS.map((sec) => (
          <button
            key={sec}
            type="button"
            className={`seg-btn ${form.duration === sec ? "active" : ""}`}
            onClick={() => onChange("duration", sec)}
          >
            {sec}s
          </button>
        ))}
      </div>

      <span className="field-label">Language</span>
      <div className="segmented segmented-stack" role="group" aria-label="Script Language">
        {LANGUAGES.map((lang) => (
          <button
            key={lang.value}
            type="button"
            className={`seg-btn ${form.language === lang.value ? "active" : ""}`}
            onClick={() => onChange("language", lang.value)}
          >
            {lang.label}
          </button>
        ))}
      </div>
      <div className="helper-text">
        Target: {limits.label} words ({paceRate})
      </div>
    </section>
  );
}

export function Sidebar({ form, onChange, onGenerate, isLoading, loadingLabel, quotaStatus, bootstrap }) {
  const limits = getLimitsForTone(form.duration, form.language);
  const paceRate = form.language === "English" ? "~2.4 w/s" : "~2.2 w/s";

  return (
    <aside className="sidebar" aria-label="Script Controls">
      <div className="sidebar-scroll">
        <ModeSection form={form} onChange={onChange} quotaStatus={quotaStatus} viaPhp={bootstrap?.viaPhp} />
        <hr className="side-divider" />
        <TopicSection form={form} onChange={onChange} />
        <hr className="side-divider" />
        <FormatSection form={form} onChange={onChange} limits={limits} paceRate={paceRate} />
      </div>

      <div className="sidebar-footer">
        <button type="button" className="btn-primary" onClick={onGenerate} disabled={isLoading}>
          <span className="material-symbols-rounded" aria-hidden="true">
            bolt
          </span>
          <span>{isLoading ? loadingLabel : "Generate Script"}</span>
        </button>
      </div>
    </aside>
  );
}
