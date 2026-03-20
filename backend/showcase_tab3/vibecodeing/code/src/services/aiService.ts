import type { AIUsageStats } from '../types/log';
import type { FunctionBridgeInfo, FunctionRouteInfo } from '../types/functionFlow';
import { getKeySubFunctionCount, getRuntimeAiSettings } from './appSettings';
import { normalizeFunctionName } from './functionSearch';

type JsonSchema = Record<string, unknown>;

interface StructuredResult<T> {
  result: T;
  raw: {
    request: Record<string, unknown>;
    response: unknown;
    filteredFiles?: string[];
    usage?: AIUsageStats;
  };
}

export interface AIAnalysisResult {
  languages: string[];
  techStack: string[];
  entryPoints: string[];
  summary: string;
}

export interface EntryPointVerification {
  isEntryPoint: boolean;
  reason: string;
}

export interface SubFunction {
  name: string;
  filePath: string;
  summary: string;
  drillDown: -1 | 0 | 1;
  receiver?: string;
  callExpression?: string;
  route?: FunctionRouteInfo | null;
  bridge?: FunctionBridgeInfo | null;
}

export interface SubFunctionAnalysis {
  functions: SubFunction[];
}

export interface FunctionFileGuessResult {
  candidatePaths: string[];
  likelyExternal: boolean;
  reason: string;
}

export interface ModuleClassificationModule {
  name: string;
  summary: string;
  nodeIds: string[];
}

export interface ModuleClassificationResult {
  modules: ModuleClassificationModule[];
}

interface ChatCompletionApiResult {
  choices?: Array<{
    message?: {
      content?:
        | string
        | Array<{
            type?: string;
            text?: string;
          }>;
    };
  }>;
  error?: {
    message?: string;
  };
  usage?: Record<string, unknown>;
}

interface AnthropicMessageApiResult {
  content?: Array<{
    type?: string;
    text?: string;
  }>;
  error?: {
    message?: string;
  };
  usage?: {
    input_tokens?: number;
    output_tokens?: number;
  };
}

interface GeminiGenerateContentResult {
  candidates?: Array<{
    content?: {
      parts?: Array<{
        text?: string;
      }>;
    };
  }>;
  error?: {
    message?: string;
  };
  usageMetadata?: Record<string, unknown>;
}

const ANALYSIS_SCHEMA: JsonSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    languages: {
      type: 'array',
      items: { type: 'string' },
    },
    techStack: {
      type: 'array',
      items: { type: 'string' },
    },
    entryPoints: {
      type: 'array',
      items: { type: 'string' },
    },
    summary: { type: 'string' },
  },
  required: ['languages', 'techStack', 'entryPoints', 'summary'],
};

const ENTRY_POINT_SCHEMA: JsonSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    isEntryPoint: { type: 'boolean' },
    reason: { type: 'string' },
  },
  required: ['isEntryPoint', 'reason'],
};

const SUB_FUNCTION_SCHEMA: JsonSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    functions: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          name: { type: 'string' },
          filePath: { type: 'string' },
          summary: { type: 'string' },
          drillDown: {
            type: 'integer',
            enum: [-1, 0, 1],
          },
        },
        required: ['name', 'filePath', 'summary', 'drillDown'],
      },
    },
  },
  required: ['functions'],
};

const FUNCTION_FILE_GUESS_SCHEMA: JsonSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    candidatePaths: {
      type: 'array',
      items: { type: 'string' },
    },
    likelyExternal: {
      type: 'boolean',
    },
    reason: {
      type: 'string',
    },
  },
  required: ['candidatePaths', 'likelyExternal', 'reason'],
};

const MODULE_CLASSIFICATION_SCHEMA: JsonSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    modules: {
      type: 'array',
      maxItems: 10,
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          name: { type: 'string' },
          summary: { type: 'string' },
          nodeIds: {
            type: 'array',
            items: { type: 'string' },
          },
        },
        required: ['name', 'summary', 'nodeIds'],
      },
    },
  },
  required: ['modules'],
};

export const CODE_EXTENSIONS = [
  '.js',
  '.jsx',
  '.ts',
  '.tsx',
  '.py',
  '.c',
  '.cpp',
  '.h',
  '.hpp',
  '.go',
  '.rs',
  '.java',
  '.rb',
  '.php',
  '.swift',
  '.kt',
  '.cs',
  '.html',
  '.css',
  '.scss',
  '.sql',
  '.sh',
  '.yml',
  '.yaml',
  '.json',
];

