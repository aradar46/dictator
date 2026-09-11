/**
 * Voice dialogs: the one-call way to build a speech interface.
 *
 * ```ts
 * const agent = new AgentFlow();
 *
 * agent.listenFor('set up wifi', async (d) => {
 *   const ssid = await d.ask("What's the name of your wifi network?");
 *   if (await d.confirm(`I heard ${ssid}. Is that right?`)) {
 *     await d.say(`Done. Connecting to ${ssid}.`);
 *   }
 * });
 *
 * await agent.load();
 * await agent.startListening();
 * ```
 *
 * `load()` downloads and wires everything a voice interface needs: a streaming
 * speech-to-text model, an embedding model for matching trigger phrases, a
 * text-to-speech voice, and a microphone. `speech(false)` and
 * `microphone(false)` each drop one of those when an application does not need
 * it. A flow is an ordinary async function, so it reads top to bottom and
 * `try` / `finally` work the way you expect.
 *
 * Scope note vs. the Python runner: this port implements free-form asks plus
 * confirm/choose matching. The alphanumeric dictation subsystem and the
 * success/error beep diagnostics are not here yet.
 */
import { AssetDownloader } from './asset-downloader.js';
import { ModelArch } from './enums.js';
import { type PhraseGroup } from './embedding-model.js';
import { MicTranscriber, type ProgressCallback } from './mic-transcriber.js';
import { type MoonshineModule } from './module.js';
import { TextToSpeech } from './text-to-speech.js';
/** Thrown into a flow when the user (or a global handler) cancels it. */
export declare class DialogCancelled extends Error {
    constructor();
}
/** Thrown into a flow when it should start again from the top. */
export declare class DialogRestart extends Error {
    constructor();
}
/** Thrown out of `ask` / `confirm` / `choose` after the retries run out. */
export declare class DialogNoMatch extends Error {
    constructor(message?: string);
}
export interface AskOptions {
    /** Give up waiting after this long and re-prompt. */
    timeoutMs?: number;
    /** Spoken when the answer wasn't understood. `{prompt}` is substituted. */
    reprompt?: string;
    /** How many times to re-prompt before giving up. Defaults to 2. */
    maxRetries?: number;
}
export interface ConfirmOptions extends AskOptions {
    yesPhrases?: string[];
    noPhrases?: string[];
}
/**
 * The conversation, handed to a flow as its only argument. Every method speaks
 * and then waits, so a flow is just straight-line code.
 */
