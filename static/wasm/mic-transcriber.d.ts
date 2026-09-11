/**
 * Live microphone transcription.
 *
 * ```ts
 * const mic = new MicTranscriber()
 *   .onText((text) => renderLive(text))
 *   .onLine((line) => appendFinal(line.text));
 *
 * await mic.load();
 * await mic.start();
 * ```
 *
 * Captures microphone audio via WebAudio (an AudioWorklet where available,
 * falling back to a ScriptProcessorNode), downmixes to mono, resamples to
 * 16 kHz, and feeds a streaming {@link Stream}. Everything except the choice of
 * language is optional.
 */
import { ModelArch } from './enums.js';
import type { TranscriptEventListener } from './events.js';
import { Transcriber } from './transcriber.js';
import type { TranscriptLine } from './types.js';
/** Byte counts behind a progress report, covering the whole model. */
export interface DownloadProgress {
    /** Bytes fetched so far across every file the model needs. */
    loaded: number;
    /**
     * Total bytes the model needs, from the sizes its manifest declares.
     * Undefined when fetching files of unknown size, in which case `fraction`
     * is meaningless and the download should be shown as indeterminate.
     */
    total?: number;
}
/**
 * Download progress: a `0..1` fraction of the *entire* model, the file
 * currently in flight, and the underlying byte counts.
 */
export type ProgressCallback = (fraction: number, file: string, progress?: DownloadProgress) => void;
export declare class MicTranscriber {
    private transcriber?;
    private ownsTranscriber;
    private languageCode;
    private arch;
    private modelSource?;
    private constraints;
    private flags;
    private readonly listeners;
    private textCallbacks;
    private lineCallbacks;
    private errorCallbacks;
    private progressCallback?;
    private mediaStream?;
    private audioContext?;
    private sourceNode?;
    private workletNode?;
    private scriptNode?;
    private stream?;
    private running;
    private muted;
    /** Speech-to-text language. Defaults to `"en"`. */
    language(code: string): this;
    /** Overrides the streaming model. Defaults to the best one for the language. */
    modelArch(arch: ModelArch): this;
    /**
     * Loads the model from somewhere other than the Moonshine CDN: either a base
     * URL that the canonical filenames are appended to (`'/models/'`), or one URL
     * per file (`{'encoder_model.ort': '/models/enc.ort'}`).
     */
    modelsFrom(source: string | Record<string, string>): this;
    /** Reuses an already-loaded transcriber rather than loading another. */
    useTranscriber(transcriber: Transcriber): this;
    /** Constraints passed to `getUserMedia({ audio })`. */
    audioConstraints(constraints: MediaTrackConstraints | boolean): this;
    /** Enables alphanumeric spelling mode for dictating codes and serial numbers. */
    spellingMode(enabled?: boolean): this;
    /** Called with the in-progress text of the line currently being spoken. */
    onText(callback: (text: string) => void): this;
    /** Called once per finished line. */
    onLine(callback: (line: TranscriptLine) => void): this;
    onError(callback: (error: Error) => void): this;
    /** Model download progress, as a `0..1` fraction. */
    onProgress(callback: ProgressCallback): this;
    /**
     * Attaches a full {@link TranscriptEventListener}, for applications that need
     * line ids, speaker spans, or word timings rather than just the text.
     */
    addListener(listener: TranscriptEventListener): this;
    /** Downloads the model if needed and prepares the transcriber. */
    load(): Promise<this>;
    /**
     * Opens the microphone and starts transcribing. Loads the model first if
     * {@link load} has not already been called.
     */
    start(): Promise<void>;
    /** Stops capture, flushes a final transcript, and releases audio resources. */
    stop(): Promise<void>;
    /**
     * Drops incoming audio without tearing down the microphone. Used to stop the
     * assistant transcribing its own synthesized speech.
     */
    mute(muted?: boolean): void;
    /**
     * Biases the decoder towards a list of terms while listening, replacing any
     * previous list. See {@link Transcriber.setKeyterms}; this can be called
     * between phrases to follow whatever the user is looking at. To start
     * listening with a list already in place, load a {@link Transcriber} with the
     * `keyterms` option and hand it to {@link useTranscriber}.
     */
    setKeyterms(keyterms: string[]): void;
    /**
     * Picks the key terms out of a passage of text and biases towards them while
     * listening. See {@link Transcriber.setContext}; this can be called between
     * phrases to follow the document or thread the user is in. To start listening
     * with a passage already in place, load a {@link Transcriber} with the
     * `context` option and hand it to {@link useTranscriber}.
     */
    setContext(context: string, maxTerms?: number): void;
    get isRunning(): boolean;
    /** Releases the stream, and the transcriber unless one was supplied. */
    close(): void;
    private namedCallbackListener;
    private emitError;
    private setupWorklet;
    private setupScriptProcessor;
}
/**
 * Adapts the `0..1` fraction callbacks the public API uses onto the
 * `(loaded, total, file)` shape the downloader reports. The downloader counts
 * bytes across the whole model, so the fraction is a true overall percentage
 * whenever the manifest declared its sizes.
 */
export declare function wrapProgress(callback: ProgressCallback | undefined): ((loaded: number, total: number | undefined, file: string) => void) | undefined;
/** Simple linear resampler to 16 kHz mono. */
export declare function resampleTo16k(input: Float32Array, inputRate: number): Float32Array;
/**
 * Averages capture channels into one mono buffer.
 *
 * Averaging rather than taking the first channel matters: plenty of capture
 * devices (USB headsets, audio interfaces, dock passthroughs) open as stereo
 * with the microphone on the right channel and digital silence on the left.
 * Reading only channel 0 there yields a stream of zeroes, so everything appears
 * to run and nothing is ever transcribed.
 *
 * Always returns a copy, because the worklet reuses its input buffers.
 */
export declare function downmixToMono(channels: readonly Float32Array[]): Float32Array;
//# sourceMappingURL=mic-transcriber.d.ts.map