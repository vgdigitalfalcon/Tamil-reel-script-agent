export function ResearchTab({ research }) {
  const findings = research?.key_findings || [];
  const painPoints = research?.pain_points || [];
  const sources = research?.sources || [];
  const uncertainties = research?.uncertainties || [];

  return (
    <div>
      <div className="surface-card card-active">
        <div className="card-kicker">Chosen Content Angle</div>
        <div className="angle-title">{research?.chosen_angle}</div>
        <div className="muted-copy">{research?.angle_reason}</div>
      </div>

      <div className="grid-2">
        <div>
          <h3 className="section-title">Verified Findings</h3>
          <ul className="clean-list">
            {findings.map((finding, idx) => (
              <li key={idx}>{finding}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="section-title">Audience Pain Points</h3>
          <ul className="clean-list">
            {painPoints.map((point, idx) => (
              <li key={idx}>{point}</li>
            ))}
          </ul>
        </div>
      </div>

      <h3 className="section-title">Sources</h3>
      {sources.length > 0 ? (
        <div>
          {sources.map((src, idx) => (
            <div key={idx} className="surface-card" style={{ marginBottom: "10px" }}>
              <a className="source-link" href={src.url} target="_blank" rel="noopener noreferrer">
                {src.title || src.url}
              </a>
              <span className="chip" style={{ marginLeft: "8px" }}>
                {src.is_verified ? "Verified" : "Unverified"}
              </span>
              <div className="muted-copy" style={{ marginTop: "6px" }}>
                {src.claim_supported}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted-copy">No external sources logged.</p>
      )}

      {uncertainties.length > 0 ? (
        <div className="alert-banner warn">
          <span className="material-symbols-rounded" aria-hidden="true">
            warning
          </span>
          <div>
            {uncertainties.map((item, idx) => (
              <div key={idx}>{item}</div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