export declare class Dialog {
    /** The phrase that started this flow. */
    readonly triggerPhrase: string;
    /** Scratch space for the flow's own use; the runner never touches it. */
    readonly state: Record<string, unknown>;
    private readonly runner;
    constructor(runner: AgentFlow, triggerPhrase?: string);
    /** Speaks `text` and waits for playback to finish. */
    say(text: string): Promise<void>;
    /** Asks an open question and returns what the user said. */
    ask(prompt: string, options?: AskOptions): Promise<string>;
    /** Asks a yes/no question. */
    confirm(prompt: string, options?: ConfirmOptions): Promise<boolean>;
    /**
     * Offers a set of choices and returns the key of the one picked. Each key
     * maps to the phrases that select it; the key itself always counts.
     */
    choose(prompt: string, options: Record<string, string[]>, settings?: AskOptions): Promise<string>;
    /** Abandons the flow. */
    cancel(): never;
    /** Runs the flow again from the beginning. */
    restart(): never;
}
export type FlowFn = (dialog: Dialog) => void | Promise<void>;
export type GlobalHandler = (dialog: Dialog) => void | Promise<void>;
export type UnmatchedHandler = (text: string) => void | Promise<void>;
type Interpretation<T> = {
    ok: true;
    value: T;
} | {
    ok: false;
};
export declare class AgentFlow {
    private readonly flows;
    private readonly globals;
    /**
     * Globals that only mean anything while a flow is running. The built-in
     * "cancel" and "start over" are in here: matching them when nothing is
     * active would consume the line, do nothing with it, and leave a dictation
     * interface silently missing a sentence.
     */
    private readonly flowScopedGlobals;
    private languageCode;
    private arch;
    private voiceId?;
    private wantsMicrophone;
    private wantsSpeech;
    private threshold;
    private assetBase?;
    private context?;
    private progressCallback?;
    private speakOverride?;
    private heardCallbacks;
    private saidCallbacks;
    private errorCallbacks;
    private unmatchedCallbacks;
    private mod?;
    private sharedDownloader?;
    private tts?;
    private embedding?;
    private matcher;
    private mic?;
    private micConstraints;
    private ownsTts;
    private ownsMic;
    private activeDialog?;
    private activeTriggerPhrase?;
    private pending?;
    private speaking;
    /** Serializes utterance handling so one flow advances at a time. */
    private queue;
    /**
     * Woken when the runner comes to rest, meaning the flow either finished or
     * is parked waiting for the next thing the user says. Handing an utterance
     * in resolves at that point rather than when the whole flow completes, which
     * would deadlock: the flow is waiting for the utterance after this one.
     */
    private settleWaiters;
    constructor();
    private addFlowScopedGlobal;
    /** Speech-to-text and synthesis language. Defaults to `"en"`. */
    language(code: string): this;
    /** Overrides the streaming speech-to-text model. */
    modelArch(arch: ModelArch): this;
    /** Voice used for spoken prompts, e.g. `"kokoro_af_heart"`. */
    voice(id: string): this;
    /** Fetches all model assets from a base URL you host instead of the CDN. */
    modelsFrom(baseUrl: string): this;
    /** Set to false to drive the agent from text instead of a microphone. */
    microphone(enabled: boolean): this;
    /**
     * Whether {@link load} should open a synthesizer. Defaults to true. Turn it
     * off for a silent runner: prompts still reach {@link onSaid} and flows still
     * advance, they just aren't spoken, and no voice is downloaded.
     */
    speech(enabled?: boolean): this;
    /**
     * Constraints for the microphone this opens, e.g. to name a capture device
     * rather than accept the browser's default. Ignored when a transcriber is
     * supplied through {@link useMicTranscriber}, which brings its own.
     */
    audioConstraints(constraints: MediaTrackConstraints | boolean): this;
    /** Similarity a trigger phrase needs to match, 0 to 1. Defaults to 0.7. */
    triggerThreshold(threshold: number): this;
    audioContext(context: AudioContext): this;
    /** Combined download progress for every model, as a `0..1` fraction. */
    onProgress(callback: ProgressCallback): this;
    /** Called with each thing the user says. */
    onHeard(callback: (text: string) => void): this;
    /** Called with each thing the assistant says. */
    onSaid(callback: (text: string) => void): this;
    /** Called when a flow throws something the runner doesn't handle itself. */
    onError(callback: (error: Error) => void): this;
    /** Replaces the built-in synthesizer, e.g. to route prompts somewhere else. */
    speakWith(speak: (text: string) => void | Promise<void>): this;
    /** Registers a flow to run when the user says something like `phrase`. */
    listenFor(phrase: string, flow: FlowFn): this;
    /**
     * Registers a handler that runs whenever `phrase` is heard, even in the
     * middle of a flow. This is how `cancel` and `start over` are implemented.
     */
    always(phrase: string, handler: GlobalHandler): this;
    /**
     * Registers a handler for speech that matched no global, no waiting prompt
     * and no trigger. This is what a dictation interface hangs its text off:
     * `onHeard` reports every line including commands and answers, while this
     * one reports only the lines nothing else claimed.
     *
     * Nothing arrives here while a flow is running, because a flow's prompts
     * take every line until it finishes.
     */
    otherwise(handler: UnmatchedHandler): this;
    useModule(module: MoonshineModule): this;
    useDownloader(downloader: AssetDownloader): this;
    useTextToSpeech(tts: TextToSpeech): this;
    useMicTranscriber(mic: MicTranscriber): this;
    /** Downloads and wires every model the agent needs. */
    load(): Promise<this>;
    /** Opens the microphone and starts responding to trigger phrases. */
    startListening(): Promise<void>;
    stopListening(): Promise<void>;
    /** Says something outside any flow, e.g. a welcome message. */
    say(text: string): Promise<void>;
    /**
     * Speaks a reply that is still being written, a piece at a time.
     *
     * Each complete sentence starts playing while the rest is still arriving, so
     * an LLM's answer can be forwarded token by token rather than waited for in
     * full:
     *
     * ```ts
     * await flow.sayStream(async (push) => {
     *   for await (const token of llm.stream(question)) push(token);
     * });
     * ```
     *
     * The microphone stays muted and self-capture stays suppressed for the whole
     * passage, exactly as in {@link say}, and this does not resolve until
     * playback has finished. Falls back to collecting the text and speaking it in
     * one go when there is no built-in synthesizer.
     */
    sayStream(produce: (push: (text: string) => void) => void | Promise<void>): Promise<void>;
    /**
     * Feeds in an utterance the agent didn't hear itself. Useful for text input
     * and for tests. Resolves once the flow has advanced as far as it can.
     */
    handleUtterance(text: string): Promise<void>;
    /** True while a flow is running. */
    get isActive(): boolean;
    /** The trigger phrase of the running flow, if any. */
    get activeTrigger(): string | undefined;
    /** Abandons the running flow. Returns false if there wasn't one. */
    cancel(): boolean;
    close(): void;
    /** @internal */
    speakInFlow(text: string): Promise<void>;
    /**
     * Speaks a prompt, waits for an answer, and re-prompts until `interpret`
     * accepts one or the retries run out.
     * @internal
     */
    promptForAnswer<T>(prompt: string, options: AskOptions, interpret: (text: string) => Interpretation<T>): Promise<T>;
    private transcriptListener;
    private waitForAnswer;
    /** Resolves the next time the runner finishes a flow or parks on a prompt. */
    private settledSignal;
    private notifySettled;
    private resolvePending;
    private rejectPending;
    private dispatch;
    private matchTrigger;
    /**
     * The globals worth matching right now. Flow-scoped ones are offered only
     * while a flow is running, so with nothing active their phrases reach
     * `otherwise()` like any other speech.
     */
    private liveGlobals;
    /**
     * The key of the group whose phrases best match `utterance`, used by
     * `Dialog.confirm` and `Dialog.choose`.
     *
     * @internal
     */
    matchKey(utterance: string, groups: PhraseGroup[]): string | undefined;
    private runFlow;
    private invokeGlobal;
    private speak;
}
/** Renders a string as a space-separated spoken form for reading back. */
export declare function spellOut(value: string): string;
export {};
//# sourceMappingURL=agent-flow.d.ts.map