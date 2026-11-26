const PRESETS = [
  {
    topic: "Why are businesses not getting leads from their websites?",
    platform: "Instagram Reels",
    duration: 30,
    tone: "Tanglish",
    objective: "Get agency leads",
    audience: "Small business owners",
    niche: "Digital Marketing / Web Development",
  },
  {
    topic: "Common SEO mistakes and ranking myths for small businesses",
    platform: "Instagram Reels",
    duration: 45,
    tone: "Tanglish",
    objective: "awareness",
    audience: "Local business owners and Tamil entrepreneurs",
    niche: "Search Engine Optimization",
  },
  {
    topic: "Germany Opportunity Card (Chancenkarte) and job seeker visa requirements",
    platform: "Instagram Reels",
    duration: 60,
    tone: "conversational spoken Tamil",
    objective: "awareness",
    audience: "Tamil graduates and tech professionals looking to work in Germany",
    niche: "Abroad Careers & Immigration",
  },
];

const WORD_LIMITS = {
  30: "60–75",
  45: "95–110",
  60: "125–145",
};

const ENGLISH_WORD_LIMITS = {
  30: "65–80",
  45: "100–120",
  60: "130–155",
};

function getLimitsForTone(duration, tone) {
  const table = tone === "English" ? ENGLISH_WORD_LIMITS : WORD_LIMITS;
  return table[duration] || table[30];
}

const state = {
  mode: "standalone",
  duration: 30,
  tone: "Tanglish",
  deliverable: null,
  markdown: "",
};

const $ = (id) => document.getElementById(id);

function createEl(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null && text !== "") node.textContent = String(text);
  return node;
}

function appendModulated(parent, text) {
  const raw = String(text ?? "");
  const parts = raw.split(/(\[[^\]]+\])/g);
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith("[") && part.endsWith("]")) {
      parent.appendChild(createEl("span", "mod-cue", part.slice(1, -1)));
    } else {
      parent.appendChild(document.createTextNode(part));
    }
  }
}

function setModulatedContent(container, text) {
  container.replaceChildren();
  if (text) appendModulated(container, text);
}

function showError(msg) {
  $("errorMessage").textContent = msg;
  $("errorBanner").classList.remove("hidden");
}

function clearError() {
  $("errorBanner").classList.add("hidden");
}

function setActiveGroup(selector, matchAttr, val) {
  document.querySelectorAll(selector).forEach((btn) => {
    btn.classList.toggle("active", String(btn.dataset[matchAttr]) === String(val));
  });
}

function updatePacingHint() {
  const rate = state.tone === "English" ? "~2.4 w/s" : "~2.2 w/s";
  $("pacingTargetHint").textContent = `Target: ${getLimitsForTone(state.duration, state.tone)} words (${rate})`;
}

function applyPreset(index) {
  const p = PRESETS[index];
  if (!p) return;
  $("topicInput").value = p.topic;
  $("platformSelect").value = p.platform;
  $("objectiveInput").value = p.objective;
  $("audienceInput").value = p.audience;
  $("nicheInput").value = p.niche;
  state.duration = p.duration;
  state.tone = p.tone;
  setActiveGroup("[data-duration]", "duration", p.duration);
  setActiveGroup("[data-tone]", "tone", p.tone);
  updatePacingHint();
  $("topicInput").focus();
}

function setLoading(isLoading, label = "Generating...") {
  const btn = $("generateBtn");
  btn.disabled = isLoading;
  $("generateBtnText").textContent = isLoading ? label : "Generate Script";
}

function renderAuditBadges({ passed, wordsCount, targetRange, wordsOk, duration, isEnglish, cuesCount, modelLabel, costLabel }) {
  const badges = [
    createEl("span", `audit-badge ${passed === 7 ? "pass" : "flag"}`, `Audit: ${passed}/7 Passed`),
    createEl("span", `audit-badge ${wordsOk ? "pass" : ""}`, `Words: ${wordsCount} / ${targetRange}`),
    createEl("span", "audit-badge", `Pacing: ${isEnglish ? "~2.4 w/s" : "~2.2 w/s"} · ${duration}s`),
    createEl("span", "audit-badge", `Cues: ${cuesCount}`),
    createEl("span", "audit-badge", `${modelLabel} · ${costLabel}`),
  ];
  $("auditBadges").replaceChildren(...badges);
}

