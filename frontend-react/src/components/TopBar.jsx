export function TopBar({ health, bootstrap }) {
  const connected = Boolean(health?.provider_connected);
  const providerLabel = health
    ? `Provider: ${health.active_provider} (${connected ? "connected" : "simulation"})`
    : "Provider: checking...";

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-name">ScriptFalcon</span>
        <span className="brand-sub">VG Digital Falcon</span>
      </div>

      <div className="status-row">
        <span className="pill">
          <span className={`dot ${connected ? "dot-live" : "dot-sim"}`} />
          <span>{providerLabel}</span>
        </span>
        <span className="pill">
          <span className="dot dot-live" />
          <span>7-Criteria Audit</span>
        </span>
        <span className="pill">
          <span className="dot dot-live" />
          <span>Single-Narrator Lock</span>
        </span>
        {bootstrap?.viaPhp && bootstrap?.user ? (
          <>
            <span className="pill" title={bootstrap.user.email || bootstrap.user.user_id}>
              <span className="material-symbols-rounded" aria-hidden="true">
                person
              </span>
              <span>
                {bootstrap.user.display_name || bootstrap.user.user_id} ({bootstrap.user.role})
              </span>
            </span>
            <a className="pill pill-link" href="index.php?action=logout">
              Sign out
            </a>
          </>
        ) : null}
      </div>
    </header>
  );
}
