import type { FC } from "react";
import { AbsoluteFill, Easing, OffthreadVideo, interpolate, staticFile, useCurrentFrame } from "remotion";

export const SIGNAL_WEAVE_FPS = 30;

type FilmProps = { source?: string };

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const soft = Easing.bezier(0.22, 0.78, 0.2, 1);
const stageStarts = [150, 270, 405, 525];

function transitionProgress(frame: number, start: number) {
  return interpolate(frame, [start - 10, start + 10], [0, 1], { ...clamp, easing: soft });
}

const StageSheen: FC<{ frame: number }> = ({ frame }) => (
  <>
    {stageStarts.map((start) => {
      const progress = transitionProgress(frame, start);
      const opacity = Math.sin(progress * Math.PI) * 0.28;
      return (
        <div
          key={start}
          style={{
            position: "absolute",
            top: -80,
            bottom: -80,
            left: `${interpolate(progress, [0, 1], [-24, 112], clamp)}%`,
            width: 170,
            opacity,
            background: "linear-gradient(90deg, transparent, rgba(20,184,166,.2) 42%, rgba(91,97,232,.18) 58%, transparent)",
            transform: "skewX(-12deg)",
            filter: "blur(1px)",
            pointerEvents: "none",
          }}
        />
      );
    })}
  </>
);

export const SignalWeaveFilm: FC<FilmProps> = ({ source = "signalweave-page-recording.mp4" }) => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill style={{ background: "#e9eef3", overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          overflow: "hidden",
          background: "#f7f9fb",
        }}
      >
        <OffthreadVideo
          src={staticFile(source)}
          muted
          style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
        />
        <StageSheen frame={frame} />
        <div
          style={{
            position: "absolute",
            right: 0,
            bottom: 0,
            width: 170,
            height: 58,
            background: "linear-gradient(180deg, rgba(247,249,251,0), rgba(247,249,251,.9) 38%, #f7f9fb 74%)",
            pointerEvents: "none",
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
