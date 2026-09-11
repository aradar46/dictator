/**
 * Main-thread host for {@link ./stt-worker.ts}.
 *
 * Spawns a module worker when the environment supports it (browsers). Node
 * tests and {@link Stream.transcribe} stay on the main thread.
 */
import type { ModelArch } from './enums.js';
import type { TranscriptEventListener } from './events.js';
import type { SttLoadSource } from './stt-worker-protocol.js';
export interface SttLoadTranscriberConfig {
    transcriberId: string;
    modelArch: ModelArch;
    options?: Record<string, string>;
    source: SttLoadSource;
}
/** True when we can run STT inference off the main thread. */
export declare function sttWorkerSupported(): boolean;
/**
 * Base URL for files next to this module (`moonshine.wasm`, the worker, …).
 * Trailing slash included so `new URL(path, base)` resolves correctly.
 */
export declare function moonshineWasmBaseUrl(): string;
export declare class SttWorkerHost {
    private worker;
    private nextId;
    private pending;
    private readonly wasmBaseUrl;
    private closed;
    private readonly listeners;
    /** Audio posted to a stream that the worker has not yet ingested. */
    private readonly inflightSeconds;
    onProgress?: (transcriberId: string, loaded: number, total: number | undefined, file: string) => void;
    onPass?: (streamId: string, ms: number) => void;
    constructor(wasmBaseUrl?: string);
    private dispatchEvent;
    private request;
    /** Downloads and constructs a transcriber inside the worker. */
    loadTranscriber(config: SttLoadTranscriberConfig): Promise<void>;
    createStream(transcriberId: string, streamId: string, options?: {
        flags?: number;
        updateInterval?: number;
        priority?: number;
    }): Promise<void>;
    setListener(streamId: string, listener: TranscriptEventListener): void;
    start(streamId: string): Promise<void>;
    /**
     * Posts PCM to the worker without waiting for a pass. The buffer is copied
     * and transferred; the caller can keep using `audio`.
     */
    addAudio(streamId: string, audio: Float32Array, sampleRate: number, options?: {
        transcribe?: boolean;
    }): void;
    /** Seconds of audio posted to the worker that it has not yet ingested. */
    queuedSeconds(streamId: string): number;
    stop(streamId: string): Promise<void>;
    closeStream(streamId: string): Promise<void>;
    close(): void;
}
//# sourceMappingURL=stt-worker-host.d.ts.map