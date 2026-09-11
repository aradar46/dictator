/**
 * Text embeddings: turns text into vectors and scores them against each other.
 *
 * This is internal to the binding. {@link AgentFlow} is the supported way to
 * match spoken phrases; it owns a model and compares utterances to phrases
 * itself, so nothing here is exported from the package entry point.
 *
 * The embedding model ships as a single all-in-one `.ort` file (plus
 * `tokenizer.bin`) and is loaded entirely from in-memory buffers via the
 * `moonshine_create_embedding_model_from_memory` C ABI — the browser has no
 * natural filesystem, so nothing is staged to disk.
 */
import { AssetDownloader } from './asset-downloader.js';
import { EmbeddingModelArch } from './enums.js';
import { type LoadModuleOptions, type MoonshineModule } from './module.js';
export interface EmbeddingFromCatalog {
    /** Embedding model id (e.g. `"embeddinggemma-300m"`). Empty = default. */
    modelName?: string;
    modelArch?: EmbeddingModelArch;
    /** One of "q4", "q8", "fp16", "fp32", "q4f16". Empty = model default. */
    variant?: string;
    downloader?: AssetDownloader;
    onProgress?: (loaded: number, total: number | undefined, file: string) => void;
}
export type EmbeddingModelOptions = EmbeddingFromCatalog & {
    moduleOptions?: LoadModuleOptions;
    module?: MoonshineModule;
};
/** Options for {@link EmbeddingModel.loadFromUrls} (self-hosted model files). */
export interface EmbeddingFromUrlsOptions {
    modelArch?: EmbeddingModelArch;
    /** One of "q4", "q8", "fp16", "fp32", "q4f16". Empty = "q4". */
    variant?: string;
    downloader?: AssetDownloader;
    onProgress?: (loaded: number, total: number | undefined, file: string) => void;
    moduleOptions?: LoadModuleOptions;
    module?: MoonshineModule;
}
export declare class EmbeddingModel {
    private readonly raw;
    private constructor();
    static load(options?: EmbeddingModelOptions): Promise<EmbeddingModel>;
    /**
     * Loads the embedding model from a caller-supplied map of canonical filename
     * -> URL (e.g. `{ 'model_q4.ort': '...', 'tokenizer.bin': '...' }`), for
     * self-hosting the model files instead of using the Moonshine CDN.
     */
    static loadFromUrls(files: Record<string, string> | Map<string, string>, options?: EmbeddingFromUrlsOptions): Promise<EmbeddingModel>;
    private static construct;
    /** The embedding vector for `sentence`. */
    calculateEmbedding(sentence: string): Float32Array;
    /** Cosine similarity between two embeddings of equal length, in `[-1, 1]`. */
    distance(embeddingA: Float32Array, embeddingB: Float32Array): number;
    close(): void;
    [Symbol.dispose](): void;
}
/** A key and the phrases that select it. */
export interface PhraseGroup {
    key: string;
    phrases: string[];
}
/**
 * Matches an utterance to one of several phrase groups by meaning.
 *
 * Each phrase is embedded once and cached, the utterance is embedded once per
 * call, and the key of the best-scoring phrase at or above `threshold` wins.
 * Without an {@link EmbeddingModel} it falls back to case-insensitive substring
 * matching, which is what keeps dialogs working before {@link AgentFlow.load}.
 */
export declare class PhraseMatcher {
    private readonly model?;
    private readonly cache;
    constructor(model?: EmbeddingModel);
    /** The best-matching key, or undefined when nothing clears `threshold`. */
    match(utterance: string, groups: PhraseGroup[], threshold: number): string | undefined;
    /** The best-matching phrase, treating each phrase as its own key. */
    matchPhrases(utterance: string, phrases: string[], threshold: number): string | undefined;
    private embeddingFor;
}
//# sourceMappingURL=embedding-model.d.ts.map