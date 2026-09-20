import type { FC } from "react";
import {
  AbsoluteFill,
  Easing,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

export const SIGNAL_WEAVE_FPS = 30;

type FilmProps = { source: string };
type Scene = { start: number; end: number; label: string; focus: [number, number] };

const scenes: Scene[] = [
  { start: 0, end: 156, label: "SCHEDULED RUN", focus: [420, 350] },
  { start: 156, end: 246, label: "HUMAN CONTEXT", focus: [640, 365] },
  { start: 246, end: 375, label: "EVIDENCE GRAPH", focus: [640, 390] },
  { start: 375, end: 495, label: "BUNDLE TO AGENT", focus: [650, 375] },
  { start: 495, end: 660, label: "PUSH + ACK", focus: [650, 390] },
];

const ease = Easing.bezier(0.22, 0.85, 0.2, 1);
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

function sceneForFrame(frame: number) {
  return scenes.find((scene) => frame >= scene.start && frame < scene.end) ?? scenes[scenes.length - 1];
}

function localProgress(frame: number, start: number, end: number) {
  return interpolate(frame, [start, end], [0, 1], clamp);
}

function entering(frame: number, start: number, duration = 24) {
  return interpolate(frame, [start, start + duration], [0, 1], { ...clamp, easing: ease });
}

function cameraForFrame(frame: number) {
  const scene = sceneForFrame(frame);
  const progress = localProgress(frame, scene.start, scene.end);

  if (scene.start === 0) {
    const focus = localProgress(frame, 30, 76);
    const settle = localProgress(frame, 94, 156);
    return {
      scale: interpolate(focus, [0, 1], [1.015, 1.34], clamp) * interpolate(settle, [0, 1], [1, 0.78], clamp),
      x: interpolate(focus, [0, 1], [0, 84], clamp),
      y: interpolate(focus, [0, 1], [0, -102], clamp),
      rotateY: 0,
      rotateZ: interpolate(frame, [0, 40], [-0.35, 0], clamp),
    };
  }

  const flipIn = entering(frame, scene.start, 25);
  const flipOut = interpolate(frame, [scene.end - 22, scene.end], [0, 1], clamp);
  const focusScale = scene.start === 246
    ? interpolate(progress, [0, 0.45, 1], [1.04, 1.15, 1.03], clamp)
    : scene.start === 375
      ? interpolate(progress, [0, 0.45, 1], [1.04, 1.12, 1.06], clamp)
      : interpolate(progress, [0, 0.4, 1], [1.02, 1.1, 1.045], clamp);

  return {
    scale: focusScale,
    x: scene.start === 246 ? interpolate(progress, [0, 0.6, 1], [0, -34, 0], clamp) : 0,
    y: scene.start === 495 ? interpolate(progress, [0, 0.5, 1], [20, -8, 0], clamp) : 0,
    rotateY: scene.start % 2 === 0
      ? interpolate(flipIn, [0, 1], [88, 0], clamp) + interpolate(flipOut, [0, 1], [0, -24], clamp)
      : interpolate(flipIn, [0, 1], [-88, 0], clamp) + interpolate(flipOut, [0, 1], [0, 24], clamp),
    rotateZ: interpolate(progress, [0, 0.18, 1], [scene.start === 375 ? -0.6 : 0.25, 0, 0], clamp),
  };
}

const TransitionWash: FC<{ frame: number }> = ({ frame }) => {
  const scene = sceneForFrame(frame);
  const active = scene.start > 0 && frame < scene.start + 24;
  if (!active) return null;
  const opacity = Math.sin(localProgress(frame, scene.start, scene.start + 24) * Math.PI) * 0.38;
  return (
    <div
      style={{
        position: "absolute", inset: 0,
        background: "linear-gradient(115deg, rgba(255,255,255,.96), rgba(234,239,255,.72) 45%, rgba(255,255,255,.96))",
        opacity, mixBlendMode: "screen", pointerEvents: "none",
      }}
    />
  );
};

export const SignalWeaveFilm: FC<FilmProps> = ({ source }) => {
  const frame = useCurrentFrame();
  const scene = sceneForFrame(frame);
  const camera = cameraForFrame(frame);
  const shellIn = entering(frame, 0, 30);
  const shellOut = interpolate(frame, [648, 660], [1, 0], clamp);

  return (
    <AbsoluteFill style={{ background: "#f6f8fb", overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          background: "radial-gradient(circle at 52% 42%, rgba(99,102,241,.075), transparent 34%), linear-gradient(135deg,#f9fafb,#eef2f7)",
          opacity: shellIn * shellOut,
        }}
      />
      <div
        style={{
          position: "absolute", inset: 18, overflow: "hidden", borderRadius: 30,
          border: "1px solid rgba(15,23,42,.12)", background: "#f8fafc",
          boxShadow: "0 28px 70px rgba(15,23,42,.16), 0 2px 8px rgba(15,23,42,.06)",
          perspective: 1500, opacity: shellIn * shellOut,
        }}
      >
        <div
          style={{
            position: "absolute", inset: 0, transformOrigin: "50% 50%",
            transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale}) rotateY(${camera.rotateY}deg) rotateZ(${camera.rotateZ}deg)`,
            willChange: "transform",
          }}
        >
          <OffthreadVideo
            src={staticFile(source)} muted startFrom={0} endAt={22 * SIGNAL_WEAVE_FPS}
            style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          />
        </div>
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(255,255,255,.06), transparent 26%, rgba(15,23,42,.035))", pointerEvents: "none" }} />
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 56, background: "linear-gradient(180deg, rgba(248,250,252,.04), rgba(248,250,252,.98) 58%)", pointerEvents: "none" }} />
        <TransitionWash frame={frame} />
      </div>
      <div style={{ position: "absolute", left: 44, right: 44, bottom: 18, height: 2, background: "rgba(100,116,139,.16)", borderRadius: 999 }}>
        <div style={{ height: "100%", width: `${(frame / (22 * SIGNAL_WEAVE_FPS - 1)) * 100}%`, background: "linear-gradient(90deg,#12b8a6,#6366f1,#ec4a9d)", borderRadius: 999 }} />
      </div>
    </AbsoluteFill>
  );
};
