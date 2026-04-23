import { AbsoluteFill, OffthreadVideo } from "remotion";
import { z } from "zod";
import { DateLocation } from "./overlays/DateLocation";
import { Event } from "./overlays/Event";
import { Logo } from "./overlays/Logo";
import { ProgressBar } from "./overlays/ProgressBar";

export const shareClipSchema = z.object({
  source: z.string(),
  dateLocation: z.string(),
  aspect: z.enum(["16:9", "9:16", "1:1"]),
  durationInFrames: z.number().int().positive(),
  event: z
    .object({
      text: z.string(),
      startFrame: z.number().int().nonnegative(),
      endFrame: z.number().int().nonnegative(),
    })
    .nullable(),
});

export type ShareClipProps = z.infer<typeof shareClipSchema>;

export const defaultProps: ShareClipProps = {
  source: "https://files.astropolis.be/public/allsky/videos/custom/placeholder.mp4",
  dateLocation: "Oostende · 22 apr 2026 · 23:42",
  aspect: "16:9",
  durationInFrames: 600,
  event: { text: "ISS pass", startFrame: 120, endFrame: 450 },
};

export const ShareClip: React.FC<ShareClipProps> = ({
  source,
  dateLocation,
  aspect,
  event,
}) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <OffthreadVideo src={source} />
      <DateLocation text={dateLocation} aspect={aspect} />
      {event ? (
        <Event
          text={event.text}
          startFrame={event.startFrame}
          endFrame={event.endFrame}
          aspect={aspect}
        />
      ) : null}
      <Logo aspect={aspect} />
      <ProgressBar aspect={aspect} />
    </AbsoluteFill>
  );
};
