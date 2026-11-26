import { ModulatedText } from "./ModulatedText.jsx";

export function TeleprompterTab({
  script,
  regenObjective,
  onChangeRegenObjective,
  onRegenerateHooks,
  onRegenerateCta,
  isLoading,
}) {
  const hooks = script?.hooks || [];
  const bodyPoints = script?.body_points || [];
  const ctaOptions = script?.cta_options || [];
  const onScreenTexts = script?.on_screen_texts || [];
  const hashtags = script?.hashtags || [];

  return (
    <div>
      <div className="teleprompter-card">
        <div className="tp-section">
          <div className="tp-label">Hook</div>
          <div className="tp-text">
            <ModulatedText text={script?.hook} />
          </div>
        </div>

        <div className="tp-section">
          <div className="tp-label">Body</div>
          {script?.context ? (
            <div className="tp-subtext">
              <ModulatedText text={script.context} />
            </div>
          ) : null}
          <div className="tp-text">
            {bodyPoints.map((point, idx) => (
              <div key={idx}>
                <ModulatedText text={point} />
              </div>
            ))}
          </div>
          {script?.engagement ? (
            <div className="tp-subtext">
              <ModulatedText text={script.engagement} />
            </div>
          ) : null}
        </div>

        <div className="tp-section">
          <div className="tp-label">CTA</div>
          <div className="tp-text tp-strong">
            <ModulatedText text={script?.cta} />
          </div>
        </div>
      </div>

      <h3 className="section-title">Hook Alternatives</h3>
      <div className="grid-3">
        {hooks.map((hookItem, idx) => (
          <div key={idx} className={`surface-card ${hookItem.is_recommended ? "card-active" : ""}`}>
            <div className="card-header">
              <span className="card-kicker">{hookItem.type}</span>
              {hookItem.is_recommended ? <span className="rec-pill">Recommended</span> : null}
            </div>
            <div className="tp-subtext" style={{ color: "#ffffff", margin: 0 }}>
              &ldquo;
              <ModulatedText text={hookItem.text} />
              &rdquo;
            </div>
            {hookItem.reason ? (
              <div className="muted-copy" style={{ marginTop: "8px" }}>
                {hookItem.reason}
              </div>
            ) : null}
          </div>
        ))}
      </div>

      <div className="regen-bar">
        <button type="button" className="btn-secondary" onClick={onRegenerateHooks} disabled={isLoading}>
          <span className="material-symbols-rounded" aria-hidden="true">
            refresh
          </span>
          <span>Regenerate Hooks</span>
        </button>
        <input
          aria-label="Custom CTA objective"
          className="input"
          type="text"
          value={regenObjective}
          onChange={(e) => onChangeRegenObjective(e.target.value)}
          placeholder="Custom CTA objective..."
        />
        <button type="button" className="btn-secondary" onClick={onRegenerateCta} disabled={isLoading}>
          <span className="material-symbols-rounded" aria-hidden="true">
            refresh
          </span>
          <span>Regenerate CTA</span>
        </button>
      </div>

      {ctaOptions.length > 0 ? (
        <div>
          <h3 className="section-title">CTA Alternatives</h3>
          <ul className="clean-list">
            {ctaOptions.map((option, idx) => (
              <li key={idx}>
                <strong>
                  Option {idx + 1}
                  {option.is_recommended ? " (Recommended)" : ""}:{" "}
                </strong>
                <ModulatedText text={option.text} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid-2">
        <div>
          <h3 className="section-title">On-Screen Text</h3>
          <div className="chips-wrap">
            {onScreenTexts.map((item, idx) => (
              <span key={idx} className="chip">
                {item}
              </span>
            ))}
          </div>
        </div>
        <div>
          <h3 className="section-title">Caption &amp; Hashtags</h3>
          <div className="surface-card">
            <p className="muted-copy">{script?.caption}</p>
            <code className="mono-code">{hashtags.join(" ")}</code>
          </div>
        </div>
      </div>
    </div>
  );
}
