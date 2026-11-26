import { PRESETS } from "../constants.js";
import { ModulatedText } from "./ModulatedText.jsx";

export function EmptyState({ onSelectPreset, recentScripts, onOpenRecent }) {
  return (
    <section>
      <div className="hero-wrap">
        <div className="hero-glow" aria-hidden="true" />
        <div className="hero-content">
          <h1 className="hero-title">
            Camera-ready Tamil, Tanglish &amp; English <span className="hero-highlight">reel scripts</span>.
          </h1>
          <p className="hero-sub">
            Research-backed, single-narrator scripts calibrated for camera pacing with inline vocal cues and 7-criteria
            quality audit checks.
          </p>
        </div>
      </div>

      <h2 className="section-title">Start from a preset</h2>
      <div className="grid-3">
        {PRESETS.map((preset, idx) => (
          <button key={preset.title} type="button" className="preset-card" onClick={() => onSelectPreset(idx)}>
            <div className="preset-card-top">
              <span className="preset-title">{preset.title}</span>
              <span className="material-symbols-rounded preset-arrow" aria-hidden="true">
                arrow_outward
              </span>
            </div>
            <div className="preset-meta">{preset.meta}</div>
          </button>
        ))}
      </div>

      <h2 className="section-title">How it works</h2>
      <div className="grid-3">
        <div className="surface-card">
          <div className="step-head">
            <span className="material-symbols-rounded" aria-hidden="true">
              edit_note
            </span>
            <span>1. Topic</span>
          </div>
          <p className="muted-copy">Pick a preset or enter any topic, audience, and optional client URL.</p>
        </div>
        <div className="surface-card">
          <div className="step-head">
            <span className="material-symbols-rounded" aria-hidden="true">
              bolt
            </span>
            <span>2. Generate</span>
          </div>
          <p className="muted-copy">Live web citations feed a single-narrator script with vocal cues.</p>
        </div>
        <div className="surface-card">
          <div className="step-head">
            <span className="material-symbols-rounded" aria-hidden="true">
              verified_user
            </span>
            <span>3. 7-Criteria Audit</span>
          </div>
          <p className="muted-copy">Checks language purity, pacing fit, and zero AI clichés.</p>
        </div>
      </div>

      <h2 className="section-title">Output preview</h2>
      <div className="skeleton-card" aria-hidden="true">
        <div className="skeleton-row">
          <div className="skeleton-tag">Hook</div>
          <div className="skeleton-sample">
            <ModulatedText text="[Direct eye contact] உங்க வெப்சைட் இருந்தும் ஏன் leads வரமாட்டேங்குது தெரியுமா?" />
          </div>
        </div>
        <div className="skeleton-row">
          <div className="skeleton-tag">Body</div>
          <div className="skeleton-bar" style={{ width: "88%" }} />
          <div className="skeleton-bar" style={{ width: "74%" }} />
          <div className="skeleton-bar" style={{ width: "60%" }} />
        </div>
        <div className="skeleton-row">
          <div className="skeleton-tag">CTA</div>
          <div className="skeleton-bar" style={{ width: "50%" }} />
        </div>
      </div>

      {recentScripts && recentScripts.length > 0 ? (
        <div>
          <h2 className="section-title">Recent scripts</h2>
          <div className="recent-list">
            {recentScripts.map((item) => (
              <div key={item.stem} className="recent-row">
                <div>
                  <div className="recent-title">{item.topic}</div>
                  <div className="recent-meta">
                    {item.platform} · {item.duration}s · {item.tone} · {item.word_count} words
                  </div>
                </div>
                <button type="button" className="btn-secondary" onClick={() => onOpenRecent(item.stem)}>
                  <span className="material-symbols-rounded" aria-hidden="true">
                    open_in_new
                  </span>
                  <span>Open</span>
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <details className="guardrails-details">
        <summary>
          <span className="material-symbols-rounded" aria-hidden="true">
            rule
          </span>
          <span>Pacing &amp; Guardrails Reference</span>
        </summary>
        <div className="guardrails-grid">
          <div>
            <strong>Spoken Word Calibration</strong>
            <ul>
              <li>Tamil / Tanglish (~2.2 w/s): 60–75 (30s) · 95–110 (45s) · 125–145 (60s)</li>
              <li>English (~2.4 w/s): 65–80 (30s) · 100–120 (45s) · 130–155 (60s)</li>
            </ul>
          </div>
          <div>
            <strong>Quality &amp; Quota Guardrails</strong>
            <ul>
              <li>Single narrator, zero 2-person skits, zero AI clichés or Sen-Tamil slips</li>
              <li>Client ₹60/month budget lock + Employee 25 runs / 75k tokens/day cap</li>
            </ul>
          </div>
        </div>
      </details>
    </section>
  );
}
