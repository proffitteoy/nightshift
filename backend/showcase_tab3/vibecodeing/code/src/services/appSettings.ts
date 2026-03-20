export type AITransport = 'openai-compatible' | 'anthropic' | 'gemini';
export type AIProviderId =
  | 'deepseek'
  | 'openai'
  | 'anthropic'
  | 'gemini'
  | 'openrouter'
  | 'ollama'
  | 'compatible';

export interface AIProviderDefinition {
  id: AIProviderId;
  label: string;
  description: string;
  transport: AITransport;
  defaultBaseUrl: string;
  defaultModel: string;
  env: {
    apiKey: string[];
    baseUrl: string[];
    model: string[];
    reviewModel: string[];
  };
}

export interface AppSettings {
  aiProvider: AIProviderId;
  aiBaseUrl: string;
  aiApiKey: string;
  aiModel: string;
  githubToken: string;
  maxDrillDepth: number;
  keySubFunctionCount: number;
}

export interface AppSettingsFieldResolution<T extends keyof AppSettings = keyof AppSettings> {
  key: T;
  value: AppSettings[T];
  source: 'env' | 'storage' | 'default' | 'embedded';
  storedValue?: AppSettings[T];
  hasStoredValue?: boolean;
  envName?: string;
  envValue?: string;
}

export interface ResolvedAppSettings {
  values: AppSettings;
  storedValues: AppSettings;
  fields: {
    [K in keyof AppSettings]: AppSettingsFieldResolution<K>;
  };
}

interface RuntimeAiSettings {
  provider: AIProviderDefinition;
  apiKey: string;
  baseUrl: string;
  model: string;
  reviewModel: string;
}

export interface EmbeddedRuntimeConfig {
  embedded: boolean;
  disableLocalProject: boolean;
  defaultGithubToken: string;
}

declare global {
  interface Window {
    __NIGHTSHIFT_TAB3_CONFIG__?: Partial<EmbeddedRuntimeConfig>;
  }
}

const STORAGE_KEY = 'gitvisual.app-settings.v2';
const LEGACY_STORAGE_KEY = 'gitvisual.app-settings.v1';
const SETTINGS_CHANGE_EVENT = 'gitvisual:settings-changed';

const ENV_VALUES: Record<string, string | undefined> = {
  AI_PROVIDER: process.env.AI_PROVIDER,
  AI_API_KEY: process.env.AI_API_KEY,
  AI_BASE_URL: process.env.AI_BASE_URL,
  AI_MODEL: process.env.AI_MODEL,
  AI_REVIEW_MODEL: process.env.AI_REVIEW_MODEL,
  DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY,
  DEEPSEEK_BASE_URL: process.env.DEEPSEEK_BASE_URL,
  DEEPSEEK_MODEL: process.env.DEEPSEEK_MODEL,
  DEEPSEEK_REVIEW_MODEL: process.env.DEEPSEEK_REVIEW_MODEL,
  OPENAI_API_KEY: process.env.OPENAI_API_KEY,
  OPENAI_BASE_URL: process.env.OPENAI_BASE_URL,
  OPENAI_MODEL: process.env.OPENAI_MODEL,
  OPENAI_REVIEW_MODEL: process.env.OPENAI_REVIEW_MODEL,
  ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
  ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL,
  ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL,
  ANTHROPIC_REVIEW_MODEL: process.env.ANTHROPIC_REVIEW_MODEL,
  GEMINI_API_KEY: process.env.GEMINI_API_KEY,
  GEMINI_BASE_URL: process.env.GEMINI_BASE_URL,
  GEMINI_MODEL: process.env.GEMINI_MODEL,
  GEMINI_REVIEW_MODEL: process.env.GEMINI_REVIEW_MODEL,
  GOOGLE_API_KEY: process.env.GOOGLE_API_KEY,
  OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY,
  OPENROUTER_BASE_URL: process.env.OPENROUTER_BASE_URL,
  OPENROUTER_MODEL: process.env.OPENROUTER_MODEL,
  OPENROUTER_REVIEW_MODEL: process.env.OPENROUTER_REVIEW_MODEL,
  OLLAMA_BASE_URL: process.env.OLLAMA_BASE_URL,
  OLLAMA_MODEL: process.env.OLLAMA_MODEL,
  FUNCTION_ANALYSIS_MAX_DEPTH: process.env.FUNCTION_ANALYSIS_MAX_DEPTH,
  KEY_SUB_FUNCTION_LIMIT: process.env.KEY_SUB_FUNCTION_LIMIT,
  GITHUB_TOKEN: process.env.GITHUB_TOKEN,
  TAB3_DEFAULT_GITHUB_TOKEN: process.env.TAB3_DEFAULT_GITHUB_TOKEN,
  TAB3_EMBEDDED: process.env.TAB3_EMBEDDED,
  TAB3_DISABLE_LOCAL_PROJECT: process.env.TAB3_DISABLE_LOCAL_PROJECT,
};

