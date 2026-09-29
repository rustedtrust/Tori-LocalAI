class ToriVoiceCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frames = [];
    this.frameCount = 0;
    this.chunkFrames = Math.max(1, Math.round(sampleRate / 4));
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input || input.length === 0) return true;
    this.frames.push(new Float32Array(input));
    this.frameCount += input.length;
    while (this.frameCount >= this.chunkFrames) {
      const floats = new Float32Array(this.chunkFrames);
      let offset = 0;
      while (offset < floats.length && this.frames.length) {
        const frame = this.frames[0];
        const take = Math.min(frame.length, floats.length - offset);
        floats.set(frame.subarray(0, take), offset);
        offset += take;
        if (take === frame.length) this.frames.shift();
        else this.frames[0] = frame.subarray(take);
      }
      this.frameCount -= this.chunkFrames;
      const pcm = new Int16Array(this.chunkFrames);
      for (let index = 0; index < floats.length; index += 1) {
        const sample = Math.max(-1, Math.min(1, floats[index]));
        pcm[index] = sample < 0 ? Math.round(sample * 32768) : Math.round(sample * 32767);
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("tori-voice-capture", ToriVoiceCaptureProcessor);
