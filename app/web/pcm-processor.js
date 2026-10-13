/**
 * Day 12: AudioWorklet PCM Processor
 * FILE: app/web/pcm-processor.js
 *
 * Browser audio thread pe raw PCM capture karta hai.
 * Float32 samples → Int16 (16-bit little-endian) convert karke
 * main thread ko bhejta hai, wahan se WebSocket ko.
 *
 * Kyun AudioWorklet (MediaRecorder nahi)?
 * MediaRecorder only encodes to WebM/Opus — raw PCM nahi deta.
 * Server raw PCM expect karta hai. AudioWorklet = 2026 industry standard.
 *
 * Kyun 4096 samples ka buffer?
 * Default 128 samples → mobile/low-end devices pe crackling/distortion.
 * 4096 samples = ~256ms at 16kHz — optimal latency vs stability balance.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Int16Array(4096);
    this._bufferIndex = 0;
  }

  process(inputs, _outputs, _parameters) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const float32Samples = input[0]; // Float32 range: -1.0 to 1.0

    for (let i = 0; i < float32Samples.length; i++) {
      // Float32 → Int16 clamp + round
      this._buffer[this._bufferIndex++] = Math.max(
        -32768,
        Math.min(32767, Math.round(float32Samples[i] * 32768))
      );

      // Buffer full → main thread ko bhejo (zero-copy via transferable)
      if (this._bufferIndex >= this._buffer.length) {
        const copy = this._buffer.slice();
        this.port.postMessage(copy.buffer, [copy.buffer]);
        this._bufferIndex = 0;
      }
    }

    return true; // Processor alive rakhho
  }
}

registerProcessor("pcm-processor", PCMProcessor);