function renderHookCards(hooks) {
  const cards = (hooks || []).map((h) => {
    const card = createEl("div", `surface-card ${h.is_recommended ? "card-active" : ""}`);
    const header = createEl("div", "card-header");
    header.appendChild(createEl("span", "card-kicker", h.type));
    if (h.is_recommended) header.appendChild(createEl("span", "rec-pill", "Recommended"));
    card.appendChild(header);

    const quote = createEl("div", "tp-subtext");
    quote.style.color = "#fff";
    quote.style.margin = "0";
    quote.appendChild(document.createTextNode('"'));
    appendModulated(quote, h.text);
    quote.appendChild(document.createTextNode('"'));
    card.appendChild(quote);

    if (h.reason) {
      const reason = createEl("div", "muted-copy", h.reason);
      reason.style.marginTop = "8px";
      card.appendChild(reason);
    }
    return card;
  });
  $("hookGrid").replaceChildren(...cards);
}

function renderCtaOptions(ctaOptions) {
  if (!ctaOptions || !ctaOptions.length) {
    $("ctaOptionsWrap").classList.add("hidden");
    return;
  }
  $("ctaOptionsWrap").classList.remove("hidden");
  const items = ctaOptions.map((c, idx) => {
    const li = document.createElement("li");
    const label = createEl("strong", "", `Option ${idx + 1}${c.is_recommended ? " (Recommended)" : ""}: `);
    li.appendChild(label);
    li.appendChild(document.createTextNode(c.text || ""));
    return li;
  });
  $("ctaOptionsList").replaceChildren(...items);
}

function renderResearchTab(res) {
  $("chosenAngleText").textContent = res.chosen_angle || "";
  $("angleReasonText").textContent = res.angle_reason || "";
  $("findingsList").replaceChildren(...(res.key_findings || []).map((f) => createEl("li", "", f)));
  $("painPointsList").replaceChildren(...(res.pain_points || []).map((p) => createEl("li", "", p)));

  if (res.sources && res.sources.length) {
    const sourceCards = res.sources.map((s) => {
      const card = createEl("div", "surface-card");
      card.style.marginBottom = "10px";
      const link = createEl("a", "source-link", s.title || s.url);
      link.href = s.url || "#";
      link.target = "_blank";
      link.rel = "noopener";
      card.appendChild(link);
      const chip = createEl("span", "chip", s.is_verified ? "Verified" : "Unverified");
      chip.style.marginLeft = "8px";
      card.appendChild(chip);
      const claim = createEl("div", "muted-copy", s.claim_supported);
      claim.style.marginTop = "6px";
      card.appendChild(claim);
      return card;
    });
    $("sourcesList").replaceChildren(...sourceCards);
  } else {
    $("sourcesList").replaceChildren(createEl("p", "muted-copy", "No external sources logged."));
  }

  if (res.uncertainties && res.uncertainties.length) {
    $("uncertaintiesBox").classList.remove("hidden");
    $("uncertaintiesText").replaceChildren(...res.uncertainties.map((u) => createEl("div", "", u)));
  } else {
    $("uncertaintiesBox").classList.add("hidden");
  }
}

function renderAuditTab(checks, fixesApplied) {
  const cards = checks.map(([name, item]) => {
    const card = createEl("div", "surface-card");
    const header = createEl("div", "card-header");
    header.appendChild(createEl("strong", "", name));
    header.appendChild(createEl("span", `audit-badge ${item.status === "PASS" ? "pass" : "flag"}`, item.status));
    card.appendChild(header);
    card.appendChild(createEl("div", "muted-copy", item.notes));
    return card;
  });
  $("auditGrid").replaceChildren(...cards);

  if (fixesApplied && fixesApplied.length) {
    $("fixesBox").classList.remove("hidden");
    $("fixesList").replaceChildren(...fixesApplied.map((f) => createEl("li", "", f)));
  } else {
    $("fixesBox").classList.add("hidden");
  }
}

