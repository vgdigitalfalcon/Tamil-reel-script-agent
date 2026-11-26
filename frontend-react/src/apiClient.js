import { formatApiErrorPayload } from "./constants.js";

function defaultBootstrapContext() {
  return {
    authenticated: true,
    viaPhp: false,
    apiBase: "",
    csrfToken: "",
    user: null,
    defaultClientId: "vg_demo_clinic",
    defaultMode: "standalone",
  };
}

export function readBootstrapContext() {
  const el = typeof document !== "undefined" ? document.getElementById("sf-bootstrap") : null;
  if (!el || !el.textContent) {
    return defaultBootstrapContext();
  }
  try {
    const parsed = JSON.parse(el.textContent);
    return {
      authenticated: Boolean(parsed.authenticated),
      viaPhp: Boolean(parsed.viaPhp),
      apiBase: parsed.apiBase || "api-proxy.php",
      csrfToken: parsed.csrfToken || "",
      user: parsed.user || null,
      defaultClientId: parsed.defaultClientId || "vg_demo_clinic",
      defaultMode: parsed.defaultMode === "crm" ? "crm" : "standalone",
    };
  } catch {
    return defaultBootstrapContext();
  }
}

export class ApiRequestError extends Error {
  constructor(formatted) {
    super(formatted.message);
    this.status = formatted.status;
    this.title = formatted.title;
    this.details = formatted.details || [];
    this.variant = formatted.variant || "error";
  }
}

export function buildApiUrl(endpoint, bootstrap) {
  if (bootstrap?.viaPhp) {
    const sep = bootstrap.apiBase.includes("?") ? "&" : "?";
    return `${bootstrap.apiBase}${sep}endpoint=${encodeURIComponent(endpoint)}`;
  }
  return endpoint;
}

export async function apiRequest(endpoint, options = {}, bootstrap = readBootstrapContext()) {
  const url = buildApiUrl(endpoint, bootstrap);
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(bootstrap?.csrfToken ? { "X-CSRF-Token": bootstrap.csrfToken } : {}),
    ...options.headers,
  };

  const response = await fetch(url, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: bootstrap?.viaPhp ? "same-origin" : "omit",
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : { detail: await response.text().catch(() => "Unexpected server response.") };

  if (!response.ok) {
    throw new ApiRequestError(formatApiErrorPayload(response.status, payload));
  }
  return payload;
}
