#!/usr/bin/env node
/**
 * Run DataDome boring_challenge WASM from base64 (file or deobfuscator report).
 * Usage:
 *   node scripts/run_wasm.js [wasm.txt|report.json]
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const { performance } = require("perf_hooks");

function runWasmChallengeSync(wasmBase64, concurrency = os.cpus().length) {
  const bytes = Uint8Array.from(Buffer.from(wasmBase64.trim(), "base64"));
  const module = new WebAssembly.Module(bytes.buffer);
  const table = new WebAssembly.Table({ initial: 0, element: "anyref" });
  const importObject = {
    wbg: {
      __wbindgen_init_externref_table: () => {
        const base = table.grow(4);
        table.set(base + 0, undefined);
        table.set(base + 1, null);
        table.set(base + 2, true);
        table.set(base + 3, false);
      },
      __wbindgen_export_0: table,
    },
  };
  const instance = new WebAssembly.Instance(module, importObject);
  if (!instance.exports.boring_challenge) {
    throw new Error(
      "WASM module has no boring_challenge export (interstitial wasm_b is different — use datadome-wasm/wasm.txt)"
    );
  }
  const seed = Math.floor(Math.random() * (20_000_000 - 10_000_000 + 1)) + 10_000_000;
  const t0 = performance.now();
  const out = instance.exports.boring_challenge(BigInt(seed), BigInt(concurrency));
  const t1 = performance.now();
  return { result: Number(out), seed, elapsed_ms: t1 - t0 };
}

function loadWasmBase64(inputPath) {
  const raw = fs.readFileSync(inputPath, "utf-8");
  if (inputPath.endsWith(".json")) {
    const report = JSON.parse(raw);
    const wasm =
      report.wasm?.wasm ||
      report.modules?.find((m) => m.wasm)?.wasm?.wasm;
    if (!wasm) throw new Error("No wasm.wasm in report JSON");
    return wasm;
  }
  return raw.trim();
}

const input = process.argv[2] || path.join(__dirname, "..", "datadome-wasm", "wasm.txt");
const b64 = loadWasmBase64(input);
const { result, seed, elapsed_ms } = runWasmChallengeSync(b64);
console.log(JSON.stringify({ result, seed, elapsed_ms: Number(elapsed_ms.toFixed(2)) }, null, 2));
