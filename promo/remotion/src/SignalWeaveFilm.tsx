import type { FC, ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";

export const SIGNAL_WEAVE_FPS = 30;

type FilmProps = { source?: string };
type Tone = "teal" | "indigo" | "pink" | "amber" | "ink";

const W = 1280;
const H = 720;
const TRANSITION = 14;
const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const smooth = Easing.bezier(0.2, 0.85, 0.2, 1);
const colors = { ink: "#0f172a", muted: "#6b7890", line: "#dbe2ea", paper: "#fbfcfe", teal: "#14b8a6", indigo: "#5b61e8", pink: "#e24f9b", amber: "#e6a43a" };
const scenes = [
  { start: 0, end: 150, number: "01" },
  { start: 150, end: 270, number: "02" },
  { start: 270, end: 405, number: "03" },
  { start: 405, end: 525, number: "04" },
  { start: 525, end: 660, number: "05" },
];

function p(frame: number, from: number, to: number, easing = smooth) {
  return interpolate(frame, [from, to], [0, 1], { ...clamp, easing });
}

function sceneVisibility(frame: number, index: number) {
  const scene = scenes[index];
  const enter = interpolate(frame, [scene.start - TRANSITION, scene.start + TRANSITION], [0, 1], clamp);
  const direction = index % 2 === 0 ? 1 : -1;
  const visible = frame >= scene.start - TRANSITION && frame < scene.end + TRANSITION;
  const reveal = interpolate(enter, [0, 1], [100, 0], clamp);
  return {
    opacity: visible ? 1 : 0,
    clipPath: index === 0 ? "inset(0 0 0 0)" : direction > 0 ? `inset(0 ${reveal}% 0 0)` : `inset(0 0 0 ${reveal}%)`,
    transform: `translate3d(${interpolate(enter, [0, 1], [direction * 52, 0], clamp)}px, ${interpolate(enter, [0, 1], [index === 0 ? 18 : -8, 0], clamp)}px, 0) rotateZ(${interpolate(enter, [0, 1], [direction * 1.1, 0], clamp)}deg) scale(${interpolate(enter, [0, 1], [.99, 1], clamp)})`,
  };
}

const Mark: FC<{ size?: number }> = ({ size = 28 }) => (
  <svg width={size * 1.55} height={size} viewBox="0 0 44 28" fill="none" aria-label="SignalWeave">
    <path d="M2 14C6 3 12 3 18 14S30 25 36 14 42 3 43 6" stroke={colors.teal} strokeWidth="5" strokeLinecap="round" />
    <path d="M2 14C6 25 12 25 18 14S30 3 36 14 42 25 43 22" stroke={colors.pink} strokeWidth="5" strokeLinecap="round" />
    <circle cx="3" cy="14" r="3.5" fill={colors.ink} /><circle cx="41" cy="14" r="3.5" fill={colors.ink} />
  </svg>
);

const Brand: FC = () => <div style={{ display: "flex", alignItems: "center", gap: 10 }}><Mark size={25} /><div style={{ fontSize: 16, lineHeight: 1, fontWeight: 760, letterSpacing: "-.04em", color: colors.ink }}>SignalWeave</div></div>;
const Kicker: FC<{ children: ReactNode; tone?: Tone }> = ({ children, tone = "indigo" }) => <div style={{ color: colors[tone], fontWeight: 800, fontSize: 11, letterSpacing: ".18em", textTransform: "uppercase" }}>{children}</div>;
const Dot: FC<{ tone?: Tone; size?: number }> = ({ tone = "indigo", size = 9 }) => <span style={{ display: "inline-block", width: size, height: size, borderRadius: "50%", background: colors[tone], boxShadow: `0 0 0 5px ${colors[tone]}18` }} />;
const Pill: FC<{ children: ReactNode; tone?: Tone; dark?: boolean }> = ({ children, tone = "indigo", dark = false }) => <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "9px 13px", borderRadius: 999, border: `1px solid ${dark ? "rgba(255,255,255,.14)" : colors.line}`, background: dark ? "rgba(15,23,42,.88)" : "rgba(255,255,255,.72)", color: dark ? "#fff" : colors.ink, fontSize: 12, fontWeight: 700 }}><Dot tone={tone} size={6} />{children}</div>;

