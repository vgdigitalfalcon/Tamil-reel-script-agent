import { useState } from "react";
import { getLimitsForTone } from "../constants.js";
import { ExportTab } from "./ExportTab.jsx";
import { QualityAuditTab, buildAuditCriteria } from "./QualityAuditTab.jsx";
import { ResearchTab } from "./ResearchTab.jsx";
import { TeleprompterTab } from "./TeleprompterTab.jsx";

const TABS = [
  { id: "teleprompter", label: "Teleprompter", icon: "mic" },
  { id: "research", label: "Research", icon: "search" },
  { id: "audit", label: "Quality Audit", icon: "verified_user" },
  { id: "export", label: "Export", icon: "download" },
];

export function ResultWorkspace({
  deliverable,
  markdown,
  clipfalconHandoff,
  regenObjective,
  onChangeRegenObjective,
  onRegenerateHooks,
  onRegenerateCta,
  onBack,
  isLoading,
}) {
  const [activeTab, setActiveTab] = useState("teleprompter");
  const [copied, setCopied] = useState(false);

  const inp = deliverable.input_data;
  const script = deliverable.script;
  const qc = deliverable.quality_check;
  const isEnglish = inp.tone === "English";
  const criteria = buildAuditCriteria(qc, isEnglish);
  const passed = criteria.filter(([, item]) => item?.status === "PASS").length;
  const limits = getLimitsForTone(inp.duration, inp.tone);
  const wordsOk = script.word_count >= limits.min && script.word_count <= limits.max;
  const cuesCount = (
    `${script.hook} ${script.context} ${(script.body_points || []).join(" ")} ${script.engagement} ${script.cta}`.match(
      /\[[^\]]+\]/g
    ) || []
  ).length;
  const costLabel = deliverable.cost_inr ? `₹${Number(deliverable.cost_inr).toFixed(4)}` : "₹0.00";

  async function handleCopy() {
    const fullText = [
      `[Hook] ${script.hook}`,
      `[Context] ${script.context}`,
      `[Body]\n${(script.body_points || []).map((pt) => `- ${pt}`).join("\n")}`,
      `[Engagement] ${script.engagement}`,
      `[CTA] ${script.cta}`,
    ].join("\n\n");
    await navigator.clipboard.writeText(fullText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <section>
      <div className="result-toolbar">
        <div className="badge-strip">
          <span className={`audit-badge ${passed === 7 ? "pass" : "flag"}`}>Audit: {passed}/7 Passed</span>
          <span className={`audit-badge ${wordsOk ? "pass" : ""}`}>
            Words: {script.word_count} / {limits.label}
          </span>
          <span className="audit-badge">
            Pacing: {isEnglish ? "~2.4 w/s" : "~2.2 w/s"} · {inp.duration}s
          </span>
          <span className="audit-badge">{inp.tone}</span>
          <span className="audit-badge">Cues: {cuesCount}</span>
          <span className="audit-badge">
            {deliverable.model_used || "simulation"} · {costLabel}
          </span>
        </div>

        <div className="toolbar-actions">
          <button type="button" className="btn-secondary" onClick={onBack}>
            <span className="material-symbols-rounded" aria-hidden="true">
              arrow_back
            </span>
            <span>New</span>
          </button>
          <button type="button" className="btn-secondary" onClick={handleCopy}>
            <span className="material-symbols-rounded" aria-hidden="true">
              content_copy
            </span>
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>
        </div>
      </div>

      <div className="tabs-bar" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`tab-btn ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="material-symbols-rounded" aria-hidden="true">
              {tab.icon}
            </span>
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {activeTab === "teleprompter" ? (
        <TeleprompterTab
          script={script}
          regenObjective={regenObjective}
          onChangeRegenObjective={onChangeRegenObjective}
          onRegenerateHooks={onRegenerateHooks}
          onRegenerateCta={onRegenerateCta}
          isLoading={isLoading}
        />
      ) : null}

      {activeTab === "research" ? <ResearchTab research={deliverable.research} /> : null}

      {activeTab === "audit" ? <QualityAuditTab qc={qc} isEnglish={isEnglish} /> : null}

      {activeTab === "export" ? (
        <ExportTab deliverable={deliverable} markdown={markdown} clipfalconHandoff={clipfalconHandoff} />
      ) : null}
    </section>
  );
}
