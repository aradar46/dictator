/**
 * Text to speech, including zero-shot voice cloning.
 *
 * ```ts
 * const tts = new TextToSpeech().language('en_us').voice('kokoro_af_heart');
 * await tts.load();
 * await tts.say('Hello world!');
 * ```
 *
 * Cloning is a create-time mode, like choosing a catalog voice. Call
 * {@link cloning} before {@link load} so every ZipVoice + clone-ASR asset is
 * fetched up front; then {@link cloneFrom} only swaps the reference clip:
 *
 * ```ts
 * const tts = new TextToSpeech().language('en_us').cloning();
 * await tts.load();
 * await tts.cloneFrom(recording);
 * await tts.say('Hello in your voice!');
 * ```
 */
import { AssetDownloader } from './asset-downloader.js';
import { type ProgressCallback } from './mic-transcriber.js';
import { type LoadModuleOptions, type MoonshineModule } from './module.js';
import type { TtsSynthesisResult } from './types.js';
import { VoiceClone, type VoiceCloneOptions } from './voice-clone.js';
/** Anything {@link TextToSpeech.cloneFrom} can take a reference voice from. */
export type CloneSource = string | URL | Blob | ArrayBuffer | AudioBuffer | Float32Array | VoiceClone | {
    audio: Float32Array;
    sampleRate: number;
};
/** Anything {@link TextToSpeech.stream} can take its text from. */
export type TtsTextSource = string | Iterable<string> | AsyncIterable<string>;
/** One piece of streamed audio from {@link TextToSpeech.stream}. */
export interface TtsChunk {
    audio: Float32Array;
    sampleRate: number;
    /** The text this chunk covers, or `''` when the engine cannot attribute it. */
    text: string;
    /** Which queued utterance this chunk belongs to, counting from one. */
    utteranceId: number;
    /** True for the last chunk of an utterance. */
    isFinal: boolean;
}
/** A single voice row returned by {@link TextToSpeech.voices}. */
export interface TtsVoiceEntry {
    id: string;
    state: 'found' | 'missing';
}
export interface TtsVoicesOptions {
    /** Comma-separated languages (default: `language`). */
    languages?: string;
    language?: string;
    /**
     * A representative voice id whose prefix selects the engine to list:
     * `kokoro_*` (default), `piper_*`, or `zipvoice_*`.
     */
    voice?: string;
    moduleOptions?: LoadModuleOptions;
    module?: MoonshineModule;
}
export declare class TextToSpeech {
    private raw?;
    private mod?;
    private moduleOpts?;
    private downloader?;
    private languageCode;
    private voiceId?;
    private assetBase?;
    private suppliedAssets?;
    /** Assets fetched by {@link load}; reused by {@link cloneFrom} with no re-download. */
    private loadedAssets?;
    private extraOptions;
    private progressCallback?;
    private context?;
    private ownsContext;
    private cloningWanted;
    /** End of already-scheduled playback, on the AudioContext clock. */
    private playbackTail;
    /** Scheduled-but-unfinished sources, so {@link stop} can silence them. */
    private readonly scheduledSources;
    /** The clip the current voice was cloned from, if any. */
    private cloneAudio?;
    private cloneTranscript?;
    /** Last {@link say} output, keyed by the spoken text, for instant replay. */
    private sayCache?;
    /** True once the streaming reply in flight has drained or been abandoned. */
    private streamEnded;
    /** Resolved when text arrives or the reply ends, so a waiting pull retries. */
    private streamWaiter?;
    /**
     * Browser worker that owns a synthesizer for {@link say}. Absent in Node
     * tests, which keep synthesis on the main thread.
     */
    private workerHost?;
    /** Snapshot used to recreate a main-thread synthesizer for {@link synthesize}. */
    private mainEngine?;
    /** Synthesis language, e.g. `"en"` or `"en_us"`. Defaults to `"en"`. */
    language(code: string): this;
    /**
     * Catalog voice id, e.g. `"kokoro_af_heart"`. Clears {@link cloning} — a
     * synthesizer is either a catalog voice or a cloning engine, not both.
     */
    voice(id: string): this;
    /**
     * Fetches the voice and G2P assets from a base URL you host instead of the
     * Moonshine CDN. Canonical names (e.g. `kokoro/prosody.model.ort`) are
     * appended.
     */
    modelsFrom(baseUrl: string): this;
    /**
     * Supplies voice assets directly, keyed by canonical name (e.g.
     * `kokoro/prosody.model.ort`). Nothing is downloaded when this is set.
     */
    assets(assets: Map<string, Uint8Array>): this;
    /**
     * Create this synthesizer as a ZipVoice cloning engine. Call before
     * {@link load} so ZipVoice and clone-ASR assets are fetched up front.
     * Clears {@link voice}. Only then may {@link cloneFrom} / {@link startCloning}
     * be used.
     */
    cloning(enabled?: boolean): this;
    /** Model download progress, as a `0..1` fraction. */
    onProgress(callback: ProgressCallback): this;
    /** Reuses an AudioContext for playback rather than creating one per call. */
    audioContext(context: AudioContext): this;
    /** Shares an already-initialised WASM module. */
    useModule(module: MoonshineModule): this;
    /** Shares a downloader, so several engines report progress together. */
    useDownloader(downloader: AssetDownloader): this;
    /** Escape hatch for `moonshine_option_t` entries the builder doesn't cover. */
    nativeOptions(options: Record<string, string>): this;
    /**
     * Downloads every asset this synthesizer needs and prepares it. With
     * {@link cloning}, that includes ZipVoice and clone ASR — afterwards
     * {@link cloneFrom} does not go back to the network.
     */
    load(): Promise<this>;
    /**
     * Clones the voice in `source` and uses it for subsequent synthesis. Accepts
     * a URL or path, a `File` / `Blob`, an `AudioBuffer`, raw 16 kHz mono PCM, or
     * a {@link VoiceClone} captured with {@link startCloning}.
     *
     * Requires {@link cloning} before {@link load}. The library trims the
     * recording and transcribes it for the vocoder (using assets already fetched
     * by `load`) unless you pass `transcript`.
     */
    cloneFrom(source: CloneSource, options?: {
        transcript?: string;
    }): Promise<this>;
    /**
     * Starts capturing a reference voice incrementally, for cloning from a live
     * microphone. Requires {@link cloning} before {@link load}.
     */
    startCloning(options?: VoiceCloneOptions): VoiceClone;
    /** True once a voice has been cloned into this instance. */
    get isCloned(): boolean;
    /** Synthesizes `text` to mono PCM without playing it. */
    synthesize(text: string): TtsSynthesisResult;
    /**
     * Concatenated PCM from the last {@link say} call, if any. Handy for a
     * download link or for tests; replay uses the per-sentence cache instead.
     */
    get lastSaid(): TtsSynthesisResult | undefined;
    /**
     * Speaks `text` out loud, resolving when playback finishes.
     *
     * Long strings are split on an approximate sentence boundary (`.`, `!`,
     * `?`, or `:` followed by whitespace). The first sentence starts playing as soon
     * as it is ready; later sentences synthesize on a Web Worker while the
     * previous one plays (main-thread fallback where Workers are unavailable).
     * Calling again with the same text replays the cached audio instantly.
     */
    say(text: string): Promise<void>;
    private playChunks;
    /**
     * Queues `result` immediately after whatever is already scheduled and
     * resolves when it has finished playing. Scheduling against the running
     * clock rather than waiting for `onended` means consecutive chunks join
     * without an audible gap.
     */
    private playOne;
    /**
     * Queues already-synthesized audio — a {@link TtsChunk} from
     * {@link stream}, say — after whatever is already scheduled, so successive
     * chunks join without a gap. Resolves once this piece has played.
     */
    playChunk(chunk: {
        audio: Float32Array;
        sampleRate: number;
    }): Promise<void>;
    /** Resolves when everything scheduled has finished playing. */
    waitForPlayback(): Promise<void>;
    /** Drops anything queued and silences playback immediately. */
    stop(): void;
    /** True while scheduled audio is still playing. */
    get isTalking(): boolean;
    /**
     * Lists the voices known for a language, with availability state. Pass a
     * `voice` whose prefix selects the engine to enumerate: `kokoro_*` (the
     * default), `piper_*`, or `zipvoice_*`.
     */
    static voices(options?: TtsVoicesOptions): Promise<TtsVoiceEntry[]>;
    /**
     * Splits `text` into the utterances {@link say} would speak one at a time,
     * using the shared native splitter.
     */
    splitUtterances(text: string): string[];
    /**
     * Appends text to the reply being spoken, starting one if needed.
     *
     * Pieces are concatenated verbatim, so a model's output can go in token by
     * token. Text is held back until it forms a complete sentence, because
     * synthesizing half a clause gets the prosody wrong.
     */
    pushText(text: string): void;
    /** Queues the buffered fragment even though it has no terminator. */
    flush(): void;
    /** Declares that no more text is coming, letting the reply finish. */
    endInput(): void;
    /**
     * Drops queued text and abandons the reply in progress. This is the barge-in
     * path: when someone interrupts the assistant, stop the reply.
     */
    cancelStream(): void;
    /** True while a reply is part-spoken. */
    get isStreaming(): boolean;
    /**
     * Synthesizes and returns the next chunk, blocking while it computes.
     *
     * `undefined` means there is nothing to hand back: either no complete
     * sentence is buffered yet, or the reply is over — drained, or discarded by
     * a {@link cancelStream}. {@link isStreaming} tells those apart. Prefer
     * {@link stream}, which yields between chunks so playback and the page get a
     * turn.
     */
    nextChunk(): TtsChunk | undefined;
    /**
     * The chunks of a reply, in order:
     *
     * ```ts
     * for await (const chunk of tts.stream(llm.tokens(question))) {
     *   await tts.playChunk(chunk);
     * }
     * ```
     *
     * With `text`, that whole reply is pushed and ended for you: pass a string,
     * or an iterable of pieces to forward as they arrive. Without it, call
     * {@link pushText} from elsewhere and iterate here. Iteration ends once
     * {@link endInput} lets the queue drain, or as soon as a
     * {@link cancelStream} elsewhere abandons the reply; leaving the loop early
     * abandons the rest of it.
     */
    stream(text?: TtsTextSource): AsyncGenerator<TtsChunk>;
    close(): void;
    [Symbol.dispose](): void;
    /** Pushes every piece of `text`, giving up if the consumer walked away. */
    private feedStream;
    private waitForStream;
    private wakeStream;
    /** Ends any iteration in flight, for when the engine is about to go away. */
    private endStreamIteration;
    private requireCloningMode;
    private isEngineReady;
    /**
     * Creates (or recreates) the main-thread synthesizer used by
     * {@link synthesize} and {@link startCloning}. No-op when one already exists
     * matching {@link mainEngine}.
     */
    private ensureMainThreadEngine;
    /**
     * (Re)creates the native synthesizer. `allowDownload` is true for
     * {@link load}; {@link cloneFrom} reuses {@link loadedAssets}.
     *
     * When Workers are available the engine used by {@link say} is built on a
     * worker (main thread stays free). A main-thread copy is created lazily for
     * {@link synthesize} / {@link startCloning}.
     */
    private build;
    private resolveAssets;
    /** One-shot STT of a clone clip using the advertised clone_asr assets. */
    private autotranscribeCloneClip;
    private downloadAssets;
    private resolveCloneSource;
    private ensureContext;
}
/**
 * Splits `text` the way {@link TextToSpeech.say} does, into the utterances a
 * synthesizer speaks one at a time. Uses the shared native splitter, so it
 * knows about abbreviations like `Dr.`, initials, quotes, and non-Latin
 * terminators such as `。` and `؟`.
 */
export declare function splitSayUtterances(text: string, options?: {
    language?: string;
    module?: MoonshineModule;
}): Promise<string[]>;
//# sourceMappingURL=text-to-speech.d.ts.map