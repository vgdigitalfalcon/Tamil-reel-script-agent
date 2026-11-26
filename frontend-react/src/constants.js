// Context fields that silently shape every script. Kept here so the sidebar can flag
// values that differ from these and "New" can reset them.
export const DEFAULT_CONTEXT_FIELDS = {
  audience: "Small business owners & Tamil entrepreneurs",
  niche: "Business & Technology",
  referenceUrl: "",
};

export function getActiveOverrides(form) {
  const active = [];
  if ((form.audience || "").trim() !== DEFAULT_CONTEXT_FIELDS.audience) active.push("Audience");
  if ((form.niche || "").trim() !== DEFAULT_CONTEXT_FIELDS.niche) active.push("Niche");
  if ((form.referenceUrl || "").trim()) active.push("Reference URL");
  return active;
}

export const PRESETS = [
  {
    title: "Why websites fail to get leads",
    meta: "Instagram Reels · 30s · Tanglish",
    topic: "Why are businesses not getting leads from their websites?",
    platform: "Instagram Reels",
    duration: 30,
    language: "Tanglish",
    objective: "Get agency leads",
    audience: "Small business owners",
    niche: "Digital Marketing / Web Development",
  },
  {
    title: "SEO mistakes & ranking myths",
    meta: "Instagram Reels · 45s · Tanglish",
    topic: "Common SEO mistakes and ranking myths for small businesses",
    platform: "Instagram Reels",
    duration: 45,
    language: "Tanglish",
    objective: "Educate business owners on organic SEO",
    audience: "Local business owners and Tamil entrepreneurs",
    niche: "Search Engine Optimization",
  },
  {
    title: "Germany Opportunity Card guide",
    meta: "Instagram Reels · 60s · Spoken Tamil",
    topic: "Germany Opportunity Card (Chancenkarte) and job seeker visa requirements",
    platform: "Instagram Reels",
    duration: 60,
    language: "Conversational Spoken Tamil",
    objective: "Get consultation calls",
    audience: "Tamil graduates and tech professionals looking to work in Germany",
    niche: "Abroad Careers & Immigration",
  },
];

export const PLATFORMS = ["Instagram Reels", "YouTube Shorts", "LinkedIn Video"];

export const DURATIONS = [30, 45, 60];

export const LANGUAGES = [
  { value: "Tanglish", label: "Tanglish" },
  { value: "Conversational Spoken Tamil", label: "Conversational Spoken Tamil" },
  { value: "Tamil", label: "Tamil" },
  { value: "English", label: "English" },
];

export const WORD_LIMITS = {
  30: { min: 60, max: 75, label: "60–75" },
  45: { min: 95, max: 110, label: "95–110" },
  60: { min: 125, max: 145, label: "125–145" },
};

export const ENGLISH_WORD_LIMITS = {
  30: { min: 65, max: 80, label: "65–80" },
  45: { min: 100, max: 120, label: "100–120" },
  60: { min: 130, max: 155, label: "130–155" },
};

export const CLIENT_MONTHLY_BUDGET_INR = 60.0;
export const DAILY_USER_RUN_LIMIT = 25;
export const DAILY_USER_TOKEN_LIMIT = 75000;

export function getLimitsForTone(duration, tone) {
  const isEnglish = String(tone || "").trim().toLowerCase() === "english";
  const table = isEnglish ? ENGLISH_WORD_LIMITS : WORD_LIMITS;
  return table[duration] || table[30];
}

export function normalizeLanguageValue(toneOrLanguage) {
  const clean = String(toneOrLanguage || "").trim();
  if (clean.toLowerCase() === "conversational spoken tamil") {
    return "Conversational Spoken Tamil";
  }
  return LANGUAGES.some((item) => item.value === clean) ? clean : "Tanglish";
}

export function formatApiErrorPayload(status, payload) {
  if (status === 422 && payload && Array.isArray(payload.detail)) {
    const messages = payload.detail.map((err) => {
      const loc = Array.isArray(err.loc) ? err.loc.filter((part) => part !== "body").join(".") : "input";
      return loc ? `${loc}: ${err.msg}` : err.msg;
    });
    return {
      status,
      title: "Input Validation Error (HTTP 422)",
      message: messages[0] || "Please check your inputs and try again.",
      details: messages,
      variant: "error",
    };
  }

  const detailText =
    typeof payload?.detail === "string"
      ? payload.detail
      : payload?.message || `Request failed with HTTP ${status}.`;

  if (status === 429) {
    return {
      status,
      title: "Daily Teammate Limit Reached (HTTP 429)",
      message: detailText,
      details: ["Client monthly balance was not deducted. Ask an Admin to grant +10 bonus runs if urgent."],
      variant: "warn",
    };
  }

  if (status === 402) {
    return {
      status,
      title: "Client Monthly Quota Reached (HTTP 402)",
      message: detailText,
      details: ["Client bucket is paused until topped up or reset."],
      variant: "error",
    };
  }

  return {
    status,
    title: `Request Failed (HTTP ${status})`,
    message: detailText,
    details: [],
    variant: "error",
  };
}