const Frame: FC<{ index: number; frame: number; children: ReactNode }> = ({ index, frame, children }) => {
  const motion = sceneVisibility(frame, index);
  return <div style={{ position: "absolute", inset: 0, opacity: motion.opacity, clipPath: motion.clipPath, transform: motion.transform, pointerEvents: "none", zIndex: index + 1 }}><div style={{ position: "absolute", inset: 30, borderRadius: 30, overflow: "hidden", background: colors.paper, border: "1px solid rgba(15,23,42,.1)", boxShadow: "0 34px 90px rgba(15,23,42,.14)" }}><div style={{ position: "absolute", inset: 0, background: "radial-gradient(circle at 10% 8%, rgba(20,184,166,.08), transparent 29%), radial-gradient(circle at 91% 88%, rgba(91,97,232,.1), transparent 32%)" }} /><div style={{ position: "absolute", top: 32, left: 44, right: 44, display: "flex", alignItems: "center", justifyContent: "space-between" }}><Brand /><div style={{ display: "flex", alignItems: "center", gap: 16 }}><div style={{ color: colors.muted, fontSize: 11, letterSpacing: ".16em", fontWeight: 700 }}>PUSHED ANALYTICS</div><div style={{ color: colors.muted, fontSize: 12, fontVariantNumeric: "tabular-nums" }}>{scenes[index].number} / 05</div></div></div><div style={{ position: "absolute", left: 44, top: 94, right: 44, height: 1, background: colors.line }} />{children}</div></div>;
};

const QueryScene: FC<{ frame: number }> = ({ frame }) => {
  const start = scenes[0].start;
  const within = p(frame, start, scenes[0].end);
  const typing = p(frame, start + 26, start + 87);
  const text = "What changed in growth health — and why?";
  const chars = Math.round(interpolate(typing, [0, 1], [0, text.length], clamp));
  const cardIn = p(frame, start + 8, start + 26);
  const chips = p(frame, start + 90, start + 116);
  return <Frame index={0} frame={frame}><div style={{ position: "absolute", left: 86, top: 150, width: 820 }}><Kicker tone="teal">Growth Monitoring Agent</Kicker><div style={{ marginTop: 24, color: colors.ink, fontSize: 52, lineHeight: 1.02, letterSpacing: "-.065em", fontWeight: 760, maxWidth: 760 }}>A question becomes a run.</div><div style={{ marginTop: 42, opacity: cardIn, transform: `translateY(${interpolate(cardIn, [0, 1], [25, 0], clamp)}px)`, width: 780, padding: 25, borderRadius: 20, background: "rgba(255,255,255,.88)", border: `1px solid ${colors.line}`, boxShadow: "0 20px 54px rgba(15,23,42,.1)" }}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Kicker>Agent query</Kicker><Pill tone="teal">scheduled · 07:00</Pill></div><div style={{ marginTop: 26, minHeight: 66, color: colors.ink, fontSize: 31, letterSpacing: "-.045em", fontWeight: 680 }}>{text.slice(0, chars)}<span style={{ display: "inline-block", width: 2, height: 29, verticalAlign: -3, marginLeft: 3, background: colors.indigo, opacity: typing < 1 ? 1 : .35 }} /></div><div style={{ display: "flex", gap: 9, marginTop: 20, opacity: chips }}><Pill tone="indigo">card</Pill><Pill tone="amber">dashboards</Pill><Pill tone="teal">SQL</Pill></div></div></div><div style={{ position: "absolute", right: 86, bottom: 90, opacity: p(frame, start + 100, start + 126), transform: `translateY(${interpolate(p(frame, start + 100, start + 126), [0, 1], [18, 0], clamp)}px)` }}><div style={{ display: "flex", alignItems: "center", gap: 12, color: colors.muted, fontSize: 12, fontWeight: 700 }}><Dot tone="teal" />human intent, already loaded</div></div><div style={{ position: "absolute", left: 88, right: 88, bottom: 48, height: 3, borderRadius: 999, background: colors.line }}><div style={{ width: `${within * 100}%`, height: "100%", borderRadius: 999, background: `linear-gradient(90deg, ${colors.teal}, ${colors.indigo})` }} /></div></Frame>;
};