function ensureApiKey() {
  const runtime = getRuntimeAiSettings();
  if (runtime.provider.id !== 'ollama' && !runtime.apiKey) {
    throw new Error('Missing AI API key. Please set it in the settings panel or provide an environment variable.');
  }
}

function extractOpenAICompatibleText(response: ChatCompletionApiResult): string {
  const content = response.choices?.[0]?.message?.content;
  if (typeof content === 'string') {
    return content.trim();
  }

  if (Array.isArray(content)) {
    return content
      .map((item) => item.text || '')
      .join('\n')
      .trim();
  }

  return '';
}

function extractAnthropicText(response: AnthropicMessageApiResult): string {
  return (response.content || [])
    .filter((item) => item.type === 'text')
    .map((item) => item.text || '')
    .join('\n')
    .trim();
}

function extractGeminiText(response: GeminiGenerateContentResult): string {
  return (response.candidates?.[0]?.content?.parts || [])
    .map((part) => part.text || '')
    .join('\n')
    .trim();
}

function sanitizeCallableName(rawName: string) {
  return rawName
    .trim()
    .replace(/[`"'“”‘’]/g, '')
    .replace(/[`"'“”‘’]/g, '')
    .replace(/[`"'“”‘’]/g, '');
}

function isTransientReceiver(receiver: string) {
  return /^(this|self|super|cls|prototype|window|global|globalThis|module|exports|ctx|req|res|app)$/i.test(receiver.trim());
}

function isMeaningfulReceiver(receiver: string) {
  const trimmed = receiver.trim();
  return (
    /^[A-Z][A-Za-z0-9_$]*$/.test(trimmed) ||
    /(service|controller|manager|store|client|repository|repo|provider|handler|parser|builder|factory|engine|module|model)$/i.test(trimmed)
  );
}

function parseCallableReference(rawName: string): {
  name: string;
  receiver?: string;
  callExpression?: string;
} {
  const callExpression = sanitizeCallableName(rawName);
  const normalizedName = normalizeFunctionName(callExpression) || rawName.trim();

  if (callExpression.includes('::') || callExpression.includes('.:')) {
    const segments = callExpression.split(/::|\.\:/).map((segment) => segment.trim()).filter(Boolean);
    const receiver = segments.length > 1 ? segments[segments.length - 2] : undefined;
    return {
      name: callExpression,
      receiver,
      callExpression: callExpression !== rawName.trim() ? callExpression : undefined,
    };
  }

  const accessorMatch = callExpression.match(/^(.*?)(\?\.|\.|->|#)([A-Za-z_$][A-Za-z0-9_$]*)$/);
  const receiver = accessorMatch?.[1]?.trim();
  if (!receiver) {
    return {
      name: normalizedName,
      callExpression: callExpression !== normalizedName ? callExpression : undefined,
    };
  }

  const normalizedReceiver = normalizeFunctionName(receiver) || receiver;
  const shouldKeepReceiver = !isTransientReceiver(normalizedReceiver) && isMeaningfulReceiver(normalizedReceiver);

  return {
    name: shouldKeepReceiver ? `${normalizedReceiver}.${normalizedName}` : normalizedName,
    receiver: normalizedReceiver,
    callExpression: callExpression !== normalizedName ? callExpression : undefined,
  };
}

function normalizeSubFunction(subFunction: SubFunction): SubFunction {
  const callable = parseCallableReference(subFunction.name);
  const receiverNote =
    callable.receiver && !subFunction.summary.includes(callable.receiver)
      ? ` (璋冪敤瀹夸富: ${callable.receiver})`
      : '';

  return {
    ...subFunction,
    name: callable.name,
    receiver: callable.receiver,
    callExpression: callable.callExpression,
    summary: `${subFunction.summary}${receiverNote}`,
  };
}

function parseStructuredJson<T>(text: string): T {
  try {
    return JSON.parse(text) as T;
  } catch {
    const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (fenced?.[1]) {
      return JSON.parse(fenced[1]) as T;
    }

    const firstBrace = text.indexOf('{');
    const lastBrace = text.lastIndexOf('}');
    if (firstBrace !== -1 && lastBrace !== -1 && lastBrace > firstBrace) {
      return JSON.parse(text.slice(firstBrace, lastBrace + 1)) as T;
    }

    throw new Error('Model returned invalid JSON.');
  }
}

function readUsageNumber(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

function extractUsageStats(response: Record<string, unknown> | ChatCompletionApiResult): AIUsageStats | undefined {
  const anthropicUsage = (response as AnthropicMessageApiResult).usage;
  if (anthropicUsage && typeof anthropicUsage === 'object') {
    const inputTokens = readUsageNumber(anthropicUsage.input_tokens);
    const outputTokens = readUsageNumber(anthropicUsage.output_tokens);
    const totalTokens = inputTokens + outputTokens;

    if (totalTokens > 0) {
      return {
        inputTokens,
        outputTokens,
        totalTokens,
      };
    }
  }

  const geminiUsage = (response as GeminiGenerateContentResult).usageMetadata;
  if (geminiUsage && typeof geminiUsage === 'object') {
    const inputTokens = readUsageNumber(
      geminiUsage.promptTokenCount ?? geminiUsage.prompt_token_count,
    );
    const outputTokens = readUsageNumber(
      geminiUsage.candidatesTokenCount ?? geminiUsage.candidates_token_count,
    );
    const totalTokens = readUsageNumber(
      geminiUsage.totalTokenCount ?? geminiUsage.total_token_count,
    ) || (inputTokens + outputTokens);

    if (totalTokens > 0) {
      return {
        inputTokens,
        outputTokens,
        totalTokens,
      };
    }
  }

  const usage = (response as ChatCompletionApiResult).usage;
  if (!usage || typeof usage !== 'object') {
    return undefined;
  }

  const inputTokens = readUsageNumber(
    usage.prompt_tokens ?? usage.input_tokens ?? usage.promptTokens ?? usage.inputTokens,
  );
  const outputTokens = readUsageNumber(
    usage.completion_tokens ?? usage.output_tokens ?? usage.completionTokens ?? usage.outputTokens,
  );
  const totalTokens = readUsageNumber(usage.total_tokens ?? usage.totalTokens) || (inputTokens + outputTokens);

  if (inputTokens === 0 && outputTokens === 0 && totalTokens === 0) {
    return undefined;
  }

  return {
    inputTokens,
    outputTokens,
    totalTokens,
  };
}

function buildOpenAICompatibleEndpoint(baseUrl: string) {
  const normalized = baseUrl.replace(/\/+$/, '');
  return normalized.endsWith('/chat/completions') ? normalized : `${normalized}/chat/completions`;
}

function buildAnthropicEndpoint(baseUrl: string) {
  const normalized = baseUrl.replace(/\/+$/, '');
  if (normalized.endsWith('/messages')) {
    return normalized;
  }
  return normalized.endsWith('/v1') ? `${normalized}/messages` : `${normalized}/v1/messages`;
}

function buildGeminiEndpoint(baseUrl: string, model: string) {
  const normalized = baseUrl.replace(/\/+$/, '');
  if (normalized.includes(':generateContent')) {
    return normalized;
  }
  return `${normalized}/models/${encodeURIComponent(model)}:generateContent`;
}

async function callStructuredModel<T>(
  model: string,
  schemaName: string,
  schema: JsonSchema,
  prompt: string,
  filteredFiles?: string[],
): Promise<StructuredResult<T>> {
  ensureApiKey();
  const runtime = getRuntimeAiSettings();
  if (!model.trim()) {
    throw new Error('Missing AI model name. Please set it in the settings panel first.');
  }
  if (!runtime.baseUrl.trim()) {
    throw new Error('Missing AI base URL. Please set it in the settings panel first.');
  }

  const systemPrompt = [
    'You are a precise software-analysis assistant.',
    'Return exactly one valid JSON object.',
    'Do not return markdown fences, prose, or explanations.',
    `The JSON must match the schema named "${schemaName}" exactly:`,
    JSON.stringify(schema, null, 2),
  ].join('\n');

  let endpoint = '';
  let requestBody: Record<string, unknown> = {};
  let requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  switch (runtime.provider.transport) {
    case 'anthropic':
      endpoint = buildAnthropicEndpoint(runtime.baseUrl);
      requestHeaders = {
        ...requestHeaders,
        'x-api-key': runtime.apiKey,
        'anthropic-version': '2023-06-01',
      };
      requestBody = {
        model,
        max_tokens: 4096,
        temperature: 0.1,
        system: systemPrompt,
        messages: [
          {
            role: 'user',
            content: prompt,
          },
        ],
      };
      break;
    case 'gemini':
      endpoint = buildGeminiEndpoint(runtime.baseUrl, model);
      requestHeaders = {
        ...requestHeaders,
        'x-goog-api-key': runtime.apiKey,
      };
      requestBody = {
        system_instruction: {
          parts: [{ text: systemPrompt }],
        },
        contents: [
          {
            role: 'user',
            parts: [{ text: prompt }],
          },
        ],
        generationConfig: {
          temperature: 0.1,
        },
      };
      break;
    case 'openai-compatible':
    default:
      endpoint = buildOpenAICompatibleEndpoint(runtime.baseUrl);
      if (runtime.apiKey) {
        requestHeaders.Authorization = `Bearer ${runtime.apiKey}`;
      }
      requestBody = {
        model,
        messages: [
          {
            role: 'system',
            content: systemPrompt,
          },
          {
            role: 'user',
            content: prompt,
          },
        ],
        response_format: {
          type: 'json_object',
        },
        temperature: 0.1,
      };
      break;
  }

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: requestHeaders,
    body: JSON.stringify(requestBody),
  });

  let responseData: ChatCompletionApiResult | AnthropicMessageApiResult | GeminiGenerateContentResult | Record<string, unknown>;
  try {
    responseData = await response.json();
  } catch {
    const text = await response.text();
    throw new Error(`Model API returned non-JSON output: ${text}`);
  }

  if (!response.ok) {
    const message =
      (responseData as ChatCompletionApiResult)?.error?.message ||
      (responseData as AnthropicMessageApiResult)?.error?.message ||
      (responseData as GeminiGenerateContentResult)?.error?.message ||
      `${response.status} ${response.statusText}`;
    throw new Error(message);
  }

  const outputText =
    runtime.provider.transport === 'anthropic'
      ? extractAnthropicText(responseData as AnthropicMessageApiResult)
      : runtime.provider.transport === 'gemini'
        ? extractGeminiText(responseData as GeminiGenerateContentResult)
        : extractOpenAICompatibleText(responseData as ChatCompletionApiResult);
  if (!outputText) {
    throw new Error('Model returned an empty response.');
  }

  return {
    result: parseStructuredJson<T>(outputText),
    raw: {
      request: {
        url: endpoint,
        body: requestBody,
      },
      response: responseData,
      filteredFiles,
      usage: extractUsageStats(responseData),
    },
  };
}

export async function analyzeProjectWithAI(
  filePaths: string[],
): Promise<StructuredResult<AIAnalysisResult>> {
  const runtime = getRuntimeAiSettings();
  const codeFiles = filePaths
    .filter((path) => CODE_EXTENSIONS.some((ext) => path.toLowerCase().endsWith(ext)))
    .slice(0, 500);

  const prompt = [
    'Analyze the repository file list below and return JSON only.',
    'Use Chinese text for the summary field.',
    '',
    'Repository files:',
    codeFiles.join('\n'),
    '',
    'Return:',
    '1. Primary programming languages',
    '2. Main tech stack',
    '3. Most likely entry-point files',
    '4. One-sentence repository summary',
  ].join('\n');

  return callStructuredModel<AIAnalysisResult>(
    runtime.model,
    'project_analysis',
    ANALYSIS_SCHEMA,
    prompt,
    codeFiles,
  );
}

export async function verifyEntryPoint(
  githubUrl: string,
  summary: string,
  languages: string[],
  filePath: string,
  content: string,
): Promise<StructuredResult<EntryPointVerification>> {
  const runtime = getRuntimeAiSettings();
  const prompt = [
    'Decide whether the file below is a primary project entry point.',
    'Return JSON only. Use Chinese text in the reason field.',
    '',
    `Repository URL: ${githubUrl}`,
    `Project summary: ${summary}`,
    `Languages: ${languages.join(', ')}`,
    `File path: ${filePath}`,
    '',
    'File content:',
    content,
    '',
    'An entry point usually starts the app, assembles the runtime, or launches the main execution flow.',
  ].join('\n');

  return callStructuredModel<EntryPointVerification>(
    runtime.reviewModel,
    'entry_point_verification',
    ENTRY_POINT_SCHEMA,
    prompt,
  );
}

export async function identifySubFunctions(
  summary: string,
  languages: string[],
  filePaths: string[],
  functionName: string,
  filePath: string,
  content: string,
): Promise<StructuredResult<SubFunctionAnalysis>> {
  const runtime = getRuntimeAiSettings();
  const keySubFunctionCount = getKeySubFunctionCount();
  const prompt = [
    'Analyze the current function or file and identify only the sub-function calls that are central to the repository core workflow.',
    'Return JSON only. Use Chinese text in the summary field.',
    '',
    `Project summary: ${summary}`,
    `Languages: ${languages.join(', ') || '(unknown)'}`,
    'Repository file list:',
    filePaths.slice(0, 1000).join('\n'),
    '',
    `Current analysis target: ${functionName}`,
    `Current file path: ${filePath}`,
    '',
    'Code snippet:',
    content,
    '',
    'Rules:',
    `1. Return at most ${keySubFunctionCount} key sub-functions.`,
    '2. Only include calls that materially advance the core business flow, primary control flow, orchestration flow, or critical data-processing flow.',
    '3. Do not include routine data structure operations, traversal helpers, map/list/set operations, string handling, formatting, serialization, logging, simple validation, or obvious library/framework boilerplate unless they are themselves core business logic.',
    '4. For object-oriented code, if a callee is a method and the class, namespace, or service type can be identified, name must keep that owner, such as ClassName::method or ServiceName.method.',
    '5. Do not use transient variable receivers like this.method, self.method, obj.method, or instance->method as the final name when the stable owner type is inferable.',
    '6. filePath should be the most likely repository file defining the function.',
    '7. drillDown must be -1, 0, or 1.',
    '8. Use drillDown = -1 for non-core, framework, library, built-in, or clearly unimportant functions.',
    '9. Use drillDown = 0 when the function may be worth drilling into but confidence is limited.',
    '10. Use drillDown = 1 when the function is clearly central to the call chain.',
  ].join('\n');

  const response = await callStructuredModel<SubFunctionAnalysis>(
    runtime.reviewModel,
    'sub_function_analysis',
    SUB_FUNCTION_SCHEMA,
    prompt,
  );

  return {
    ...response,
    result: {
      functions: response.result.functions
        .slice(0, keySubFunctionCount)
        .map(normalizeSubFunction),
    },
  };
}

export async function guessFunctionDefinitionFiles(
  summary: string,
  filePaths: string[],
  functionName: string,
  parentFunctionName: string,
  parentFilePath: string,
  hintedFilePath?: string,
): Promise<StructuredResult<FunctionFileGuessResult>> {
  const runtime = getRuntimeAiSettings();
  const prompt = [
    'Infer which repository files are most likely to define the target function.',
    'Return JSON only. Use Chinese text in the reason field.',
    '',
    `Project summary: ${summary}`,
    `Target callee function: ${functionName}`,
    `Parent caller function: ${parentFunctionName}`,
    `Parent caller file: ${parentFilePath}`,
    `Existing hint file: ${hintedFilePath || '(none)'}`,
    '',
    'Repository files:',
    filePaths.slice(0, 1000).join('\n'),
    '',
    'Rules:',
    '1. candidatePaths must come from the repository file list above.',
    '2. Return at most 8 candidate paths.',
    '3. If the function is probably a system function, standard library symbol, framework API, or external dependency, set likelyExternal=true and return an empty or minimal candidate list.',
    '4. Prefer files in the same module, same directory, sibling utilities, service layers, or files with matching names.',
  ].join('\n');

  return callStructuredModel<FunctionFileGuessResult>(
    runtime.reviewModel,
    'function_definition_guess',
    FUNCTION_FILE_GUESS_SCHEMA,
    prompt,
  );
}

export async function classifyFunctionModules(
  projectSummary: string,
  languages: string[],
  techStack: string[],
  nodes: Array<{
    id: string;
    name: string;
    filePath: string;
    summary: string;
    depth: number;
    parentId: string | null;
  }>,
): Promise<StructuredResult<ModuleClassificationResult>> {
  const runtime = getRuntimeAiSettings();
  const prompt = [
    'Group the repository function nodes below into high-level product or technical modules.',
    'Return JSON only. Use Chinese text for name and summary.',
    '',
    `Project summary: ${projectSummary}`,
    `Languages: ${languages.join(', ') || '(unknown)'}`,
    `Tech stack: ${techStack.join(', ') || '(unknown)'}`,
    '',
    'Function nodes:',
    JSON.stringify(nodes, null, 2),
    '',
    'Rules:',
    '1. Return at most 10 modules.',
    '2. Every nodeId must appear exactly once across all modules.',
    '3. Modules should describe cohesive functionality, not implementation layers only.',
    '4. summary should explain the module responsibility in one Chinese sentence.',
    '5. nodeIds must come from the provided node list only.',
  ].join('\n');

  return callStructuredModel<ModuleClassificationResult>(
    runtime.reviewModel,
    'function_module_classification',
    MODULE_CLASSIFICATION_SCHEMA,
    prompt,
  );
}
