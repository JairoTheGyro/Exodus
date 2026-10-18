/**
 * Clock — alert tones, synthesised with Web Audio so no audio files ship.
 * (Clock.app plays system tones from ToneLibrary; these are original stand-ins.)
 */

export const SOUNDS = [
  { id: 'chime', name: 'Chime' },
  { id: 'beacon', name: 'Beacon' },
  { id: 'bell', name: 'Bell' },
  { id: 'pulse', name: 'Pulse' },
  { id: 'ripple', name: 'Ripple' },
  { id: 'none', name: 'None' },
];
export const DEFAULT_SOUND = 'chime';

export function soundName(id) {
  const s = SOUNDS.find(x => x.id === id) || SOUNDS[0];
  return s.id === DEFAULT_SOUND ? `${s.name} (Default)` : s.name;
}

let ctx = null;
function audio() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  if (ctx.state === 'suspended') ctx.resume().catch(() => {});
  return ctx;
}

function note(ac, at, freq, dur, { type = 'sine', gain = 0.22, attack = 0.008 } = {}) {
  const osc = ac.createOscillator();
  const g = ac.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, at);
  g.gain.setValueAtTime(0, at);
  g.gain.linearRampToValueAtTime(gain, at + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  osc.connect(g).connect(ac.destination);
  osc.start(at);
  osc.stop(at + dur + 0.05);
}

// One phrase per tone; looped by the caller while an alert is showing.
const PHRASES = {
  chime: (ac, t) => { [880, 1108.7, 1318.5, 1108.7].forEach((f, i) => note(ac, t + i * 0.16, f, 0.9)); return 1.6; },
  beacon: (ac, t) => { note(ac, t, 1046.5, 0.35, { type: 'triangle' }); note(ac, t + 0.4, 1046.5, 0.35, { type: 'triangle' }); return 1.2; },
  bell: (ac, t) => { note(ac, t, 659.3, 2.2, { gain: 0.25 }); note(ac, t, 1318.5, 1.4, { gain: 0.08 }); note(ac, t, 1975.5, 0.8, { gain: 0.04 }); return 2.0; },
  pulse: (ac, t) => { for (let i = 0; i < 4; i++) note(ac, t + i * 0.12, 1500, 0.08, { type: 'square', gain: 0.06 }); return 0.9; },
  ripple: (ac, t) => { [523.3, 659.3, 784, 1046.5, 1318.5].forEach((f, i) => note(ac, t + i * 0.07, f, 0.5, { gain: 0.15 })); return 1.4; },
};

/** Play one phrase (used for previews in the sound pickers). */
export function preview(id) {
  const ac = audio();
  if (!ac || !PHRASES[id]) return;
  PHRASES[id](ac, ac.currentTime + 0.02);
}

/** Loop a tone until the returned stop() is called. */
export function loop(id) {
  const ac = audio();
  if (!ac || !PHRASES[id]) return () => {};
  let stopped = false, timer = null;
  const play = () => {
    if (stopped) return;
    const len = PHRASES[id](ac, ac.currentTime + 0.02);
    timer = setTimeout(play, (len + 0.5) * 1000);
  };
  play();
  return () => { stopped = true; clearTimeout(timer); };
}
