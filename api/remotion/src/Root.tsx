import { Composition } from "remotion";
import { ShareClip, shareClipSchema, defaultProps } from "./ShareClip";

const FPS = 30;

const DIMS = {
  "16:9": { width: 1920, height: 1080 },
  "9:16": { width: 1080, height: 1920 },
  "1:1": { width: 1080, height: 1080 },
} as const;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {(["16:9", "9:16", "1:1"] as const).map((aspect) => {
        const id = `ShareClip_${aspect.replace(":", "x")}`;
        const { width, height } = DIMS[aspect];
        return (
          <Composition
            key={id}
            id={id}
            component={ShareClip}
            durationInFrames={FPS * 10}
            fps={FPS}
            width={width}
            height={height}
            schema={shareClipSchema}
            defaultProps={{ ...defaultProps, aspect }}
            calculateMetadata={({ props }) => ({
              durationInFrames: props.durationInFrames,
            })}
          />
        );
      })}
    </>
  );
};