function renderDeliverable(deliverable, markdown) {
  state.deliverable = deliverable;
  state.markdown = markdown;

  $("emptyState").classList.add("hidden");
  $("resultState").classList.remove("hidden");

  const inp = deliverable.input_data;
  const script = deliverable.script;
  const qc = deliverable.quality_check;
  const isEnglish = inp.tone === "English";
  const checks = [
    ["1. Unsupported Claims", qc.unsupported_claims],
    ["2. Repetition", qc.repetition],
    ["3. Weak Call-to-Action", qc.weak_cta],
    [isEnglish ? "4. Natural Spoken English" : "4. Natural Spoken Tamil", qc.unnatural_tamil],
    ["5. Duration Fit Calibration", qc.duration_fit],
    ["6. Respectful Single-Narrator & Anti-AI Cliché", qc.respectful_and_cliche_free],
    [isEnglish ? "7. Spoken Flow & Vocal Modulation" : "7. Tamil Word Integrity & Vocal Modulation", qc.tamil_integrity_and_modulation],
  ];
  const passed = checks.filter(([, item]) => item && item.status === "PASS").length;
  const targetRange = getLimitsForTone(inp.duration, inp.tone);
  const [minW, maxW] = targetRange.split("–").map(Number);
  const cuesCount = (`${script.hook} ${script.context} ${(script.body_points || []).join(" ")} ${script.engagement} ${script.cta}`.match(/\[[^\]]+\]/g) || []).length;
  const costLabel = deliverable.cost_inr ? `₹${Number(deliverable.cost_inr).toFixed(4)}` : "₹0.00";

  renderAuditBadges({
    passed,
    wordsCount: script.word_count,
    targetRange,
    wordsOk: script.word_count >= minW && script.word_count <= maxW,
    duration: inp.duration,
    isEnglish,
    cuesCount,
    modelLabel: deliverable.model_used || "simulation",
    costLabel,
  });
  setModulatedContent($("tpHook"), script.hook);
  setModulatedContent($("tpContext"), script.context);
  $("tpBody").replaceChildren(...(script.body_points || []).map((pt) => {
    const row = document.createElement("div");
    appendModulated(row, pt);
    return row;
  }));
  setModulatedContent($("tpEngagement"), script.engagement);
  setModulatedContent($("tpCta"), script.cta);

  renderHookCards(script.hooks);
  $("regenCtaObjective").value = inp.objective || "";
  renderCtaOptions(script.cta_options);
  $("onScreenWrap").replaceChildren(...(script.on_screen_texts || []).map((ost) => createEl("span", "chip", ost)));
  $("captionText").textContent = script.caption || "";
  $("hashtagsText").textContent = (script.hashtags || []).join(" ");

  renderResearchTab(deliverable.research);
  renderAuditTab(checks, qc.fixes_applied);
  $("rawMarkdownPre").textContent = markdown;
}

async function generateScript() {
  clearError();
  const topic = $("topicInput").value.trim();
  if (!topic) {
    showError("Enter a video topic before generating.");
    return;
  }

  setLoading(true, "Generating...");
  try {
    let resp;
    if (state.mode === "crm") {
      const token = $("crmTokenInput").value.trim();
      resp = await fetch("/api/v1/script-falcon/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          client_id: $("clientIdInput").value.trim(),
          topic,
          duration: state.duration,
          tone: state.tone,
          objective: $("objectiveInput").value.trim() || "awareness",
          platform: $("platformSelect").value,
          audience: $("audienceInput").value.trim() || null,
          niche: $("nicheInput").value.trim() || null,
          reference_url: $("refUrlInput").value.trim() || null,
        }),
      });
    } else {
      resp = await fetch("/api/v1/scripts/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic,
          duration: state.duration,
          tone: state.tone,
          objective: $("objectiveInput").value.trim() || "awareness",
          platform: $("platformSelect").value,
          audience: $("audienceInput").value.trim() || null,
          niche: $("nicheInput").value.trim() || null,
          reference_url: $("refUrlInput").value.trim() || null,
          mode: "full_script",
        }),
      });
    }
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Generation failed.");
    renderDeliverable(data.deliverable, data.markdown);
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

