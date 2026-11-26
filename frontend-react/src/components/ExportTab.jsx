function downloadBlob(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function buildPlainTextExport(deliverable) {
  const s = deliverable.script;
  const inp = deliverable.input_data;
  const lines = [
    `Topic: ${inp.topic}`,
    `Platform: ${inp.platform} | Duration: ${inp.duration}s | Language: ${inp.tone}`,
    `Words: ${s.word_count}`,
    "",
    `[Hook]\n${s.hook}`,
    "",
    `[Context]\n${s.context}`,
    "",
    `[Body]\n${(s.body_points || []).join("\n")}`,
    "",
    `[Engagement]\n${s.engagement}`,
    "",
    `[CTA]\n${s.cta}`,
  ];
  return lines.join("\n");
}

export function buildClipFalconPayload(deliverable, clipfalconHandoff) {
  if (clipfalconHandoff) {
    return clipfalconHandoff;
  }
  const s = deliverable.script;
  const inp = deliverable.input_data;
  return {
    deliverable_id: deliverable.deliverable_id,
    client_id: deliverable.client_id || inp.client_id,
    topic: inp.topic,
    platform: inp.platform,
    target_duration_seconds: inp.duration,
    language_mode: inp.tone,
    expected_word_count: s.word_count,
    selected_hook: s.hook,
    segments: {
      hook: s.hook,
      context: s.context,
      body_points: s.body_points,
      engagement: s.engagement,
      cta: s.cta,
    },
    on_screen_texts: s.on_screen_texts,
  };
}

export function ExportTab({ deliverable, markdown, clipfalconHandoff }) {
  const duration = deliverable.input_data.duration;

  return (
    <div>
      <div className="grid-4">
        <button
          type="button"
          className="btn-secondary"
          onClick={() => downloadBlob(buildPlainTextExport(deliverable), `scriptfalcon_${duration}s.txt`, "text/plain")}
        >
          <span className="material-symbols-rounded" aria-hidden="true">
            article
          </span>
          <span>Download TXT</span>
        </button>

        <button
          type="button"
          className="btn-secondary"
          onClick={() => downloadBlob(markdown, `scriptfalcon_${duration}s.md`, "text/markdown")}
        >
          <span className="material-symbols-rounded" aria-hidden="true">
            description
          </span>
          <span>Download Markdown</span>
        </button>

        <button
          type="button"
          className="btn-secondary"
          onClick={() =>
            downloadBlob(JSON.stringify(deliverable, null, 2), `scriptfalcon_${duration}s.json`, "application/json")
          }
        >
          <span className="material-symbols-rounded" aria-hidden="true">
            data_object
          </span>
          <span>Download State JSON</span>
        </button>

        <button
          type="button"
          className="btn-secondary"
          onClick={() =>
            downloadBlob(
              JSON.stringify(buildClipFalconPayload(deliverable, clipfalconHandoff), null, 2),
              `clipfalcon_handoff_${duration}s.json`,
              "application/json"
            )
          }
        >
          <span className="material-symbols-rounded" aria-hidden="true">
            movie
          </span>
          <span>ClipFalcon Payload</span>
        </button>
      </div>

      <h3 className="section-title">Raw Markdown</h3>
      <pre className="code-pre">{markdown}</pre>
    </div>
  );
}
