import type { AIAnalysisResult } from './aiService';
import type {
  AnalysisModule,
  FunctionNode,
  ProjectAnalysisHistoryCard,
  ProjectAnalysisSaveInput,
  ProjectAnalysisSnapshot,
  StoredLogEntry,
} from '../types/analysis';
import { formatFunctionRouteLabel } from '../types/functionFlow';
import type { LogEntry } from '../types/log';

const STORAGE_KEY = 'gitvisual.project-analysis.history.v2';
const LEGACY_STORAGE_KEY = 'gitvisual.project-analysis.history.v1';
const SNAPSHOT_VERSION = 2;
const MAX_HISTORY_ITEMS = 12;

function getStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isAiResult(value: unknown): value is AIAnalysisResult {
  if (!isObject(value)) {
    return false;
  }

  return Array.isArray(value.languages)
    && Array.isArray(value.techStack)
    && Array.isArray(value.entryPoints)
    && typeof value.summary === 'string';
}

function isFunctionNode(value: unknown): value is FunctionNode {
  if (!isObject(value)) {
    return false;
  }

  const children = (value as { children?: unknown }).children;
  return typeof value.id === 'string'
    && typeof value.name === 'string'
    && typeof value.filePath === 'string'
    && typeof value.summary === 'string'
    && (children === undefined || (Array.isArray(children) && children.every(isFunctionNode)));
}

function isAnalysisModule(value: unknown): value is AnalysisModule {
  if (!isObject(value)) {
    return false;
  }

  return typeof value.id === 'string'
    && typeof value.name === 'string'
    && typeof value.summary === 'string'
    && typeof value.color === 'string'
    && Array.isArray(value.nodeIds)
    && value.nodeIds.every((nodeId) => typeof nodeId === 'string');
}

function isStoredLogEntry(value: unknown): value is StoredLogEntry {
  if (!isObject(value)) {
    return false;
  }

  return typeof value.id === 'string'
    && typeof value.timestamp === 'string'
    && typeof value.type === 'string'
    && typeof value.message === 'string';
}

function isSnapshot(value: unknown): value is ProjectAnalysisSnapshot {
  if (!isObject(value) || !isObject(value.repo)) {
    return false;
  }

  return typeof value.id === 'string'
    && typeof value.version === 'number'
    && typeof value.createdAt === 'string'
    && typeof value.updatedAt === 'string'
    && typeof value.githubUrl === 'string'
    && typeof value.repo.owner === 'string'
    && typeof value.repo.repo === 'string'
    && typeof value.repo.fullName === 'string'
    && (value.aiResult === null || isAiResult(value.aiResult))
    && Array.isArray(value.files)
    && value.files.every((file) => isObject(file) && typeof file.path === 'string' && typeof file.type === 'string')
    && (value.functionTree === null || isFunctionNode(value.functionTree))
    && Array.isArray(value.modules)
    && value.modules.every(isAnalysisModule)
    && Array.isArray(value.logs)
    && value.logs.every(isStoredLogEntry)
    && typeof value.engineeringMarkdown === 'string';
}

function compareSnapshots(left: ProjectAnalysisSnapshot, right: ProjectAnalysisSnapshot) {
  return new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime();
}

function normalizeParsedSnapshot(value: unknown): ProjectAnalysisSnapshot | null {
  if (!isObject(value) || !isObject(value.repo)) {
    return null;
  }

  if (isSnapshot(value)) {
    return value;
  }

  const looksLikeLegacySnapshot = typeof value.id === 'string'
    && typeof value.version === 'number'
    && typeof value.createdAt === 'string'
    && typeof value.updatedAt === 'string'
    && typeof value.githubUrl === 'string'
    && typeof value.repo.owner === 'string'
    && typeof value.repo.repo === 'string'
    && typeof value.repo.fullName === 'string'
    && (value.aiResult === null || isAiResult(value.aiResult))
    && Array.isArray(value.files)
    && (value.functionTree === null || isFunctionNode(value.functionTree))
    && Array.isArray(value.logs)
    && value.logs.every(isStoredLogEntry)
    && typeof value.engineeringMarkdown === 'string';

  if (!looksLikeLegacySnapshot) {
    return null;
  }

  return {
    id: value.id as string,
    version: SNAPSHOT_VERSION,
    createdAt: value.createdAt as string,
    updatedAt: value.updatedAt as string,
    githubUrl: value.githubUrl as string,
    repo: {
      owner: value.repo.owner as string,
      repo: value.repo.repo as string,
      fullName: value.repo.fullName as string,
    },
    aiResult: (value.aiResult as AIAnalysisResult | null) || null,
    files: value.files as ProjectAnalysisSnapshot['files'],
    functionTree: (value.functionTree as FunctionNode | null) || null,
    modules: [],
    logs: value.logs as StoredLogEntry[],
    engineeringMarkdown: value.engineeringMarkdown as string,
  };
}

function readSnapshotsFromKey(key: string): ProjectAnalysisSnapshot[] {
  const storage = getStorage();
  if (!storage) {
    return [];
  }

  const raw = storage.getItem(key);
  if (!raw) {
    return [];
  }

  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed
    .map(normalizeParsedSnapshot)
    .filter((snapshot): snapshot is ProjectAnalysisSnapshot => Boolean(snapshot));
}

