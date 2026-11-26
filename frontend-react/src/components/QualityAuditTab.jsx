export function buildAuditCriteria(qc, isEnglish) {
  return [
    ["1. Unsupported Claims", qc.unsupported_claims],
    ["2. Repetition", qc.repetition],
    ["3. Weak Call-to-Action", qc.weak_cta],
    [isEnglish ? "4. Natural Spoken English" : "4. Natural Spoken Tamil", qc.unnatural_tamil],
    ["5. Duration Fit Calibration", qc.duration_fit],
    ["6. Respectful Single-Narrator & Anti-AI Cliché", qc.respectful_and_cliche_free],
    [isEnglish ? "7. Spoken Flow & Vocal Modulation" : "7. Tamil Word Integrity & Vocal Modulation", qc.tamil_integrity_and_modulation],
  ];
}

export function QualityAuditTab({ qc, isEnglish }) {
  const criteria = buildAuditCriteria(qc, isEnglish);
  const fixes = qc?.fixes_applied || [];

  return (
    <div>
      <div className="grid-2">
        {criteria.map(([name, item]) => (
          <div key={name} className="surface-card">
            <div className="card-header">
              <strong>{name}</strong>
              <span className={`audit-badge ${item?.status === "PASS" ? "pass" : "flag"}`}>
                {item?.status || "FLAG"}
              </span>
            </div>
            <div className="muted-copy">{item?.notes}</div>
          </div>
        ))}
      </div>

      {fixes.length > 0 ? (
        <div className="surface-card" style={{ marginTop: "16px" }}>
          <div className="card-kicker">Auto-Corrections Applied</div>
          <ul className="clean-list">
            {fixes.map((fix, idx) => (
              <li key={idx}>{fix}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
