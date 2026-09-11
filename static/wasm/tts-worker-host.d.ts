/**
 * Main-thread host for {@link ./tts-worker.ts}.
 *
 * Spawns a module worker when the environment supports it (browsers). Node
 * tests fall back to main-thread synthesis inside {@link TextToSpeech}.
 */
import type { TtsSynthesisResult } from './types.js';
export interface TtsWorkerEngineConfig {
    language: string;
    keys: string[];
    buffers: Uint8Array[];
    optionNames: string[];
    optionValues: string[];
}
/** True when we can run TTS synthesis off the main thread. */
export declare function ttsWorkerSupported(): boolean;
/**
 * Base URL for files next to this module (`moonshine.wasm`, the worker, …).
 * Trailing slash included so `new URL(path, base)` resolves correctly.
 */
export declare function moonshineWasmBaseUrl(): string;
export declare class TtsWorkerHost {
    private worker;
    private nextId;
    private pending;
    private readonly wasmBaseUrl;
    private closed;
    constructor(wasmBaseUrl?: string);
    private request;
    /** (Re)creates the worker-side synthesizer from asset buffers. */
    setEngine(config: TtsWorkerEngineConfig): Promise<void>;
    /** Runs `moonshine_text_to_speech` on the worker. */
    synthesize(text: string): Promise<TtsSynthesisResult>;
    close(): void;
}
//# sourceMappingURL=tts-worker-host.d.ts.map