const LEGACY_COMPATIBLE_ENV = {
  apiKey: ['DEEPSEEK_API_KEY', 'OPENAI_API_KEY'],
  baseUrl: ['DEEPSEEK_BASE_URL', 'OPENAI_BASE_URL'],
  model: ['DEEPSEEK_MODEL', 'OPENAI_MODEL'],
  reviewModel: ['DEEPSEEK_REVIEW_MODEL', 'OPENAI_REVIEW_MODEL'],
};

export const AI_PROVIDER_OPTIONS: AIProviderDefinition[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    description: 'OpenAI 兼容接口，适合当前默认接法。',
    transport: 'openai-compatible',
    defaultBaseUrl: 'https://api.deepseek.com',
    defaultModel: 'deepseek-chat',
    env: {
      apiKey: ['DEEPSEEK_API_KEY'],
      baseUrl: ['DEEPSEEK_BASE_URL'],
      model: ['DEEPSEEK_MODEL'],
      reviewModel: ['DEEPSEEK_REVIEW_MODEL'],
    },
  },
  {
    id: 'openai',
    label: 'OpenAI',
    description: 'OpenAI 官方 Chat Completions 接口。',
    transport: 'openai-compatible',
    defaultBaseUrl: 'https://api.openai.com/v1',
    defaultModel: 'gpt-4o-mini',
    env: {
      apiKey: ['OPENAI_API_KEY'],
      baseUrl: ['OPENAI_BASE_URL'],
      model: ['OPENAI_MODEL'],
      reviewModel: ['OPENAI_REVIEW_MODEL'],
    },
  },
  {
    id: 'anthropic',
    label: 'Anthropic Claude',
    description: 'Anthropic 官方 Messages API。',
    transport: 'anthropic',
    defaultBaseUrl: 'https://api.anthropic.com',
    defaultModel: 'claude-3-5-sonnet-latest',
    env: {
      apiKey: ['ANTHROPIC_API_KEY'],
      baseUrl: ['ANTHROPIC_BASE_URL'],
      model: ['ANTHROPIC_MODEL'],
      reviewModel: ['ANTHROPIC_REVIEW_MODEL'],
    },
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    description: 'Google Gemini 官方 generateContent 接口。',
    transport: 'gemini',
    defaultBaseUrl: 'https://generativelanguage.googleapis.com/v1beta',
    defaultModel: 'gemini-2.5-flash',
    env: {
      apiKey: ['GEMINI_API_KEY', 'GOOGLE_API_KEY'],
      baseUrl: ['GEMINI_BASE_URL'],
      model: ['GEMINI_MODEL'],
      reviewModel: ['GEMINI_REVIEW_MODEL'],
    },
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    description: 'OpenAI 兼容接口，可路由多模型。',
    transport: 'openai-compatible',
    defaultBaseUrl: 'https://openrouter.ai/api/v1',
    defaultModel: '',
    env: {
      apiKey: ['OPENROUTER_API_KEY'],
      baseUrl: ['OPENROUTER_BASE_URL'],
      model: ['OPENROUTER_MODEL'],
      reviewModel: ['OPENROUTER_REVIEW_MODEL'],
    },
  },
  {
    id: 'ollama',
    label: 'Ollama',
    description: '本地 OpenAI 兼容接口，适合本地模型。',
    transport: 'openai-compatible',
    defaultBaseUrl: 'http://localhost:11434/v1',
    defaultModel: 'llama3.1',
    env: {
      apiKey: [],
      baseUrl: ['OLLAMA_BASE_URL'],
      model: ['OLLAMA_MODEL'],
      reviewModel: [],
    },
  },
  {
    id: 'compatible',
    label: 'OpenAI-Compatible',
    description: '适用于 Qwen、Kimi、GLM、Ark 等兼容 Chat Completions 的接口。',
    transport: 'openai-compatible',
    defaultBaseUrl: '',
    defaultModel: '',
    env: {
      apiKey: ['AI_API_KEY'],
      baseUrl: ['AI_BASE_URL'],
      model: ['AI_MODEL'],
      reviewModel: ['AI_REVIEW_MODEL'],
    },
  },
];

