import { AbsoluteFill, staticFile, Img } from "remotion";

const SIZE_BY_ASPECT: Record<string, { width: number; margin: string }> = {
  "16:9": { width: 140, margin: "0 40px 32px 0" },
  "9:16": { width: 200, margin: "0 0 48px 0" },
  "1:1": { width: 160, margin: "0 40px 32px 0" },
};

export const Logo: React.FC<{ aspect: string }> = ({ aspect }) => {
  const cfg = SIZE_BY_ASPECT[aspect] ?? SIZE_BY_ASPECT["16:9"];
  const centerHorizontally = aspect === "9:16";

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: centerHorizontally ? "center" : "flex-end",
        pointerEvents: "none",
      }}
    >
      <Img
        src={staticFile("logo.svg")}
        style={{
          width: cfg.width,
          margin: cfg.margin,
          opacity: 0.85,
          filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.5))",
        }}
      />
    </AbsoluteFill>
  );
};
