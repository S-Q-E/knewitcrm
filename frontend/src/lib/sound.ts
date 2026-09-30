/** Short notification ping synthesized with WebAudio (no asset files). */
let context: AudioContext | null = null;

export function playPing(): void {
  try {
    const ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!ctor) {
      return;
    }
    context ??= new ctor();
    if (context.state === "suspended") {
      void context.resume();
    }
    const started = context.currentTime;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.001, started);
    gain.gain.exponentialRampToValueAtTime(0.2, started + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, started + 0.4);
    oscillator.start(started);
    oscillator.stop(started + 0.45);
  } catch {
    // Audio must never break the UI.
  }
}
