/**
 * Captures the short reference clip that zero-shot voice cloning needs.
 *
 * ```ts
 * const clone = tts.startCloning();
 * clone.onReady(() => status.textContent = 'Got it — you can stop talking.');
 * await clone.fromMicrophone();
 * await tts.cloneFrom(clone);
 * ```
 *
 * Finding a usable clip means locating a window of the recording that is mostly
 * speech rather than silence or breathing. That search runs in the core (see
 * `moonshine_extract_speech_clip`), so the browser, iOS and Android bindings
 * all agree on what a good clip looks like. Extract stays VAD-only; ZipVoice
 * clone ASR refine + transcript happen once inside {@link TextToSpeech.cloneFrom}.
 */
import { type MoonshineModule } from './module.js';
export interface VoiceCloneOptions {
    /** Length of the reference clip in seconds. Defaults to 4. */
    clipSeconds?: number;
    /** How much of the clip has to be speech. Defaults to 2. */
    minimumSpeechSeconds?: number;
}
export declare class VoiceClone {
    private readonly module;
    private readonly ttsHandle;
    private readonly clipSeconds;
    private readonly minimumSpeechSeconds;
    private chunks;
    private sampleCount;
    private samplesSinceSearch;
    private clip?;
    private clipTranscript?;
    private speech;
    private readyCallbacks;
    private progressCallbacks;
    private stopCapture?;
    constructor(module: MoonshineModule, ttsHandle: number, options?: VoiceCloneOptions);
    /** Fires once, as soon as enough speech has been captured. */
    onReady(callback: () => void): this;
    /** Reports how long the caller has been recording and how much was speech. */
    onProgress(callback: (recordedSeconds: number, speechSeconds: number) => void): this;
    /** True once {@link audio} holds a usable reference clip. */
    get isReady(): boolean;
    /** Speech found in the best window so far, in seconds. */
    get speechSeconds(): number;
    /** Transcript is unused for VAD capture; cloneFrom fills it via create-time ASR. */
    get transcript(): string | undefined;
    get recordedSeconds(): number;
    /** The captured clip (16 kHz mono), or `undefined` until {@link isReady}. */
    get audio(): Float32Array | undefined;
    get sampleRate(): number;
    /**
     * Feeds captured audio in. Call this from your own audio pipeline; the search
     * for a usable window runs a few times a second rather than on every chunk.
     */
    addAudio(pcm: Float32Array, sampleRate: number): void;
    /**
     * Opens the microphone and records until there is enough speech, or until
     * `maxSeconds` have passed. Resolves with the clip, which is also available
     * from {@link audio}.
     */
    fromMicrophone(options?: {
        maxSeconds?: number;
        audioConstraints?: MediaTrackConstraints | boolean;
    }): Promise<Float32Array>;
    /** Stops an in-flight {@link fromMicrophone} capture. */
    cancel(): Promise<void>;
    /** Throws away everything captured so far. */
    reset(): void;
    private search;
}
/**
 * Pulls a reference clip out of already-recorded audio, without any capture
 * loop. Used by `TextToSpeech.cloneFrom` when given a file or buffer.
 */
export declare function extractSpeechClip(audio: Float32Array, sampleRate: number, options: VoiceCloneOptions & {
    module?: MoonshineModule;
    ttsHandle: number;
}): Promise<Float32Array>;
//# sourceMappingURL=voice-clone.d.ts.map