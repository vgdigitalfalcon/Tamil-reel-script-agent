export function AlertBanner({ error }) {
  if (!error) return null;
  const isWarn = error.variant === "warn";
  const details = Array.isArray(error.details) ? error.details.filter((item) => item && item !== error.message) : [];

  return (
    <div className={`alert-banner${isWarn ? " warn" : ""}`} role="alert">
      <span className="material-symbols-rounded" aria-hidden="true">
        {isWarn ? "warning" : "error"}
      </span>
      <div>
        {error.title ? <div className="alert-title">{error.title}</div> : null}
        <div>{error.message}</div>
        {details.length > 0 ? (
          <ul className="clean-list">
            {details.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
