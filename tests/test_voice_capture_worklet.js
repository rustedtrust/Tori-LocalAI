"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "tori", "web_assets", "voice_capture_worklet.js"), "utf8"
);
let Processor;
class AudioWorkletProcessor {
  constructor() {
    this.port = {messages: [], postMessage: (buffer) => this.port.messages.push(buffer)};
  }
}
vm.runInNewContext(source, {
  AudioWorkletProcessor,
  Float32Array,
  Int16Array,
  Math,
  sampleRate: 48_000,
  registerProcessor(_name, processor) { Processor = processor; },
}, {filename: "voice_capture_worklet.js"});

const processor = new Processor();
const quantum = new Float32Array(128);
quantum[0] = -1;
quantum[1] = -0.5;
quantum[2] = 0.5;
quantum[3] = 1;
quantum[4] = 0;
quantum[5] = 1.5;
quantum[6] = -1.5;
for (let count = 0; count < 3_750; count += 1) {
  assert.equal(processor.process([[quantum]]), true);
}
assert.equal(processor.port.messages.length, 40, "ten seconds become four transport chunks per second");
const pcm = new Int16Array(processor.port.messages[0]);
assert.equal(pcm.length, 12_000, "250 ms at 48 kHz is one 12,000-frame transport chunk");
assert.deepEqual([...pcm.slice(0, 7)], [-32_768, -16_384, 16_384, 32_767, 0, 32_767, -32_768]);
assert.equal(pcm.byteLength, 24_000);
assert.ok(processor.port.messages.every((message) => message.byteLength === 24_000));