const JudgmentScene: FC<{ frame: number }> = ({ frame }) => {
  const start = scenes[1].start;
  const within = p(frame, start, scenes[1].end);
  const reveal = p(frame, start - 8, start + 12);
  const line = p(frame, start + 8, start + 26);
  const verdict = p(frame, start + 18, start + 36);
  const bars = [{ label: "notify", value: .91, tone: "indigo" as Tone }, { label: "review", value: .07, tone: "amber" as Tone }, { label: "ignore", value: .02, tone: "ink" as Tone }];
  return <Frame index={1} frame={frame}><div style={{ position: "absolute", left: 90, top: 166, width: 420, opacity: reveal, transform: `translateX(${interpolate(reveal, [0, 1], [-28, 0], clamp)}px)` }}><Kicker tone="teal">Human context</Kicker><div style={{ marginTop: 18, padding: 24, borderRadius: 20, background: "#fff", border: `1px solid ${colors.line}`, boxShadow: "0 18px 44px rgba(15,23,42,.08)" }}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span style={{ fontWeight: 800, fontSize: 16, color: colors.ink }}>growth-health</span><span style={{ color: colors.muted, fontSize: 11, letterSpacing: ".14em" }}>CARD / V7</span></div><div style={{ marginTop: 26, display: "grid", gap: 20 }}><div><Kicker tone="indigo">Watch</Kicker><div style={{ marginTop: 6, color: colors.ink, fontSize: 16 }}>revenue + drivers</div></div><div><Kicker tone="pink">Why</Kicker><div style={{ marginTop: 6, color: colors.ink, fontSize: 16 }}>growth plan</div></div><div><Kicker tone="teal">Deliver</Kicker><div style={{ marginTop: 6, color: colors.ink, fontSize: 16 }}>evidence-backed alert</div></div></div></div></div><svg style={{ position: "absolute", inset: 0, width: W, height: H }} viewBox={`0 0 ${W} ${H}`}><path d="M 514 360 C 600 360 642 360 716 360" fill="none" stroke={colors.indigo} strokeOpacity={line * .28} strokeWidth="3" strokeDasharray="8 12" /><circle cx={interpolate(line, [0, 1], [514, 716], clamp)} cy="360" r="7" fill={colors.indigo} opacity={line} /></svg><div style={{ position: "absolute", left: 720, top: 150, width: 426, opacity: verdict, transform: `translateX(${interpolate(verdict, [0, 1], [30, 0], clamp)}px) rotate(${interpolate(verdict, [0, 1], [1, 0], clamp)}deg)`, padding: 25, borderRadius: 20, background: "rgba(255,255,255,.92)", border: "1px solid #cfd5f6", boxShadow: "0 22px 58px rgba(91,97,232,.14)" }}><div style={{ display: "flex", justifyContent: "space-between" }}><Kicker>Jev.call</Kicker><Kicker tone="teal">typed</Kicker></div><div style={{ marginTop: 20, color: colors.ink, fontWeight: 750, fontSize: 28, letterSpacing: "-.05em" }}>Judgment shape</div><div style={{ marginTop: 16, padding: 14, borderRadius: 12, background: "#f7f8fd", color: colors.indigo, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 13, lineHeight: 1.6 }}><div>verdict: <span style={{ color: colors.teal }}>"notify"</span></div><div>evidence: <span style={{ color: colors.teal }}>4 sources</span></div><div>next: <span style={{ color: colors.teal }}>"send + investigate"</span></div></div><div style={{ marginTop: 20, display: "grid", gap: 11 }}>{bars.map((bar) => <div key={bar.label} style={{ display: "grid", gridTemplateColumns: "52px 1fr 28px", gap: 10, alignItems: "center", color: colors.muted, fontSize: 11, fontWeight: 700 }}><span>{bar.label}</span><span style={{ height: 7, borderRadius: 999, background: "#edf0f4", overflow: "hidden" }}><span style={{ display: "block", width: `${interpolate(within, [0, 1], [0, bar.value * 100], clamp)}%`, height: "100%", borderRadius: 999, background: colors[bar.tone] }} /></span><span style={{ color: colors.ink, textAlign: "right" }}>{bar.value.toFixed(2).replace("0.", ".")}</span></div>)}</div></div><div style={{ position: "absolute", right: 98, bottom: 72, opacity: p(frame, start + 72, start + 94), display: "flex", alignItems: "center", gap: 10, color: colors.muted, fontSize: 12, fontWeight: 700 }}><Dot tone="indigo" />card → Jev → shape</div></Frame>;
};

