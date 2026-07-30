const FRAME_SIZE = 2048;

class MicrophoneCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Float32Array(FRAME_SIZE);
    this.offset = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) {
      return true;
    }

    let sourceOffset = 0;
    while (sourceOffset < input.length) {
      const available = FRAME_SIZE - this.offset;
      const length = Math.min(available, input.length - sourceOffset);
      this.frame.set(
        input.subarray(sourceOffset, sourceOffset + length),
        this.offset
      );
      this.offset += length;
      sourceOffset += length;

      if (this.offset === FRAME_SIZE) {
        this.port.postMessage(this.frame, [this.frame.buffer]);
        this.frame = new Float32Array(FRAME_SIZE);
        this.offset = 0;
      }
    }

    return true;
  }
}

registerProcessor("microphone-capture", MicrophoneCaptureProcessor);