async function regeneratePart(kind) {
  if (!state.deliverable) return;
  clearError();
  const endpoint = kind === "hook" ? "/api/v1/scripts/regenerate-hook" : "/api/v1/scripts/regenerate-cta";
  const body =
    kind === "hook"
      ? { deliverable: state.deliverable }
      : { deliverable: state.deliverable, new_objective: $("regenCtaObjective").value.trim() || null };

  setLoading(true, kind === "hook" ? "Refreshing hooks..." : "Refreshing CTA...");
  try {
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Regeneration failed.");
    renderDeliverable(data.deliverable, data.markdown);
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
}

function downloadFile(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function createRecentRow(item) {
  const row = createEl("div", "recent-row");
  const info = document.createElement("div");
  info.appendChild(createEl("div", "recent-title", item.topic));
  info.appendChild(createEl("div", "recent-meta", `${item.platform} · ${item.duration}s · ${item.tone} · ${item.word_count} words`));

  const openBtn = createEl("button", "btn-secondary recent-open-btn");
  openBtn.type = "button";
  openBtn.appendChild(createEl("span", "material-symbols-rounded", "open_in_new"));
  openBtn.appendChild(createEl("span", "", "Open"));
  openBtn.addEventListener("click", async () => {
    const resp = await fetch(`/api/v1/scripts/recent/${encodeURIComponent(item.stem)}`);
    if (!resp.ok) return;
    const payload = await resp.json();
    renderDeliverable(payload.deliverable, payload.markdown);
  });

  row.appendChild(info);
  row.appendChild(openBtn);
  return row;
}

async function loadHealthAndRecent() {
  try {
    const hResp = await fetch("/api/v1/health");
    if (hResp.ok) {
      const h = await hResp.json();
      const connected = Boolean(h.provider_connected);
      $("providerDot").className = `dot ${connected ? "dot-live" : "dot-sim"}`;
      $("providerLabel").textContent = `Provider: ${h.active_provider} (${connected ? "connected" : "simulation"})`;
    }
  } catch (err) {
    console.error("Health check unavailable:", err);
  }

  try {
    const rResp = await fetch("/api/v1/scripts/recent?limit=4");
    if (!rResp.ok) return;
    const data = await rResp.json();
    if (!data.items || !data.items.length) return;
    $("recentSection").classList.remove("hidden");
    $("recentList").replaceChildren(...data.items.map(createRecentRow));
  } catch (err) {
    console.error("Recent scripts unavailable:", err);
  }
}

// Event bindings
document.querySelectorAll("[data-mode]").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.mode = btn.dataset.mode;
    setActiveGroup("[data-mode]", "mode", state.mode);
    $("crmFields").classList.toggle("hidden", state.mode !== "crm");
  });
});

document.querySelectorAll("[data-duration]").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.duration = Number(btn.dataset.duration);
    setActiveGroup("[data-duration]", "duration", state.duration);
    updatePacingHint();
  });
});

document.querySelectorAll("[data-tone]").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.tone = btn.dataset.tone;
    setActiveGroup("[data-tone]", "tone", state.tone);
    updatePacingHint();
  });
});

document.querySelectorAll(".preset-card").forEach((card) => {
  card.addEventListener("click", () => applyPreset(Number(card.dataset.preset)));
});

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${target}`));
  });
});

$("generateBtn").addEventListener("click", generateScript);
$("regenHooksBtn").addEventListener("click", () => regeneratePart("hook"));
$("regenCtaBtn").addEventListener("click", () => regeneratePart("cta"));

$("backBtn").addEventListener("click", () => {
  $("resultState").classList.add("hidden");
  $("emptyState").classList.remove("hidden");
});

$("copyScriptBtn").addEventListener("click", async () => {
  if (!state.deliverable) return;
  const s = state.deliverable.script;
  const text = [
    `[Hook] ${s.hook}`,
    `[Context] ${s.context}`,
    `[Body]\n${(s.body_points || []).map((p) => `- ${p}`).join("\n")}`,
    `[Engagement] ${s.engagement}`,
    `[CTA] ${s.cta}`,
  ].join("\n\n");
  await navigator.clipboard.writeText(text);
  $("copyBtnLabel").textContent = "Copied";
  setTimeout(() => {
    $("copyBtnLabel").textContent = "Copy";
  }, 1500);
});

$("dlMarkdownBtn").addEventListener("click", () => {
  if (!state.deliverable) return;
  downloadFile(state.markdown, `scriptfalcon_${state.deliverable.input_data.duration}s.md`, "text/markdown");
});

$("dlJsonBtn").addEventListener("click", () => {
  if (!state.deliverable) return;
  downloadFile(JSON.stringify(state.deliverable, null, 2), `scriptfalcon_${state.deliverable.input_data.duration}s.json`, "application/json");
});

$("dlClipFalconBtn").addEventListener("click", () => {
  if (!state.deliverable) return;
  const d = state.deliverable;
  const payload = {
    deliverable_id: d.deliverable_id,
    client_id: d.client_id,
    topic: d.input_data.topic,
    platform: d.input_data.platform,
    target_duration_seconds: d.input_data.duration,
    language_mode: d.input_data.tone,
    expected_word_count: d.script.word_count,
    selected_hook: d.script.hook,
    segments: {
      hook: d.script.hook,
      context: d.script.context,
      body_points: d.script.body_points,
      engagement: d.script.engagement,
      cta: d.script.cta,
    },
    on_screen_texts: d.script.on_screen_texts,
  };
  downloadFile(JSON.stringify(payload, null, 2), `clipfalcon_handoff_${d.input_data.duration}s.json`, "application/json");
});

loadHealthAndRecent();
