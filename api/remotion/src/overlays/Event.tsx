import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

const FADE = 12;
const FONT_BY_ASPECT: Record<string, number> = {
  "16:9": 52,
  "9:16": 72,
  "1:1": 58,
};

export const Event: React.FC<{
  text: string;
  startFrame: number;
  endFrame: number;
  aspect: string;
}> = ({ text, startFrame, endFrame, aspect }) => {
  const frame = useCurrentFrame();
  const fontSize = FONT_BY_ASPECT[aspect] ?? 52;

  const opacity = interpolate(
    frame,
    [startFrame, startFrame + FADE, endFrame - FADE, endFrame],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const barOpacity = opacity * 0.4;

  return (
    <>
      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          alignItems: "flex-start",
          padding: "0 4% 10% 4%",
          opacity,
        }}
      >
        <div
          style={{
            fontFamily: "Inter, system-ui, sans-serif",
            fontSize,
            fontWeight: 600,
            color: "#fff",
            textShadow: "0 2px 10px rgba(0,0,0,0.8)",
            letterSpacing: "-0.01em",
          }}
        >
          {text}
        </div>
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          alignItems: "stretch",
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            height: 6,
            background: `linear-gradient(90deg, rgba(255,255,255,${barOpacity}) 0%, rgba(180,200,255,${barOpacity}) 100%)`,
            marginBottom: "6%",
          }}
        />
      </AbsoluteFill>
    </>
  );
};
