import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

export const ProgressBar: React.FC<{ aspect: string }> = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const progress = Math.min(1, frame / Math.max(1, durationInFrames - 1));

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          height: 3,
          background: "rgba(255,255,255,0.15)",
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            width: `${progress * 100}%`,
            background: "rgba(255,255,255,0.9)",
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