function readSnapshots(): ProjectAnalysisSnapshot[] {
  try {
    const currentSnapshots = readSnapshotsFromKey(STORAGE_KEY);
    if (currentSnapshots.length > 0) {
      return currentSnapshots.sort(compareSnapshots);
    }

    const legacySnapshots = readSnapshotsFromKey(LEGACY_STORAGE_KEY).sort(compareSnapshots);
    if (legacySnapshots.length > 0) {
      writeSnapshots(legacySnapshots, legacySnapshots[0].id);
    }
    return legacySnapshots;
  } catch {
    return [];
  }
}

function writeSnapshots(nextSnapshots: ProjectAnalysisSnapshot[], protectedId: string): boolean {
  const storage = getStorage();
  if (!storage) {
    return false;
  }

  let snapshots = nextSnapshots.sort(compareSnapshots).slice(0, MAX_HISTORY_ITEMS);

  while (snapshots.length > 0) {
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(snapshots));
      return true;
    } catch {
      if (snapshots.length === 1 && snapshots[0]?.id === protectedId) {
        break;
      }

      let removableIndex = -1;
      for (let index = snapshots.length - 1; index >= 0; index -= 1) {
        if (snapshots[index].id !== protectedId) {
          removableIndex = index;
          break;
        }
      }

      if (removableIndex === -1) {
        break;
      }

      snapshots = snapshots.filter((_, index) => index !== removableIndex);
    }
  }

  return false;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString('zh-CN', { hour12: false });
}

function codeFileCount(aiResult: AIAnalysisResult | null, files: Array<{ path: string }>) {
  const codeExtensions = new Set([
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
  ]);

  return files.filter((file) => {
    const lowerPath = file.path.toLowerCase();
    for (const extension of codeExtensions) {
      if (lowerPath.endsWith(extension)) {
        return true;
      }
    }
    return false;
  }).length || aiResult?.entryPoints.length || 0;
}

function renderFunctionTree(node: FunctionNode | null, depth = 0): string[] {
  if (!node) {
    return ['- 无'];
  }

  const prefix = '  '.repeat(depth);
  const status = node.status || 'unknown';
  const moduleName = node.moduleName ? ` | 模块: ${node.moduleName}` : '';
  const routeLabel = formatFunctionRouteLabel(node.route);

  const lines = [
    `${prefix}- ${node.name} [${status}]${moduleName}`,
    `${prefix}  文件: ${node.filePath || '(unknown)'}`,
    `${prefix}  摘要: ${node.summary || '(none)'}`,
  ];
  if (routeLabel) {
    lines.push(`${prefix}  URL: ${routeLabel}`);
  }

  for (const child of node.children ?? []) {
    lines.push(...renderFunctionTree(child, depth + 1));
  }

  return lines;
}

function buildNodeNameMap(node: FunctionNode | null, map: Map<string, string> = new Map<string, string>()) {
  if (!node) {
    return map;
  }

  map.set(node.id, node.name);
  for (const child of node.children ?? []) {
    buildNodeNameMap(child, map);
  }

  return map;
}

function renderModules(modules: AnalysisModule[], functionTree: FunctionNode | null): string {
  if (!modules.length) {
    return '无';
  }

  const nodeNameMap = buildNodeNameMap(functionTree);

  return modules.map((module, index) => [
    `### ${index + 1}. ${module.name}`,
    `- 颜色: ${module.color}`,
    `- 简介: ${module.summary}`,
    `- 函数节点数: ${module.nodeIds.length}`,
    '- 节点列表:',
    ...module.nodeIds.map((nodeId) => `  - ${nodeNameMap.get(nodeId) || nodeId} (${nodeId})`),
  ].join('\n')).join('\n\n');
}

function collectCallChains(node: FunctionNode | null, chain: string[] = []): string[] {
  if (!node) {
    return [];
  }

  const routeLabel = formatFunctionRouteLabel(node.route);
  const routeSuffix = routeLabel ? ` | ${routeLabel}` : '';
  const nextChain = [...chain, `${node.name} (${node.filePath || 'unknown'}${routeSuffix})`];
  if (!node.children?.length) {
    return [nextChain.join(' -> ')];
  }

  return node.children.flatMap((child) => collectCallChains(child, nextChain));
}

function safeJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return JSON.stringify({ error: 'Unable to serialize log details.' }, null, 2);
  }
}

