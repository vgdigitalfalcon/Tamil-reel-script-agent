import React from "react";

export function ModulatedText({ text }) {
  const raw = String(text ?? "");
  if (!raw) return null;
  const parts = raw.split(/(\[[^\]]+\])/g);
  return (
    <>
      {parts.map((part, idx) => {
        if (!part) return null;
        if (part.startsWith("[") && part.endsWith("]")) {
          return (
            <span key={idx} className="mod-cue">
              {part.slice(1, -1)}
            </span>
          );
        }
        return <React.Fragment key={idx}>{part}</React.Fragment>;
      })}
    </>
  );
}