const DEFAULT_PROVIDER_ID: AIProviderId = 'deepseek';

function parseBooleanFlag(value: unknown) {
  const normalized = String(value ?? '').trim().toLowerCase();
  return normalized === '1' || normalized === 'true' || normalized === 'yes' || normalized === 'on';
}

export function getEmbeddedRuntimeConfig(): EmbeddedRuntimeConfig {
  const runtimeConfig = typeof window !== 'undefined' ? window.__NIGHTSHIFT_TAB3_CONFIG__ : undefined;

  return {
    embedded: parseBooleanFlag(runtimeConfig?.embedded ?? ENV_VALUES.TAB3_EMBEDDED),
    disableLocalProject: parseBooleanFlag(
      runtimeConfig?.disableLocalProject ?? ENV_VALUES.TAB3_DISABLE_LOCAL_PROJECT,
    ),
    defaultGithubToken: String(
      runtimeConfig?.defaultGithubToken ?? ENV_VALUES.TAB3_DEFAULT_GITHUB_TOKEN ?? '',
    ).trim(),
  };
}

function getStorage() {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readRawStorageSettings() {
  const storage = getStorage();
  if (!storage) {
    return null;
  }

  const keys = [STORAGE_KEY, LEGACY_STORAGE_KEY];
  for (const key of keys) {
    try {
      const raw = storage.getItem(key);
      if (!raw) {
        continue;
      }

      const parsed = JSON.parse(raw);
      if (typeof parsed === 'object' && parsed) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      continue;
    }
  }

  return null;
}

function hasStoredKey(rawValue: Record<string, unknown> | null, key: keyof AppSettings) {
  return Boolean(rawValue && Object.prototype.hasOwnProperty.call(rawValue, key));
}

function writeSettings(values: AppSettings) {
  const storage = getStorage();
  if (!storage) {
    return;
  }

  storage.setItem(STORAGE_KEY, JSON.stringify(values));
  storage.removeItem(LEGACY_STORAGE_KEY);
}

function dispatchSettingsChanged() {
  if (typeof window === 'undefined') {
    return;
  }

  window.dispatchEvent(new CustomEvent(SETTINGS_CHANGE_EVENT));
}

function parsePositiveInteger(value: unknown, fallback: number) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeProviderId(value: unknown): AIProviderId {
  const normalized = String(value || '').trim().toLowerCase();

  switch (normalized) {
    case 'deepseek':
      return 'deepseek';
    case 'openai':
      return 'openai';
    case 'anthropic':
    case 'claude':
      return 'anthropic';
    case 'gemini':
    case 'google':
    case 'google-gemini':
      return 'gemini';
    case 'openrouter':
      return 'openrouter';
    case 'ollama':
      return 'ollama';
    case 'compatible':
    case 'openai-compatible':
    case 'custom':
      return 'compatible';
    default:
      return DEFAULT_PROVIDER_ID;
  }
}

export function getAIProviderDefinition(providerId: AIProviderId) {
  return AI_PROVIDER_OPTIONS.find((provider) => provider.id === providerId)
    || AI_PROVIDER_OPTIONS[0];
}

function normalizeStoredSettings(value: Record<string, unknown> | null): AppSettings {
  return {
    aiProvider: normalizeProviderId(value?.aiProvider),
    aiBaseUrl: typeof value?.aiBaseUrl === 'string' ? value.aiBaseUrl.trim() : '',
    aiApiKey: typeof value?.aiApiKey === 'string' ? value.aiApiKey.trim() : '',
    aiModel: typeof value?.aiModel === 'string' ? value.aiModel.trim() : '',
    githubToken: typeof value?.githubToken === 'string' ? value.githubToken.trim() : '',
    maxDrillDepth: parsePositiveInteger(value?.maxDrillDepth, 2),
    keySubFunctionCount: parsePositiveInteger(value?.keySubFunctionCount, 10),
  };
}

function readEnvByNames(names: string[]) {
  for (const name of names) {
    const value = (ENV_VALUES[name] || '').trim();
    if (value) {
      return {
        envName: name,
        value,
      };
    }
  }

  return null;
}

function inferProviderFromEnv() {
  const providerEvidence: Array<{ provider: AIProviderId; envNames: string[] }> = [
    { provider: 'anthropic', envNames: ['ANTHROPIC_API_KEY', 'ANTHROPIC_MODEL', 'ANTHROPIC_BASE_URL'] },
    { provider: 'gemini', envNames: ['GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_MODEL', 'GEMINI_BASE_URL'] },
    { provider: 'openrouter', envNames: ['OPENROUTER_API_KEY', 'OPENROUTER_MODEL', 'OPENROUTER_BASE_URL'] },
    { provider: 'ollama', envNames: ['OLLAMA_BASE_URL', 'OLLAMA_MODEL'] },
    { provider: 'deepseek', envNames: ['DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL', 'DEEPSEEK_BASE_URL'] },
    { provider: 'openai', envNames: ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_BASE_URL'] },
    { provider: 'compatible', envNames: ['AI_API_KEY', 'AI_MODEL', 'AI_BASE_URL'] },
  ];

  for (const candidate of providerEvidence) {
    const matched = readEnvByNames(candidate.envNames);
    if (matched) {
      return {
        provider: candidate.provider,
        envName: matched.envName,
        envValue: matched.value,
      };
    }
  }

  return null;
}

function buildProviderField(storedValues: AppSettings): AppSettingsFieldResolution<'aiProvider'> {
  const rawStored = readRawStorageSettings();
  const storedValue = storedValues.aiProvider;
  const hasStoredValue = hasStoredKey(rawStored, 'aiProvider');
  const explicitEnv = readEnvByNames(['AI_PROVIDER']);
  if (explicitEnv) {
    return {
      key: 'aiProvider',
      value: normalizeProviderId(explicitEnv.value),
      source: 'env',
      storedValue,
      hasStoredValue,
      envName: explicitEnv.envName,
      envValue: explicitEnv.value,
    };
  }

  const inferredEnv = inferProviderFromEnv();
  if (inferredEnv) {
    return {
      key: 'aiProvider',
      value: inferredEnv.provider,
      source: 'env',
      storedValue,
      hasStoredValue,
      envName: inferredEnv.envName,
      envValue: inferredEnv.envValue,
    };
  }

  if (hasStoredValue) {
    return {
      key: 'aiProvider',
      value: storedValues.aiProvider,
      source: 'storage',
      storedValue,
      hasStoredValue,
    };
  }

  return {
    key: 'aiProvider',
    value: DEFAULT_PROVIDER_ID,
    source: 'default',
    storedValue,
    hasStoredValue,
  };
}

function buildStringFieldResolution<T extends 'aiBaseUrl' | 'aiApiKey' | 'aiModel' | 'githubToken'>(
  key: T,
  storedValue: AppSettings[T],
  hasStoredValue: boolean,
  defaultValue: AppSettings[T],
  candidateEnvNames: string[],
): AppSettingsFieldResolution<T> {
  const envValue = readEnvByNames(candidateEnvNames);
  if (envValue) {
    return {
      key,
      value: envValue.value as AppSettings[T],
      source: 'env',
      storedValue,
      hasStoredValue,
      envName: envValue.envName,
      envValue: envValue.value,
    };
  }

  if (hasStoredValue) {
    return {
      key,
      value: storedValue,
      source: 'storage',
      storedValue,
      hasStoredValue,
    };
  }

  return {
    key,
    value: defaultValue,
    source: 'default',
    storedValue,
    hasStoredValue,
  };
}

function buildGithubTokenFieldResolution(
  storedValue: AppSettings['githubToken'],
  hasStoredValue: boolean,
): AppSettingsFieldResolution<'githubToken'> {
  const envValue = readEnvByNames(['GITHUB_TOKEN']);
  if (envValue) {
    return {
      key: 'githubToken',
      value: envValue.value,
      source: 'env',
      storedValue,
      hasStoredValue,
      envName: envValue.envName,
      envValue: envValue.value,
    };
  }

  if (storedValue.trim()) {
    return {
      key: 'githubToken',
      value: storedValue,
      source: 'storage',
      storedValue,
      hasStoredValue,
    };
  }

  const embeddedRuntimeConfig = getEmbeddedRuntimeConfig();
  if (embeddedRuntimeConfig.defaultGithubToken) {
    return {
      key: 'githubToken',
      value: embeddedRuntimeConfig.defaultGithubToken,
      source: 'embedded',
      storedValue,
      hasStoredValue,
    };
  }

  return {
    key: 'githubToken',
    value: '',
    source: 'default',
    storedValue,
    hasStoredValue,
  };
}

function buildNumberFieldResolution<T extends 'maxDrillDepth' | 'keySubFunctionCount'>(
  key: T,
  storedValue: AppSettings[T],
  hasStoredValue: boolean,
  defaultValue: AppSettings[T],
  envNames: string[],
): AppSettingsFieldResolution<T> {
  const envValue = readEnvByNames(envNames);
  if (envValue) {
    return {
      key,
      value: parsePositiveInteger(envValue.value, defaultValue) as AppSettings[T],
      source: 'env',
      storedValue,
      hasStoredValue,
      envName: envValue.envName,
      envValue: envValue.value,
    };
  }

  if (hasStoredValue) {
    return {
      key,
      value: storedValue,
      source: 'storage',
      storedValue,
      hasStoredValue,
    };
  }

  return {
    key,
    value: defaultValue,
    source: 'default',
    storedValue,
    hasStoredValue,
  };
}

function buildReviewModelCandidateNames(provider: AIProviderDefinition) {
  const candidateNames = ['AI_REVIEW_MODEL', ...provider.env.reviewModel];
  if (provider.transport === 'openai-compatible') {
    candidateNames.push(...LEGACY_COMPATIBLE_ENV.reviewModel);
  }
  return [...new Set(candidateNames)];
}

export function getResolvedAppSettings(): ResolvedAppSettings {
  const rawStoredSettings = readRawStorageSettings();
  const storedValues = normalizeStoredSettings(rawStoredSettings);
  const providerField = buildProviderField(storedValues);
  const provider = getAIProviderDefinition(providerField.value);

  const apiKeyField = buildStringFieldResolution(
    'aiApiKey',
    storedValues.aiApiKey,
    hasStoredKey(rawStoredSettings, 'aiApiKey'),
    '',
    [
      'AI_API_KEY',
      ...provider.env.apiKey,
      ...(provider.transport === 'openai-compatible' ? LEGACY_COMPATIBLE_ENV.apiKey : []),
    ],
  );
  const baseUrlField = buildStringFieldResolution(
    'aiBaseUrl',
    storedValues.aiBaseUrl,
    hasStoredKey(rawStoredSettings, 'aiBaseUrl'),
    provider.defaultBaseUrl,
    [
      'AI_BASE_URL',
      ...provider.env.baseUrl,
      ...(provider.transport === 'openai-compatible' ? LEGACY_COMPATIBLE_ENV.baseUrl : []),
    ],
  );
  const modelField = buildStringFieldResolution(
    'aiModel',
    storedValues.aiModel,
    hasStoredKey(rawStoredSettings, 'aiModel'),
    provider.defaultModel,
    [
      'AI_MODEL',
      ...provider.env.model,
      ...(provider.transport === 'openai-compatible' ? LEGACY_COMPATIBLE_ENV.model : []),
    ],
  );
  const githubTokenField = buildGithubTokenFieldResolution(
    storedValues.githubToken,
    hasStoredKey(rawStoredSettings, 'githubToken'),
  );
  const maxDrillDepthField = buildNumberFieldResolution(
    'maxDrillDepth',
    storedValues.maxDrillDepth,
    hasStoredKey(rawStoredSettings, 'maxDrillDepth'),
    2,
    ['FUNCTION_ANALYSIS_MAX_DEPTH'],
  );
  const keySubFunctionCountField = buildNumberFieldResolution(
    'keySubFunctionCount',
    storedValues.keySubFunctionCount,
    hasStoredKey(rawStoredSettings, 'keySubFunctionCount'),
    10,
    ['KEY_SUB_FUNCTION_LIMIT'],
  );

  return {
    values: {
      aiProvider: providerField.value,
      aiBaseUrl: baseUrlField.value,
      aiApiKey: apiKeyField.value,
      aiModel: modelField.value,
      githubToken: githubTokenField.value,
      maxDrillDepth: maxDrillDepthField.value,
      keySubFunctionCount: keySubFunctionCountField.value,
    },
    storedValues,
    fields: {
      aiProvider: providerField,
      aiBaseUrl: baseUrlField,
      aiApiKey: apiKeyField,
      aiModel: modelField,
      githubToken: githubTokenField,
      maxDrillDepth: maxDrillDepthField,
      keySubFunctionCount: keySubFunctionCountField,
    },
  };
}

export function saveAppSettings(input: AppSettings) {
  const provider = getAIProviderDefinition(normalizeProviderId(input.aiProvider));
  const sanitized: AppSettings = {
    aiProvider: provider.id,
    aiBaseUrl: input.aiBaseUrl.trim() || provider.defaultBaseUrl,
    aiApiKey: input.aiApiKey.trim(),
    aiModel: input.aiModel.trim() || provider.defaultModel,
    githubToken: input.githubToken.trim(),
    maxDrillDepth: parsePositiveInteger(input.maxDrillDepth, 2),
    keySubFunctionCount: parsePositiveInteger(input.keySubFunctionCount, 10),
  };

  writeSettings(sanitized);
  dispatchSettingsChanged();
  return getResolvedAppSettings();
}

export function syncAppSettingsWithEnv() {
  const storage = getStorage();
  if (storage && !storage.getItem(STORAGE_KEY) && storage.getItem(LEGACY_STORAGE_KEY)) {
    const legacyValues = normalizeStoredSettings(readRawStorageSettings());
    writeSettings(legacyValues);
  }
  return getResolvedAppSettings();
}

export function getRuntimeAiSettings(): RuntimeAiSettings {
  const resolved = getResolvedAppSettings();
  const provider = getAIProviderDefinition(resolved.values.aiProvider);
  const reviewModelEnv = readEnvByNames(buildReviewModelCandidateNames(provider));

  return {
    provider,
    apiKey: resolved.values.aiApiKey,
    baseUrl: resolved.values.aiBaseUrl.replace(/\/+$/, ''),
    model: resolved.values.aiModel,
    reviewModel: reviewModelEnv?.value || resolved.values.aiModel,
  };
}

export function getGithubToken() {
  return getResolvedAppSettings().values.githubToken;
}

export function getMaxDrillDepth() {
  return getResolvedAppSettings().values.maxDrillDepth;
}

export function getKeySubFunctionCount() {
  return getResolvedAppSettings().values.keySubFunctionCount;
}

export function subscribeAppSettings(listener: () => void) {
  if (typeof window === 'undefined') {
    return () => {};
  }

  const handler = () => listener();
  window.addEventListener(SETTINGS_CHANGE_EVENT, handler);
  window.addEventListener('storage', handler);

  return () => {
    window.removeEventListener(SETTINGS_CHANGE_EVENT, handler);
    window.removeEventListener('storage', handler);
  };
}
