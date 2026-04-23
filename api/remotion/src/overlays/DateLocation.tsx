import { AbsoluteFill } from "remotion";

const FONT_BY_ASPECT: Record<string, number> = {
  "16:9": 28,
  "9:16": 40,
  "1:1": 30,
};

export const DateLocation: React.FC<{ text: string; aspect: string }> = ({
  text,
  aspect,
}) => {
  const fontSize = FONT_BY_ASPECT[aspect] ?? 28;
  return (
    <AbsoluteFill
      style={{
        padding: "3% 4%",
        justifyContent: "flex-start",
        alignItems: "flex-start",
      }}
    >
      <div
        style={{
          fontFamily: "JetBrains Mono, ui-monospace, monospace",
          fontSize,
          color: "rgba(255,255,255,0.85)",
          letterSpacing: "0.05em",
          textShadow: "0 1px 4px rgba(0,0,0,0.6)",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