function buildEngineeringMarkdown(snapshot: Omit<ProjectAnalysisSnapshot, 'engineeringMarkdown'>): string {
  const languages = snapshot.aiResult?.languages.join(', ') || '未知';
  const techStack = snapshot.aiResult?.techStack.join(', ') || '未知';
  const entryPoints = snapshot.aiResult?.entryPoints.length ? snapshot.aiResult.entryPoints.join('\n') : '无';
  const fileList = snapshot.files.length
    ? snapshot.files.map((file) => `- ${file.path}${file.type === 'tree' ? '/' : ''}`).join('\n')
    : '- 无';
  const callChains = collectCallChains(snapshot.functionTree);
  const callChainText = callChains.length
    ? callChains.map((chain, index) => `${index + 1}. ${chain}`).join('\n')
    : '1. 无';
  const logText = snapshot.logs.length
    ? snapshot.logs.map((log, index) => {
      const details = log.details ? `\n\`\`\`json\n${safeJson(log.details)}\n\`\`\`` : '';
      return [
        `### ${index + 1}. [${log.type}] ${log.message}`,
        `- 时间: ${formatDateTime(log.timestamp)}`,
        details,
      ].join('\n');
    }).join('\n\n')
    : '无';

  return [
    '# 项目分析工程文件',
    '',
    '## 项目地址',
    '',
    `- 项目名称: ${snapshot.repo.fullName}`,
    `- GitHub 地址: ${snapshot.githubUrl}`,
    `- 工程 ID: ${snapshot.id}`,
    `- 创建时间: ${formatDateTime(snapshot.createdAt)}`,
    `- 最近更新: ${formatDateTime(snapshot.updatedAt)}`,
    '',
    '## 基本信息',
    '',
    `- 项目摘要: ${snapshot.aiResult?.summary || '暂无'}`,
    `- 编程语言: ${languages}`,
    `- 技术栈: ${techStack}`,
    `- 文件总数: ${snapshot.files.length}`,
    `- 代码文件数: ${codeFileCount(snapshot.aiResult, snapshot.files)}`,
    '',
    '## 功能模块',
    '',
    renderModules(snapshot.modules, snapshot.functionTree),
    '',
    '## 入口文件',
    '',
    '```text',
    entryPoints,
    '```',
    '',
    '## 文件列表',
    '',
    fileList,
    '',
    '## 调用链树',
    '',
    ...renderFunctionTree(snapshot.functionTree),
    '',
    '## 完整调用链',
    '',
    callChainText,
    '',
    '## Agent 工作日志',
    '',
    logText,
  ].join('\n');
}

export function serializeLogEntries(logs: LogEntry[]): StoredLogEntry[] {
  return logs.map((log) => ({
    ...log,
    timestamp: log.timestamp instanceof Date ? log.timestamp.toISOString() : new Date(log.timestamp).toISOString(),
  }));
}

export function hydrateLogEntries(logs: StoredLogEntry[]): LogEntry[] {
  return logs.map((log) => ({
    ...log,
    timestamp: new Date(log.timestamp),
  }));
}

export function buildProjectAnalysisId(owner: string, repo: string) {
  return `${owner}/${repo}`;
}

export function normalizeGithubProjectUrl(owner: string, repo: string) {
  return `https://github.com/${owner}/${repo}`;
}

export function listProjectAnalysisSnapshots() {
  return readSnapshots();
}

export function getProjectAnalysisSnapshot(id: string) {
  return readSnapshots().find((snapshot) => snapshot.id === id) || null;
}

export function listProjectAnalysisHistoryCards(): ProjectAnalysisHistoryCard[] {
  return readSnapshots().map((snapshot) => ({
    id: snapshot.id,
    githubUrl: snapshot.githubUrl,
    projectName: snapshot.repo.fullName,
    languages: snapshot.aiResult?.languages || [],
    techStack: snapshot.aiResult?.techStack || [],
    summary: snapshot.aiResult?.summary || '暂无摘要',
    updatedAt: snapshot.updatedAt,
    totalFiles: snapshot.files.length,
    codeFiles: codeFileCount(snapshot.aiResult, snapshot.files),
    moduleCount: snapshot.modules.length,
  }));
}

export function saveProjectAnalysisSnapshot(input: ProjectAnalysisSaveInput) {
  const existing = getProjectAnalysisSnapshot(
    input.id || buildProjectAnalysisId(input.repo.owner, input.repo.repo),
  );
  const id = existing?.id || input.id || buildProjectAnalysisId(input.repo.owner, input.repo.repo);
  const createdAt = existing?.createdAt || input.createdAt || new Date().toISOString();
  const updatedAt = new Date().toISOString();

  const snapshotWithoutMarkdown: Omit<ProjectAnalysisSnapshot, 'engineeringMarkdown'> = {
    id,
    version: SNAPSHOT_VERSION,
    createdAt,
    updatedAt,
    githubUrl: input.githubUrl,
    repo: {
      ...input.repo,
      fullName: `${input.repo.owner}/${input.repo.repo}`,
    },
    aiResult: input.aiResult,
    files: input.files,
    functionTree: input.functionTree,
    modules: input.modules || [],
    logs: input.logs,
  };

  const snapshot: ProjectAnalysisSnapshot = {
    ...snapshotWithoutMarkdown,
    engineeringMarkdown: buildEngineeringMarkdown(snapshotWithoutMarkdown),
  };

  const nextSnapshots = [
    snapshot,
    ...readSnapshots().filter((item) => item.id !== snapshot.id),
  ];

  return {
    snapshot,
    persisted: writeSnapshots(nextSnapshots, snapshot.id),
  };
}
