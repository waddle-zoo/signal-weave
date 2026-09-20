import { Composition, registerRoot } from "remotion";
import { SignalWeaveFilm, SIGNAL_WEAVE_FPS } from "./SignalWeaveFilm";

export const RemotionRoot = () => {
  return (
    <Composition
      id="SignalWeaveFilm"
      component={SignalWeaveFilm}
      durationInFrames={22 * SIGNAL_WEAVE_FPS}
      fps={SIGNAL_WEAVE_FPS}
      width={1280}
      height={720}
      defaultProps={{ source: "signalweave-page-recording.mp4" }}
    />
  );
};

registerRoot(RemotionRoot);