type GraphNode = { x: number; y: number; label: string; tone: Tone; delay: number };
const graphNodes: GraphNode[] = [{ x: 148, y: 353, label: "CARD", tone: "indigo", delay: 0 }, { x: 640, y: 177, label: "SQL", tone: "teal", delay: 12 }, { x: 1066, y: 246, label: "SUPERSET", tone: "amber", delay: 27 }, { x: 1066, y: 360, label: "FUNNEL", tone: "teal", delay: 41 }, { x: 1066, y: 481, label: "OPS", tone: "pink", delay: 55 }];

const GraphScene: FC<{ frame: number }> = ({ frame }) => {
  const start = scenes[2].start;
  const within = p(frame, start, scenes[2].end);
  const root = p(frame, start + 8, start + 30);
  const sql = p(frame, start + 75, start + 100);
  return <Frame index={2} frame={frame}><div style={{ position: "absolute", left: 88, top: 130 }}><Kicker tone="teal">Evidence graph</Kicker><div style={{ marginTop: 12, fontSize: 38, lineHeight: 1, letterSpacing: "-.06em", fontWeight: 760, color: colors.ink }}>The right context, connected.</div></div><div style={{ position: "absolute", left: 84, top: 216, width: 1112, height: 330, borderRadius: 22, border: `1px solid ${colors.line}`, backgroundImage: "linear-gradient(rgba(91,97,232,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(91,97,232,.045) 1px, transparent 1px)", backgroundSize: "32px 32px", overflow: "hidden" }}><svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} viewBox="0 0 1112 330">{graphNodes.map((node, index) => { const targetX = node.x - 84; const targetY = node.y - 216; const startX = index === 0 ? 250 : 556; const startY = index === 0 ? 137 : 145; const reveal = p(frame, start + 20 + node.delay, start + 40 + node.delay); return <path key={node.label} d={`M ${startX} ${startY} C ${(startX + targetX) / 2} ${startY}, ${(startX + targetX) / 2} ${targetY}, ${targetX} ${targetY}`} fill="none" stroke={colors.indigo} strokeOpacity={reveal * .65} strokeWidth="5" strokeLinecap="round" strokeDasharray="8 12" strokeDashoffset={interpolate(reveal, [0, 1], [220, 0], clamp)} />; })}</svg><div style={{ position: "absolute", left: 486, top: 91, width: 140, height: 112, borderRadius: 56, background: "rgba(255,255,255,.92)", border: "1px solid #cfd5f6", boxShadow: "0 16px 38px rgba(91,97,232,.18)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity: root, transform: `scale(${interpolate(root, [0, 1], [.7, 1], clamp)})` }}><Mark size={26} /><div style={{ marginTop: 7, color: colors.indigo, fontSize: 19, fontWeight: 800, letterSpacing: "-.04em" }}>Jev</div></div>{graphNodes.map((node) => { const reveal = p(frame, start + 20 + node.delay, start + 40 + node.delay); return <div key={node.label} style={{ position: "absolute", left: node.x - 84 - 62, top: node.y - 216 - 23, width: 124, height: 46, borderRadius: 12, background: "rgba(255,255,255,.9)", border: `1px solid ${colors[node.tone]}55`, display: "flex", alignItems: "center", justifyContent: "center", color: colors[node.tone], fontSize: 11, fontWeight: 800, letterSpacing: ".12em", opacity: reveal, transform: `scale(${interpolate(reveal, [0, 1], [.75, 1], clamp)})` }}>{node.label}</div>; })}<div style={{ position: "absolute", left: 280, right: 280, bottom: 20, height: 30, padding: "0 12px", borderRadius: 9, background: "rgba(255,255,255,.88)", border: `1px solid ${colors.line}`, display: "flex", alignItems: "center", gap: 10, opacity: sql }}><Kicker tone="teal">SQL</Kicker><span style={{ color: colors.muted, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11 }}>SELECT revenue, conversion FROM trusted_sources</span></div><div style={{ position: "absolute", left: 390, top: 248, width: 12, height: 12, borderRadius: "50%", background: colors.teal, opacity: within, boxShadow: `0 0 0 9px ${colors.teal}18` }} /></div></Frame>;
};

const DecisionScene: FC<{ frame: number }> = ({ frame }) => {
  const start = scenes[3].start;
  const within = p(frame, start, scenes[3].end);
  const left = p(frame, start - 6, start + 15);
  const right = p(frame, start + 16, start + 36);
  const rows = [["revenue", "−22%", "pink" as Tone], ["conversion", "−15%", "pink" as Tone], ["support backlog", "+28%", "amber" as Tone], ["finance", "agrees", "teal" as Tone]];
  return <Frame index={3} frame={frame}><div style={{ position: "absolute", left: 88, top: 146 }}><Kicker tone="pink">Jev result</Kicker><div style={{ marginTop: 15, fontSize: 48, lineHeight: 1, letterSpacing: "-.07em", fontWeight: 760, color: colors.ink }}>Evidence → action.</div></div><div style={{ position: "absolute", left: 88, top: 272, width: 638, padding: 24, borderRadius: 20, background: "rgba(255,255,255,.9)", border: `1px solid ${colors.line}`, boxShadow: "0 20px 52px rgba(15,23,42,.1)", opacity: left, transform: `translateX(${interpolate(left, [0, 1], [-24, 0], clamp)}px)` }}><div style={{ display: "flex", justifyContent: "space-between", paddingBottom: 16, color: colors.muted, fontSize: 11, fontWeight: 800, letterSpacing: ".14em" }}><span>GROWTH-HEALTH / RESULT</span><span>WEIGHTED</span></div>{rows.map(([label, value, tone], index) => { const rp = p(frame, start + 25 + index * 8, start + 39 + index * 8); return <div key={label} style={{ height: 48, borderTop: `1px solid ${colors.line}`, display: "flex", alignItems: "center", justifyContent: "space-between", opacity: rp, transform: `translateX(${interpolate(rp, [0, 1], [-12, 0], clamp)}px)` }}><span style={{ display: "flex", alignItems: "center", gap: 10, color: colors.ink, fontSize: 15, fontWeight: 650 }}><Dot tone={tone} size={7} />{label}</span><span style={{ color: tone === "teal" ? colors.ink : colors[tone], fontSize: 15, fontWeight: 800 }}>{value}</span></div>; })}<div style={{ marginTop: 10, padding: "11px 14px", borderRadius: 10, background: "#effaf7", display: "flex", justifyContent: "space-between", color: colors.teal, fontSize: 12, fontWeight: 800 }}><span>confidence</span><span>{interpolate(within, [0, 1], [0, .91], clamp).toFixed(2)} · notify</span></div></div><div style={{ position: "absolute", right: 88, top: 330, width: 355, opacity: right, transform: `translateX(${interpolate(right, [0, 1], [28, 0], clamp)}px) rotate(${interpolate(right, [0, 1], [1, 0], clamp)}deg)`, padding: 25, borderRadius: 20, background: "#101b31", color: "#fff", boxShadow: "0 24px 60px rgba(15,23,42,.2)" }}><Kicker tone="teal">Typed result</Kicker><div style={{ marginTop: 18, fontSize: 25, lineHeight: 1.05, letterSpacing: "-.05em", fontWeight: 730 }}>send to growth leadership</div><div style={{ marginTop: 30, display: "flex", alignItems: "center", justifyContent: "space-between", color: "#a7b5cc", fontSize: 11 }}><span>safe to replay</span><span style={{ color: colors.teal }}>● ready</span></div></div></Frame>;
};

const PushScene: FC<{ frame: number }> = ({ frame }) => {
  const start = scenes[4].start;
  const within = p(frame, start, scenes[4].end);
  const message = p(frame, start + 18, start + 43);
  const ack = p(frame, start + 68, start + 93);
  return <Frame index={4} frame={frame}><div style={{ position: "absolute", left: 88, top: 142 }}><Kicker tone="teal">Pushed, then human</Kicker><div style={{ marginTop: 15, fontSize: 48, lineHeight: 1, letterSpacing: "-.07em", fontWeight: 760, color: colors.ink }}>The right people see it.</div></div><div style={{ position: "absolute", left: 220, top: 260, width: 840, minHeight: 264, borderRadius: 22, background: "rgba(255,255,255,.92)", border: `1px solid ${colors.line}`, boxShadow: "0 25px 65px rgba(15,23,42,.13)", overflow: "hidden" }}><div style={{ padding: "16px 22px", borderBottom: `1px solid ${colors.line}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}><div style={{ color: colors.ink, fontWeight: 800, fontSize: 14 }}>#growth-leadership</div><div style={{ color: colors.muted, fontSize: 11, letterSpacing: ".12em" }}>ACK LOOP</div></div><div style={{ padding: "24px 34px" }}><div style={{ display: "flex", justifyContent: "flex-end", opacity: message, transform: `translateY(${interpolate(message, [0, 1], [15, 0], clamp)}px)` }}><div style={{ maxWidth: 510, padding: "16px 19px", borderRadius: "15px 15px 4px 15px", background: "#eef1ff", color: colors.ink }}><Kicker>Growth Monitoring Agent</Kicker><div style={{ marginTop: 8, fontSize: 17, fontWeight: 620 }}>Revenue drift is meaningful. Evidence attached.</div></div></div><div style={{ marginTop: 16, display: "flex", justifyContent: "flex-start", opacity: ack, transform: `translateY(${interpolate(ack, [0, 1], [15, 0], clamp)}px)` }}><div style={{ maxWidth: 360, padding: "16px 19px", borderRadius: "15px 15px 15px 4px", background: "#e9faf3", color: colors.ink }}><Kicker tone="teal">Growth leadership</Kicker><div style={{ marginTop: 8, fontSize: 17, fontWeight: 620 }}>Ack — looking into it!</div></div></div></div><div style={{ position: "absolute", left: 22, right: 22, bottom: 14, display: "flex", alignItems: "center", gap: 9, color: colors.teal, fontSize: 11, fontWeight: 800 }}><Dot tone="teal" size={6} />human response received</div></div><div style={{ position: "absolute", left: 88, right: 88, bottom: 47, height: 3, borderRadius: 999, background: colors.line }}><div style={{ width: `${within * 100}%`, height: "100%", borderRadius: 999, background: `linear-gradient(90deg, ${colors.teal}, ${colors.indigo}, ${colors.pink})` }} /></div></Frame>;
};

export const SignalWeaveFilm: FC<FilmProps> = () => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ background: "#e8edf2", overflow: "hidden", fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif" }}><AbsoluteFill style={{ background: "radial-gradient(circle at 12% 10%, rgba(20,184,166,.13), transparent 24%), radial-gradient(circle at 90% 85%, rgba(91,97,232,.12), transparent 29%), linear-gradient(135deg, #f7fafc 0%, #e8edf3 100%)" }} /><QueryScene frame={frame} /><JudgmentScene frame={frame} /><GraphScene frame={frame} /><DecisionScene frame={frame} /><PushScene frame={frame} /><div style={{ position: "absolute", left: 46, right: 46, bottom: 10, height: 2, borderRadius: 999, background: "rgba(15,23,42,.12)", zIndex: 20 }}><div style={{ width: `${(frame / (22 * SIGNAL_WEAVE_FPS - 1)) * 100}%`, height: "100%", borderRadius: 999, background: `linear-gradient(90deg, ${colors.teal}, ${colors.indigo}, ${colors.pink})` }} /></div></AbsoluteFill>;
};
