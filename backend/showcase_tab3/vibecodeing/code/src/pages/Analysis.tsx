import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  ChevronLeft,
  Download,
  Eye,
  EyeOff,
  FileCode,
  FileText,
  FolderOpen,
  Github,
  Loader2,
  Search,
  Sparkles,
  X,
} from 'lucide-react';
import { CodeViewer } from '../components/CodeViewer';
import { FileTree } from '../components/FileTree';
import { LogPanel } from '../components/LogPanel';
import { ModuleListPanel } from '../components/ModuleListPanel';
import { PanoramaPanel } from '../components/PanoramaPanel';
import { SettingsLauncher } from '../components/SettingsLauncher';
import {
  AIAnalysisResult,
  CODE_EXTENSIONS,
  FunctionFileGuessResult,
  SubFunction,
  analyzeProjectWithAI,
  classifyFunctionModules,
  guessFunctionDefinitionFiles,
  identifySubFunctions,
  verifyEntryPoint,
} from '../services/aiService';
import {
  LocatedFunction,
  locateFunctionInContent,
  normalizeFunctionName,
  rankFilesForRepositorySearch,
} from '../services/functionSearch';
import {
  collectFrameworkEntryPointHints,
  resolveFrameworkEntryBridge,
} from '../services/frameworkBridges';
import { getLocalProjectSession } from '../services/localProjectSession';
import { getMaxDrillDepth } from '../services/appSettings';
import {
  buildFileTree,
  createGithubProjectDataSource,
  type ProjectDataSource,
} from '../services/projectDataSource';
import {
  getProjectAnalysisSnapshot,
  hydrateLogEntries,
  normalizeGithubProjectUrl,
  saveProjectAnalysisSnapshot,
  serializeLogEntries,
} from '../services/projectAnalysisStorage';
import { AnalysisModule, FunctionNode, ProjectAnalysisSnapshot, WorkflowStatus } from '../types/analysis';
import { FunctionBridgeInfo } from '../types/functionFlow';
import { LogEntry } from '../types/log';
import { FileNode } from '../types/project';
import {
  applyModulesToFunctionTree,
  flattenFunctionTree,
  normalizeModuleAssignments,
} from '../utils/analysisModules';

interface ActiveProjectState {
  sourceType: 'github' | 'local';
  displayName: string;
  projectName: string;
  displayLocation: string;
  location: string;
  owner?: string;
  repo?: string;
}

interface ProjectAnalysisContext {
  sourceType: 'github' | 'local';
  projectName: string;
  projectLocation: string;
  summary: string;
  languages: string[];
  codeFilePaths: string[];
}

interface RecursiveAnalysisArgs {
  repoContext: ProjectAnalysisContext;
  targetFunction: SubFunction;
  targetNodeId: string;
  parentFunctionName: string;
  parentFilePath: string;
  depth: number;
  ancestry: Set<string>;
  remainingLevels?: number;
}

interface SelectedFileState {
  path: string;
  content: string;
  loading: boolean;
  highlightRange: { startLine: number; endLine: number } | null;
  focusKey: number;
}

function trimContentForAI(content: string, maxLines = 4000) {
  const lines = content.split('\n');
  if (lines.length <= maxLines) {
    return content;
  }

  const half = Math.floor(maxLines / 2);
  return [
    lines.slice(0, half).join('\n'),
    '',
    '... [content truncated for analysis] ...',
    '',
    lines.slice(-half).join('\n'),
  ].join('\n');
}

function appendStopReason(summary: string, reason: string) {
  if (!reason || summary.includes(reason)) {
    return summary;
  }
  return `${summary} [停止: ${reason}]`;
}

function dedupeStrings(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

function buildLocationCacheKey(filePath: string, startLine: number, endLine: number) {
  return `${filePath}:${startLine}:${endLine}`;
}

function createActiveProjectState(dataSource: ProjectDataSource): ActiveProjectState {
  const { descriptor } = dataSource;
  const isGithub = descriptor.type === 'github';

  return {
    sourceType: descriptor.type,
    displayName: descriptor.fullName,
    projectName: descriptor.projectName,
    displayLocation: isGithub
      ? descriptor.location
      : `已选择本地目录: ${descriptor.projectName}`,
    location: descriptor.location,
    owner: descriptor.owner,
    repo: descriptor.repo,
  };
}

function buildNodeId(parentNodeId: string, functionName: string, index?: number) {
  const normalizedName = normalizeFunctionName(functionName) || 'anonymous';
  return `${parentNodeId}/${normalizedName}${typeof index === 'number' ? `-${index}` : ''}`;
}

function createFunctionNode(
  targetFunction: SubFunction,
  parentFilePath: string,
  depth: number,
  id: string,
  overrides: Partial<FunctionNode> = {},
): FunctionNode {
  return {
    id,
    name: targetFunction.name,
    filePath: targetFunction.filePath || parentFilePath,
    summary: targetFunction.summary,
    children: [],
    drillDown: targetFunction.drillDown,
    depth,
    status: 'pending',
    location: null,
    route: targetFunction.route || null,
    bridge: targetFunction.bridge || null,
    ...overrides,
  };
}

function cloneFunctionSubtree(node: FunctionNode, nextId: string, nextDepth: number): FunctionNode {
  return {
    ...node,
    id: nextId,
    depth: nextDepth,
    children: (node.children ?? []).map((child, index) =>
      cloneFunctionSubtree(child, buildNodeId(nextId, child.name, index), nextDepth + 1),
    ),
  };
}

function pruneFunctionSubtree(node: FunctionNode, remainingLevels: number): FunctionNode {
  if (remainingLevels <= 0) {
    return {
      ...node,
      children: [],
    };
  }

  return {
    ...node,
    children: (node.children ?? []).map((child) => pruneFunctionSubtree(child, remainingLevels - 1)),
  };
}

function inheritModuleForSubtree(
  node: FunctionNode,
  parentModuleId?: string | null,
  parentModuleName?: string | null,
): FunctionNode {
  const moduleId = node.moduleId ?? parentModuleId ?? null;
  const moduleName = node.moduleName ?? parentModuleName ?? null;

  return {
    ...node,
    moduleId,
    moduleName,
    children: node.children?.map((child) => inheritModuleForSubtree(child, moduleId, moduleName)),
  };
}

function updateNodeInTree(
  node: FunctionNode,
  nodeId: string,
  updater: (node: FunctionNode) => FunctionNode,
): FunctionNode {
  if (node.id === nodeId) {
    return updater(node);
  }
  if (!node.children?.length) {
    return node;
  }

  let changed = false;
  const nextChildren = node.children.map((child) => {
    const nextChild = updateNodeInTree(child, nodeId, updater);
    if (nextChild !== child) {
      changed = true;
    }
    return nextChild;
  });

  return changed ? { ...node, children: nextChildren } : node;
}

function findNodePath(
  node: FunctionNode | null,
  nodeId: string,
  lineage: FunctionNode[] = [],
): FunctionNode[] | null {
  if (!node) {
    return null;
  }

  const nextLineage = [...lineage, node];
  if (node.id === nodeId) {
    return nextLineage;
  }

  for (const child of node.children ?? []) {
    const matchedLineage = findNodePath(child, nodeId, nextLineage);
    if (matchedLineage) {
      return matchedLineage;
    }
  }

  return null;
}

function indexFunctionAnalysisCache(node: FunctionNode | null, cache: Map<string, FunctionNode>) {
  if (!node) {
    return;
  }
  if (node.location) {
    cache.set(
      buildLocationCacheKey(node.filePath, node.location.startLine, node.location.endLine),
      cloneFunctionSubtree(node, node.id, node.depth ?? 0),
    );
  }
  for (const child of node.children ?? []) {
    indexFunctionAnalysisCache(child, cache);
  }
}

const EMPTY_SELECTED_FILE: SelectedFileState = {
  path: '',
  content: '',
  loading: false,
  highlightRange: null,
  focusKey: 0,
};

export const Analysis: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const sourceParam = searchParams.get('source') || '';
  const urlParam = searchParams.get('url') || '';
  const historyParam = searchParams.get('history') || '';
  const sessionParam = searchParams.get('session') || '';

  const [urlInput, setUrlInput] = useState(urlParam);
  const [loading, setLoading] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [moduleLoading, setModuleLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeSource, setActiveSource] = useState<ProjectDataSource | null>(null);
  const [projectState, setProjectState] = useState<ActiveProjectState | null>(null);
  const [treeNodes, setTreeNodes] = useState<FileNode[]>([]);
  const [repoFiles, setRepoFiles] = useState<ProjectAnalysisSnapshot['files']>([]);
  const [repoInfo, setRepoInfo] = useState<{ owner: string; repo: string } | null>(null);
  const [aiResult, setAiResult] = useState<AIAnalysisResult | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [functionTree, setFunctionTree] = useState<FunctionNode | null>(null);
  const [modules, setModules] = useState<AnalysisModule[]>([]);
  const [activeModuleId, setActiveModuleId] = useState<string | null>(null);
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>('idle');
  const [workflowLabel, setWorkflowLabel] = useState('等待开始分析');
  const [currentSnapshotId, setCurrentSnapshotId] = useState('');
  const [engineeringMarkdown, setEngineeringMarkdown] = useState('');
  const [isEngineeringFileOpen, setIsEngineeringFileOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<SelectedFileState>(EMPTY_SELECTED_FILE);
  const [panels, setPanels] = useState({ fileTree: true, codeViewer: true, panorama: true });
  const [manualDrillNodeId, setManualDrillNodeId] = useState<string | null>(null);

  const lastLoadKey = useRef('');
  const logsRef = useRef<LogEntry[]>([]);
  const activeSourceRef = useRef<ProjectDataSource | null>(null);
  const functionAnalysisCacheRef = useRef<Map<string, FunctionNode>>(new Map());
  const functionTreeRef = useRef<FunctionNode | null>(null);

  const updateWorkflow = useCallback((status: WorkflowStatus, label: string) => {
    setWorkflowStatus(status);
    setWorkflowLabel(label);
  }, []);

  useEffect(() => {
    functionTreeRef.current = functionTree;
  }, [functionTree]);

  useEffect(() => {
    activeSourceRef.current = activeSource;
  }, [activeSource]);

  const addLog = useCallback((type: LogEntry['type'], message: string, details?: LogEntry['details']) => {
    const nextEntry: LogEntry = {
      id: Math.random().toString(36).slice(2),
      timestamp: new Date(),
      type,
      message,
      details,
    };
    logsRef.current = [...logsRef.current, nextEntry];
    setLogs(logsRef.current);
  }, []);

  const addAiLog = useCallback((message: string, raw: any, data?: unknown) => {
    addLog('ai', message, {
      request: raw.request,
      response: raw.response,
      filteredFiles: raw.filteredFiles,
      usage: raw.usage,
      data,
    });
  }, [addLog]);

  const getCachedFileContent = useCallback(async (path: string) => {
    const source = activeSourceRef.current;
    if (!source) {
      throw new Error('当前没有可用的数据源');
    }

    return source.readFile(path);
  }, []);

  const replaceFunctionTree = useCallback((nextFunctionTree: FunctionNode | null) => {
    functionTreeRef.current = nextFunctionTree;
    setFunctionTree(nextFunctionTree);
  }, []);

  const patchFunctionTreeNode = useCallback((nodeId: string, updater: (node: FunctionNode) => FunctionNode) => {
    setFunctionTree((prev) => {
      const nextTree = prev ? updateNodeInTree(prev, nodeId, updater) : prev;
      functionTreeRef.current = nextTree;
      return nextTree;
    });
  }, []);

  const commitFunctionTreeNode = useCallback((nodeId: string, updater: (node: FunctionNode) => FunctionNode) => {
    const currentTree = functionTreeRef.current;
    if (!currentTree) {
      return null;
    }

    const nextTree = updateNodeInTree(currentTree, nodeId, updater);
    replaceFunctionTree(nextTree);
    return nextTree;
  }, [replaceFunctionTree]);

  const persistSnapshot = useCallback((
    nextRepoInfo: { owner: string; repo: string },
    nextAiResult: AIAnalysisResult,
    nextFiles: ProjectAnalysisSnapshot['files'],
    nextFunctionTree: FunctionNode | null,
    nextModules: AnalysisModule[],
    snapshotId?: string,
  ) => {
    const { snapshot } = saveProjectAnalysisSnapshot({
      id: snapshotId,
      githubUrl: normalizeGithubProjectUrl(nextRepoInfo.owner, nextRepoInfo.repo),
      repo: nextRepoInfo,
      aiResult: nextAiResult,
      files: nextFiles,
      functionTree: nextFunctionTree,
      modules: nextModules,
      logs: serializeLogEntries(logsRef.current),
    });
    setCurrentSnapshotId(snapshot.id);
    setEngineeringMarkdown(snapshot.engineeringMarkdown);
    return snapshot;
  }, []);

  const applySnapshot = useCallback((snapshot: ProjectAnalysisSnapshot) => {
    functionAnalysisCacheRef.current.clear();
    const snapshotSource = createGithubProjectDataSource(snapshot.githubUrl);
    const nextProjectState = snapshotSource
      ? createActiveProjectState(snapshotSource)
      : {
        sourceType: 'github' as const,
        displayName: snapshot.repo.fullName,
        projectName: snapshot.repo.repo,
        displayLocation: snapshot.githubUrl,
        location: snapshot.githubUrl,
        owner: snapshot.repo.owner,
        repo: snapshot.repo.repo,
      };
    logsRef.current = hydrateLogEntries(snapshot.logs);
    activeSourceRef.current = snapshotSource;
    setUrlInput(snapshot.githubUrl);
    setLoading(false);
    setAiLoading(false);
    setModuleLoading(false);
    setError('');
    setActiveSource(snapshotSource);
    setProjectState(nextProjectState);
    setRepoInfo({ owner: snapshot.repo.owner, repo: snapshot.repo.repo });
    setRepoFiles(snapshot.files);
    setAiResult(snapshot.aiResult);
    setLogs(logsRef.current);
    setTreeNodes(buildFileTree(snapshot.files));
    setModules(snapshot.modules);
    setActiveModuleId(null);
    replaceFunctionTree(snapshot.functionTree);
    setManualDrillNodeId(null);
    setSelectedFile(EMPTY_SELECTED_FILE);
    setCurrentSnapshotId(snapshot.id);
    setEngineeringMarkdown(snapshot.engineeringMarkdown);
    indexFunctionAnalysisCache(snapshot.functionTree, functionAnalysisCacheRef.current);
    updateWorkflow('restored', '已加载历史分析结果');
  }, [replaceFunctionTree, updateWorkflow]);

  const loadHistorySnapshot = useCallback((snapshotId: string) => {
    const snapshot = getProjectAnalysisSnapshot(snapshotId);
    if (!snapshot) {
      logsRef.current = [];
      setLogs([]);
      functionAnalysisCacheRef.current.clear();
      activeSourceRef.current = null;
      setLoading(false);
      setAiLoading(false);
      setModuleLoading(false);
      setError('未找到对应的历史分析记录');
      setActiveSource(null);
      setProjectState(null);
      setRepoInfo(null);
      setRepoFiles([]);
      setTreeNodes([]);
      setAiResult(null);
      setModules([]);
      setActiveModuleId(null);
      replaceFunctionTree(null);
      setManualDrillNodeId(null);
      setSelectedFile(EMPTY_SELECTED_FILE);
      setCurrentSnapshotId('');
      setEngineeringMarkdown('');
      updateWorkflow('failed', '历史分析记录不存在');
      return;
    }
    applySnapshot(snapshot);
  }, [applySnapshot, replaceFunctionTree, updateWorkflow]);

  const locateFunctionDefinition = useCallback(async (
    repoContext: ProjectAnalysisContext,
    targetFunction: SubFunction,
    parentFunctionName: string,
    parentFilePath: string,
  ): Promise<{ location: LocatedFunction | null; stopReason: string }> => {
    const source = activeSourceRef.current;
    if (!source) {
      throw new Error('当前没有可用的数据源');
    }

    const normalizedName = normalizeFunctionName(targetFunction.name);
    if (!normalizedName) {
      return { location: null, stopReason: '函数名无法解析' };
    }

    addLog('info', `开始定位函数 ${targetFunction.name} 的定义`);

    if (parentFilePath) {
      try {
        const parentContent = await getCachedFileContent(parentFilePath);
        const sameFileLocation = locateFunctionInContent(parentContent, parentFilePath, targetFunction.name, 'same_file');
        if (sameFileLocation) {
          addLog('success', `在父函数同文件中定位到 ${targetFunction.name}`, { data: sameFileLocation });
          return { location: sameFileLocation, stopReason: '' };
        }
      } catch (sameFileError: any) {
        addLog('error', `读取父函数所在文件失败: ${sameFileError.message}`);
      }
    }

    let fileGuessResult: FunctionFileGuessResult | null = null;
    const guessedCandidates: string[] = [];

    try {
      const { result, raw } = await guessFunctionDefinitionFiles(
        repoContext.summary,
        repoContext.codeFilePaths,
        targetFunction.name,
        parentFunctionName,
        parentFilePath,
        targetFunction.filePath,
      );
      fileGuessResult = result;
      addAiLog(`AI 给出了函数 ${targetFunction.name} 的候选定义文件`, raw, result);
      for (const candidate of [targetFunction.filePath, ...result.candidatePaths]) {
        if (!candidate || !repoContext.codeFilePaths.includes(candidate) || guessedCandidates.includes(candidate)) {
          continue;
        }
        guessedCandidates.push(candidate);
      }
    } catch (guessError: any) {
      addLog('error', `AI 猜测函数 ${targetFunction.name} 的定义文件失败: ${guessError.message}`);
    }

    for (const candidatePath of guessedCandidates) {
      if (candidatePath === parentFilePath) {
        continue;
      }
      try {
        const aiGuessMatch = await source.searchFiles([candidatePath], (content, path) =>
          locateFunctionInContent(content, path, targetFunction.name, 'ai_guess'),
        );
        const aiGuessLocation = aiGuessMatch?.result || null;
        if (aiGuessLocation) {
          addLog('success', `根据 AI 文件猜测定位到 ${targetFunction.name}`, { data: aiGuessLocation });
          return { location: aiGuessLocation, stopReason: '' };
        }
      } catch (candidateError: any) {
        addLog('error', `读取候选文件 ${candidatePath} 失败: ${candidateError.message}`);
      }
    }

    addLog('info', `开始在仓库内搜索函数 ${targetFunction.name} 的定义`);
    const searchedPaths = new Set<string>([parentFilePath, ...guessedCandidates].filter(Boolean));
    const rankedPaths = rankFilesForRepositorySearch(repoContext.codeFilePaths, parentFilePath, targetFunction.name)
      .filter((path) => !searchedPaths.has(path));

    for (const candidatePath of rankedPaths) {
      try {
        const searchedMatch = await source.searchFiles([candidatePath], (content, path) =>
          locateFunctionInContent(content, path, targetFunction.name, 'repo_search'),
        );
        const searchedLocation = searchedMatch?.result || null;
        if (searchedLocation) {
          addLog('success', `通过全仓搜索定位到 ${targetFunction.name}`, { data: searchedLocation });
          return { location: searchedLocation, stopReason: '' };
        }
      } catch (searchError: any) {
        addLog('error', `搜索文件 ${candidatePath} 失败: ${searchError.message}`);
      }
    }

    if (fileGuessResult?.likelyExternal) {
      return {
        location: null,
        stopReason: `AI 判断该函数可能是系统函数、库函数或外部依赖: ${fileGuessResult.reason}`,
      };
    }

    return { location: null, stopReason: '未在仓库中找到该函数定义' };
  }, [addAiLog, addLog, getCachedFileContent]);

  const analyzeFunctionRecursively = useCallback(async ({
    repoContext,
    targetFunction,
    targetNodeId,
    parentFunctionName,
    parentFilePath,
    depth,
    ancestry,
    remainingLevels,
  }: RecursiveAnalysisArgs): Promise<FunctionNode> => {
    const baseNode = createFunctionNode(targetFunction, parentFilePath, depth, targetNodeId);
    const hasRemainingLevels = typeof remainingLevels === 'number';
    const maxDrillDepth = getMaxDrillDepth();

    patchFunctionTreeNode(targetNodeId, (current) => ({
      ...current,
      ...baseNode,
      children: current.children ?? [],
      status: 'locating',
    }));

    if (targetFunction.drillDown === -1) {
      const nextNode = {
        ...baseNode,
        summary: appendStopReason(baseNode.summary, 'AI 标记该函数无需继续下钻'),
        status: 'stopped' as const,
      };
      patchFunctionTreeNode(targetNodeId, () => nextNode);
      return nextNode;
    }

    if (!hasRemainingLevels && depth >= maxDrillDepth) {
      const nextNode = {
        ...baseNode,
        summary: appendStopReason(baseNode.summary, `达到最大递归深度 ${maxDrillDepth}`),
        status: 'stopped' as const,
      };
      patchFunctionTreeNode(targetNodeId, () => nextNode);
      return nextNode;
    }

    const { location, stopReason } = await locateFunctionDefinition(
      repoContext,
      targetFunction,
      parentFunctionName,
      parentFilePath,
    );

    if (!location) {
      const nextNode = {
        ...baseNode,
        summary: appendStopReason(baseNode.summary, stopReason),
        status: 'stopped' as const,
      };
      addLog('info', `停止下钻函数 ${targetFunction.name}: ${stopReason}`);
      patchFunctionTreeNode(targetNodeId, () => nextNode);
      return nextNode;
    }

    const locationData = {
      startLine: location.startLine,
      endLine: location.endLine,
      matchedSignature: location.matchedSignature,
      strategy: location.strategy,
    };
    const cacheKey = buildLocationCacheKey(location.filePath, location.startLine, location.endLine);

    if (ancestry.has(cacheKey)) {
      const nextNode = {
        ...baseNode,
        filePath: location.filePath,
        location: locationData,
        summary: appendStopReason(baseNode.summary, '检测到递归或循环调用链'),
        status: 'stopped' as const,
      };
      patchFunctionTreeNode(targetNodeId, () => nextNode);
      return nextNode;
    }

    const cachedNode = functionAnalysisCacheRef.current.get(cacheKey);
    if (cachedNode) {
      const clonedNode = cloneFunctionSubtree(cachedNode, targetNodeId, depth);
      const nextNode = hasRemainingLevels
        ? pruneFunctionSubtree(clonedNode, remainingLevels)
        : clonedNode;
      addLog('success', `命中函数分析缓存: ${targetFunction.name}`, {
        data: {
          cacheKey,
          filePath: location.filePath,
          startLine: location.startLine,
          endLine: location.endLine,
        },
      });
      patchFunctionTreeNode(targetNodeId, () => nextNode);
      return nextNode;
    }

    addLog('info', `未命中函数分析缓存: ${targetFunction.name}`, {
      data: {
        cacheKey,
        filePath: location.filePath,
        startLine: location.startLine,
        endLine: location.endLine,
      },
    });
    addLog('info', `开始分析函数 ${targetFunction.name} 的关键子函数，深度 ${depth}`);
    patchFunctionTreeNode(targetNodeId, (current) => ({
      ...current,
      filePath: location.filePath,
      location: locationData,
      status: 'analyzing',
    }));

    if (hasRemainingLevels && remainingLevels === 0) {
      const nextNode: FunctionNode = {
        ...baseNode,
        filePath: location.filePath,
        location: locationData,
        children: [],
        status: 'completed',
      };
      patchFunctionTreeNode(targetNodeId, () => nextNode);
      return nextNode;
    }

    const { result, raw } = await identifySubFunctions(
      repoContext.summary,
      repoContext.languages,
      repoContext.codeFilePaths,
      targetFunction.name,
      location.filePath,
      location.snippet,
    );

    addAiLog(`函数 ${targetFunction.name} 的子函数分析完成`, raw, { location, depth, result });

    if (!result.functions.length) {
      const nextNode: FunctionNode = {
        ...baseNode,
        filePath: location.filePath,
        location: locationData,
        summary: appendStopReason(baseNode.summary, '未识别到更多关键子函数'),
        children: [],
        status: 'completed',
      };
      if (!hasRemainingLevels) {
        functionAnalysisCacheRef.current.set(cacheKey, cloneFunctionSubtree(nextNode, nextNode.id, depth));
        addLog('info', `写入函数分析缓存: ${targetFunction.name}`, { data: { cacheKey } });
      }
      patchFunctionTreeNode(targetNodeId, () => nextNode);
      return nextNode;
    }

    const nextAncestry = new Set(ancestry);
    nextAncestry.add(cacheKey);
    const childNodes = result.functions.map((childFunction, index) =>
      createFunctionNode(childFunction, location.filePath, depth + 1, buildNodeId(targetNodeId, childFunction.name, index)),
    );

    patchFunctionTreeNode(targetNodeId, (current) => ({
      ...current,
      filePath: location.filePath,
      location: locationData,
      children: childNodes,
      status: 'analyzing',
    }));

    const children: FunctionNode[] = [];
    for (let index = 0; index < result.functions.length; index += 1) {
      children.push(await analyzeFunctionRecursively({
        repoContext,
        targetFunction: result.functions[index],
        targetNodeId: childNodes[index].id,
        parentFunctionName: targetFunction.name,
        parentFilePath: location.filePath,
        depth: depth + 1,
        ancestry: nextAncestry,
        remainingLevels: hasRemainingLevels ? remainingLevels - 1 : undefined,
      }));
    }

    const nextNode: FunctionNode = {
      ...baseNode,
      filePath: location.filePath,
      location: locationData,
      children,
      status: 'completed',
    };
    if (!hasRemainingLevels) {
      functionAnalysisCacheRef.current.set(cacheKey, cloneFunctionSubtree(nextNode, nextNode.id, depth));
      addLog('info', `写入函数分析缓存: ${targetFunction.name}`, { data: { cacheKey } });
    }
    patchFunctionTreeNode(targetNodeId, () => nextNode);
    return nextNode;
  }, [addAiLog, addLog, locateFunctionDefinition, patchFunctionTreeNode]);

  const runEntryPointAnalysis = useCallback(async (
    currentProjectState: ActiveProjectState,
    projectContext: ProjectAnalysisContext,
    potentialEntryPoints: string[],
    allFilePaths: string[],
  ): Promise<FunctionNode | null> => {
    const source = activeSourceRef.current;
    if (!source) {
      throw new Error('当前没有可用的数据源');
    }

    addLog('info', `开始验证入口文件候选，共 ${potentialEntryPoints.length} 个`);
    updateWorkflow('running', '验证入口文件并构建调用链');

    const codeFilePaths = allFilePaths.filter((path) =>
      CODE_EXTENSIONS.some((ext) => path.toLowerCase().endsWith(ext)),
    );

    for (const entryFilePath of potentialEntryPoints) {
      try {
        addLog('info', `正在验证入口候选文件 ${entryFilePath}`);
        const entryFileContent = await getCachedFileContent(entryFilePath);
        const aiReadyEntryContent = trimContentForAI(entryFileContent);
        const bridgeResult = await resolveFrameworkEntryBridge({
          owner: currentProjectState.owner || 'local',
          repo: currentProjectState.repo || projectContext.projectName,
          githubUrl: projectContext.projectLocation,
          summary: projectContext.summary,
          languages: projectContext.languages,
          allFilePaths,
          codeFilePaths,
          entryFilePath,
          entryFileContent,
          getFileContent: async (path) => getCachedFileContent(path),
        });
        const { result, raw } = await verifyEntryPoint(
          projectContext.projectLocation,
          projectContext.summary,
          projectContext.languages,
          entryFilePath,
          aiReadyEntryContent,
        );
        addAiLog(`入口文件研判完成: ${entryFilePath}`, raw, result);
        if (!result.isEntryPoint && !bridgeResult) {
          continue;
        }

        if (!result.isEntryPoint && bridgeResult) {
          addLog('info', `入口候选 ${entryFilePath} 由 ${bridgeResult.framework} 桥接规则确认为可分析入口`);
        }
        addLog('success', `确认入口文件: ${entryFilePath}`);

        const rootBridgeInfo: FunctionBridgeInfo | null = bridgeResult ? {
          adapterId: bridgeResult.adapterId,
          framework: bridgeResult.framework,
          kind: 'entry',
          reason: bridgeResult.reason,
        } : null;

        let subFunctions: SubFunction[] = [];
        if (bridgeResult) {
          subFunctions = bridgeResult.nodes;
          addLog('info', `启用 ${bridgeResult.framework} 框架桥接: ${bridgeResult.reason}`);
        } else {
          const { result: subFunctionResult, raw: subFunctionRaw } = await identifySubFunctions(
            projectContext.summary,
            projectContext.languages,
            codeFilePaths,
            '入口函数',
            entryFilePath,
            aiReadyEntryContent,
          );
          addAiLog('入口函数首层子函数分析完成', subFunctionRaw, subFunctionResult);
          subFunctions = subFunctionResult.functions;
        }

        const rootChildren = subFunctions.map((childFunction, index) =>
          createFunctionNode(childFunction, entryFilePath, 1, buildNodeId('root', childFunction.name, index)),
        );
        const rootNode: FunctionNode = {
          id: 'root',
          name: '入口函数',
          filePath: entryFilePath,
          summary: bridgeResult?.rootSummary || '项目启动与主执行流程入口',
          depth: 0,
          children: rootChildren,
          status: 'analyzing',
          location: null,
          bridge: rootBridgeInfo,
        };
        replaceFunctionTree(rootNode);

        const resolvedChildren: FunctionNode[] = [];
        for (let index = 0; index < subFunctions.length; index += 1) {
          resolvedChildren.push(await analyzeFunctionRecursively({
            repoContext: {
              ...projectContext,
              codeFilePaths,
            },
            targetFunction: subFunctions[index],
            targetNodeId: rootChildren[index].id,
            parentFunctionName: rootNode.name,
            parentFilePath: subFunctions[index].filePath || entryFilePath,
            depth: 1,
            ancestry: new Set<string>(),
          }));
        }

        const completedRootNode: FunctionNode = { ...rootNode, children: resolvedChildren, status: 'completed' };
        patchFunctionTreeNode('root', () => completedRootNode);
        return completedRootNode;
      } catch (entryError: any) {
        addLog('error', `入口文件分析失败 ${entryFilePath}: ${entryError.message}`);
      }
    }

    addLog('info', '未能确认可继续递归分析的入口文件');
    return null;
  }, [addAiLog, addLog, analyzeFunctionRecursively, getCachedFileContent, patchFunctionTreeNode, replaceFunctionTree, updateWorkflow]);

  const analyzeModules = useCallback(async (
    result: AIAnalysisResult,
    rootNode: FunctionNode | null,
  ): Promise<{ modules: AnalysisModule[]; tree: FunctionNode | null }> => {
    if (!rootNode) {
      addLog('info', '未生成函数调用链，跳过功能模块划分');
      return { modules: [], tree: rootNode };
    }
    const flatNodes = flattenFunctionTree(rootNode).map((node) => ({
      id: node.id,
      name: node.name,
      filePath: node.filePath,
      summary: node.summary,
      depth: node.depth,
      parentId: node.parentId,
    }));
    if (!flatNodes.length) {
      addLog('info', '未提取到可用函数节点，跳过功能模块划分');
      return { modules: [], tree: rootNode };
    }

    setModuleLoading(true);
    updateWorkflow('running', 'AI 正在划分功能模块');
    try {
      const { result: moduleResult, raw } = await classifyFunctionModules(
        result.summary,
        result.languages,
        result.techStack,
        flatNodes,
      );
      const normalizedModules = normalizeModuleAssignments(moduleResult.modules, flatNodes);
      const nextTree = applyModulesToFunctionTree(rootNode, normalizedModules);
      addAiLog('AI 功能模块划分完成', raw, normalizedModules);
      return { modules: normalizedModules, tree: nextTree };
    } catch (moduleError: any) {
      addLog('error', `功能模块划分失败: ${moduleError.message}`);
      return { modules: [], tree: rootNode };
    } finally {
      setModuleLoading(false);
    }
  }, [addAiLog, addLog, updateWorkflow]);

  const persistCurrentSnapshot = useCallback((nextFunctionTree: FunctionNode | null) => {
    if (!repoInfo || !aiResult || repoFiles.length === 0) {
      return;
    }

    persistSnapshot(
      repoInfo,
      aiResult,
      repoFiles,
      nextFunctionTree,
      modules,
      currentSnapshotId || undefined,
    );
  }, [aiResult, currentSnapshotId, modules, persistSnapshot, repoFiles, repoInfo]);

  const handleManualDrillDown = useCallback(async (node: FunctionNode) => {
    if (manualDrillNodeId || !activeSource || !projectState || !aiResult || repoFiles.length === 0) {
      return;
    }
    const manualDrillLevels = getMaxDrillDepth();

    const currentTree = functionTreeRef.current;
    const nodePath = findNodePath(currentTree, node.id);
    if (!currentTree || !nodePath) {
      addLog('error', `未找到可手动下钻的节点: ${node.name}`);
      return;
    }

    const targetNode = nodePath[nodePath.length - 1];
    const parentNode = nodePath[nodePath.length - 2] || null;

    if (targetNode.children?.length || targetNode.manualDrillAvailable === false || targetNode.drillDown === -1) {
      return;
    }

    const targetDepth = targetNode.depth ?? Math.max(nodePath.length - 1, 0);
    const repoContext: ProjectAnalysisContext = {
      sourceType: projectState.sourceType,
      projectName: projectState.projectName,
      projectLocation: projectState.location,
      summary: aiResult.summary,
      languages: aiResult.languages,
      codeFilePaths: repoFiles
        .map((file) => file.path)
        .filter((path) => CODE_EXTENSIONS.some((ext) => path.toLowerCase().endsWith(ext))),
    };
    const ancestry = new Set(
      nodePath
        .slice(0, -1)
        .flatMap((ancestor) => (ancestor.location
          ? [buildLocationCacheKey(ancestor.filePath, ancestor.location.startLine, ancestor.location.endLine)]
          : [])),
    );

    setManualDrillNodeId(targetNode.id);
    setError('');
    addLog('info', `开始手动下钻节点 ${targetNode.name}，最多向下分析 ${manualDrillLevels} 层`);
    updateWorkflow('running', `正在手动下钻 ${targetNode.name}`);

    try {
      const analyzedNode = await analyzeFunctionRecursively({
        repoContext,
        targetFunction: {
          name: targetNode.name,
          filePath: targetNode.filePath,
          summary: targetNode.summary,
          drillDown: targetNode.drillDown ?? 0,
          route: targetNode.route,
          bridge: targetNode.bridge,
        },
        targetNodeId: targetNode.id,
        parentFunctionName: parentNode?.name || '入口函数',
        parentFilePath: parentNode?.filePath || targetNode.filePath,
        depth: targetDepth,
        ancestry,
        remainingLevels: manualDrillLevels,
      });

      const finalizedNode = inheritModuleForSubtree(
        {
          ...analyzedNode,
          manualDrillAvailable: false,
        },
        targetNode.moduleId,
        targetNode.moduleName,
      );
      const nextTree = commitFunctionTreeNode(targetNode.id, () => finalizedNode);

      addLog(
        'success',
        `手动下钻完成 ${targetNode.name}，新增 ${finalizedNode.children?.length ?? 0} 个直接子节点，最多向下分析 ${manualDrillLevels} 层`,
      );
      persistCurrentSnapshot(nextTree);
      updateWorkflow('completed', `手动下钻完成: ${targetNode.name}`);
    } catch (manualDrillError: any) {
      const nextTree = commitFunctionTreeNode(targetNode.id, (current) => ({
        ...current,
        status: 'stopped',
        manualDrillAvailable: false,
        summary: appendStopReason(
          current.summary,
          manualDrillError.message || '手动下钻失败',
        ),
      }));
      addLog('error', `手动下钻失败 ${targetNode.name}: ${manualDrillError.message}`);
      persistCurrentSnapshot(nextTree);
      updateWorkflow('failed', manualDrillError.message || '手动下钻失败');
    } finally {
      setManualDrillNodeId(null);
    }
  }, [
    addLog,
    aiResult,
    analyzeFunctionRecursively,
    commitFunctionTreeNode,
    manualDrillNodeId,
    activeSource,
    persistCurrentSnapshot,
    projectState,
    repoFiles,
    updateWorkflow,
  ]);

  const analyzeDataSource = useCallback(async (dataSource: ProjectDataSource) => {
    const nextProjectState = createActiveProjectState(dataSource);
    const isGithubSource = nextProjectState.sourceType === 'github'
      && Boolean(nextProjectState.owner && nextProjectState.repo);

    logsRef.current = [];
    setLogs([]);
    functionAnalysisCacheRef.current.clear();
    activeSourceRef.current = dataSource;
    setActiveSource(dataSource);
    setProjectState(nextProjectState);
    setUrlInput(isGithubSource ? nextProjectState.location : '');
    setCurrentSnapshotId('');
    setEngineeringMarkdown('');
    setIsEngineeringFileOpen(false);
    setModules([]);
    setActiveModuleId(null);
    setLoading(true);
    setAiLoading(true);
    setModuleLoading(false);
    setError('');
    setRepoInfo(
      isGithubSource
        ? { owner: nextProjectState.owner!, repo: nextProjectState.repo! }
        : null,
    );
    setRepoFiles([]);
    setTreeNodes([]);
    setAiResult(null);
    replaceFunctionTree(null);
    setManualDrillNodeId(null);
    setSelectedFile(EMPTY_SELECTED_FILE);
    updateWorkflow('running', isGithubSource ? '获取仓库文件树' : '读取本地项目文件');

    let latestAiResult: AIAnalysisResult | null = null;
    let latestFunctionTree: FunctionNode | null = null;
    let latestModules: AnalysisModule[] = [];
    let latestFiles: ProjectAnalysisSnapshot['files'] = [];

    try {
      addLog(
        'info',
        isGithubSource
          ? `正在获取 ${nextProjectState.displayName} 的文件树`
          : `正在读取本地项目 ${nextProjectState.projectName} 的文件列表`,
      );

      latestFiles = await dataSource.listFiles();
      setRepoFiles(latestFiles);
      setTreeNodes(buildFileTree(latestFiles));
      addLog('success', `成功读取项目文件列表，共 ${latestFiles.length} 个条目`);

      const filePaths = latestFiles.map((file) => file.path);
      const codeFilePaths = filePaths.filter((path) =>
        CODE_EXTENSIONS.some((ext) => path.toLowerCase().endsWith(ext)),
      );

      updateWorkflow('running', 'AI 正在分析项目基本信息');
      const { result, raw } = await analyzeProjectWithAI(filePaths);
      const frameworkEntryHints = await collectFrameworkEntryPointHints({
        summary: result.summary,
        languages: result.languages,
        allFilePaths: filePaths,
        codeFilePaths,
      });
      const inferredEntryPoints = dedupeStrings(frameworkEntryHints.flatMap((hint) => hint.entryPoints));
      const normalizedAiResult: AIAnalysisResult = {
        ...result,
        entryPoints: dedupeStrings([...result.entryPoints, ...inferredEntryPoints]),
      };
      const analysisContext: ProjectAnalysisContext = {
        sourceType: nextProjectState.sourceType,
        projectName: nextProjectState.projectName,
        projectLocation: nextProjectState.location,
        summary: normalizedAiResult.summary,
        languages: normalizedAiResult.languages,
        codeFilePaths,
      };

      latestAiResult = normalizedAiResult;
      setAiResult(normalizedAiResult);
      addAiLog('AI 项目分析完成', raw, normalizedAiResult);
      for (const hint of frameworkEntryHints) {
        if (hint.entryPoints.length > 0) {
          addLog('info', `${hint.framework} 框架补充入口候选 ${hint.entryPoints.length} 个: ${hint.reason}`);
        }
      }

      if (normalizedAiResult.entryPoints.length > 0) {
        latestFunctionTree = await runEntryPointAnalysis(
          nextProjectState,
          analysisContext,
          normalizedAiResult.entryPoints,
          filePaths,
        );
      } else {
        addLog('info', 'AI 未给出入口文件候选');
      }

      const moduleAnalysis = await analyzeModules(normalizedAiResult, latestFunctionTree);
      latestModules = moduleAnalysis.modules;
      latestFunctionTree = moduleAnalysis.tree;
      setModules(latestModules);
      replaceFunctionTree(latestFunctionTree);
      updateWorkflow('completed', '分析流程已结束');
    } catch (analysisError: any) {
      setError(analysisError.message || '分析项目失败');
      addLog('error', `分析失败: ${analysisError.message}`);
      updateWorkflow('failed', analysisError.message || '分析项目失败');
    } finally {
      if (
        latestAiResult
        && latestFiles.length > 0
        && isGithubSource
        && nextProjectState.owner
        && nextProjectState.repo
      ) {
        persistSnapshot(
          { owner: nextProjectState.owner, repo: nextProjectState.repo },
          latestAiResult,
          latestFiles,
          latestFunctionTree,
          latestModules,
        );
      }
      setLoading(false);
      setAiLoading(false);
      setModuleLoading(false);
    }
  }, [addAiLog, addLog, analyzeModules, persistSnapshot, replaceFunctionTree, runEntryPointAnalysis, updateWorkflow]);

  const analyze = useCallback(async (targetUrl: string) => {
    const trimmedUrl = targetUrl.trim();
    const dataSource = createGithubProjectDataSource(trimmedUrl);
    if (!dataSource) {
      addLog('error', `GitHub 地址校验失败: ${trimmedUrl}`);
      setError('GitHub 地址无效');
      updateWorkflow('failed', 'GitHub 地址格式错误');
      return;
    }

    await analyzeDataSource(dataSource);
  }, [addLog, analyzeDataSource, updateWorkflow]);

  const handleReanalyzeModules = useCallback(async () => {
    if (!aiResult || !functionTree || repoFiles.length === 0) {
      addLog('error', '缺少重新分析模块所需的历史数据');
      updateWorkflow('failed', '缺少重新分析模块所需数据');
      return;
    }

    setError('');
    setActiveModuleId(null);
    addLog('info', '开始手动重新分析功能模块');
    const moduleAnalysis = await analyzeModules(aiResult, functionTree);
    if (!moduleAnalysis.tree || moduleAnalysis.modules.length === 0) {
      updateWorkflow('failed', '功能模块重新分析失败');
      return;
    }

    setModules(moduleAnalysis.modules);
    replaceFunctionTree(moduleAnalysis.tree);
    if (repoInfo) {
      persistSnapshot(repoInfo, aiResult, repoFiles, moduleAnalysis.tree, moduleAnalysis.modules, currentSnapshotId || undefined);
    }
    addLog('success', `功能模块重新分析完成，共 ${moduleAnalysis.modules.length} 个模块`);
    updateWorkflow('completed', '功能模块重新分析完成');
  }, [addLog, aiResult, analyzeModules, currentSnapshotId, functionTree, persistSnapshot, replaceFunctionTree, repoFiles, repoInfo, updateWorkflow]);

  useEffect(() => {
    const nextLoadKey = historyParam
      ? `history:${historyParam}`
      : sourceParam === 'local' && sessionParam
        ? `local:${sessionParam}`
        : urlParam
          ? `github:${urlParam}`
          : '';
    if (!nextLoadKey || lastLoadKey.current === nextLoadKey) {
      return;
    }
    lastLoadKey.current = nextLoadKey;
    if (historyParam) {
      loadHistorySnapshot(historyParam);
      return;
    }
    if (sourceParam === 'local' && sessionParam) {
      const localSource = getLocalProjectSession(sessionParam);
      if (!localSource) {
        activeSourceRef.current = null;
        setActiveSource(null);
        setProjectState(null);
        setRepoInfo(null);
        setRepoFiles([]);
        setTreeNodes([]);
        setAiResult(null);
        setModules([]);
        setCurrentSnapshotId('');
        setEngineeringMarkdown('');
        replaceFunctionTree(null);
        setSelectedFile(EMPTY_SELECTED_FILE);
        setError('本地项目会话已失效，请返回首页重新选择目录');
        updateWorkflow('failed', '本地项目会话不存在');
        return;
      }
      analyzeDataSource(localSource);
      return;
    }
    if (urlParam) {
      analyze(urlParam);
    }
  }, [analyze, analyzeDataSource, historyParam, loadHistorySnapshot, replaceFunctionTree, sessionParam, sourceParam, updateWorkflow, urlParam]);

  const handleFileSelect = useCallback(async (
    path: string,
    highlightRange: { startLine: number; endLine: number } | null = null,
  ) => {
    if (!activeSource) {
      return;
    }
    const focusKey = Date.now();
    setSelectedFile((prev) => ({ ...prev, path, loading: true, highlightRange, focusKey }));
    try {
      const content = await getCachedFileContent(path);
      setSelectedFile({ path, content, loading: false, highlightRange, focusKey });
    } catch (fileError) {
      console.error('Failed to fetch file content', fileError);
      setSelectedFile((prev) => ({ ...prev, loading: false }));
    }
  }, [activeSource, getCachedFileContent]);

  const handlePanoramaNodeSelect = useCallback((node: FunctionNode) => {
    if (!node.filePath) {
      return;
    }
    handleFileSelect(node.filePath, node.location ? {
      startLine: node.location.startLine,
      endLine: node.location.endLine,
    } : null);
  }, [handleFileSelect]);

  const handleSearchSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (projectState?.sourceType === 'local') {
      navigate('/');
      return;
    }
    const trimmedUrl = urlInput.trim();
    if (!trimmedUrl) {
      return;
    }
    if (!historyParam && urlParam === trimmedUrl) {
      lastLoadKey.current = '';
      analyze(trimmedUrl);
      return;
    }
    navigate(`/analysis?source=github&url=${encodeURIComponent(trimmedUrl)}`);
  };

  const downloadEngineeringFile = () => {
    if (!engineeringMarkdown || !projectState) {
      return;
    }
    const blob = new Blob([engineeringMarkdown], { type: 'text/markdown;charset=utf-8' });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = `${projectState.projectName}-analysis.md`;
    link.click();
    URL.revokeObjectURL(objectUrl);
  };

  const togglePanel = (panel: keyof typeof panels) => {
    setPanels((prev) => ({ ...prev, [panel]: !prev[panel] }));
  };

  const hasEngineeringFile = Boolean(engineeringMarkdown);
  const canReanalyzeModules = Boolean(activeSource && aiResult && functionTree && repoFiles.length > 0) && !loading && !aiLoading;
  const currentSourceType = projectState?.sourceType || (sourceParam === 'local' ? 'local' : 'github');
  const isGithubProject = currentSourceType === 'github';

  return (
    <>
      <div className="h-screen bg-zinc-50 text-zinc-900 flex flex-col overflow-hidden">
        <header className="h-14 border-b border-zinc-200 bg-white flex items-center justify-between px-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link to="/" className="inline-flex items-center gap-2 text-sm font-medium text-zinc-500 hover:text-zinc-800">
              <ChevronLeft size={16} /> 返回首页
            </Link>
            <div className="hidden md:flex items-center gap-2 text-sm text-zinc-500 min-w-0">
              {currentSourceType === 'local' ? <FolderOpen size={14} /> : <Github size={14} />}
              <span className="truncate">{projectState ? projectState.displayName : '等待项目分析'}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {currentSnapshotId && <span className="hidden lg:inline text-[10px] text-zinc-400 font-mono">#{currentSnapshotId}</span>}
            {aiLoading && <Loader2 size={12} className="animate-spin text-emerald-500" />}
            <SettingsLauncher
              label=""
              buttonClassName="inline-flex items-center justify-center rounded-lg border border-zinc-200 px-3 py-1.5 text-xs font-semibold text-zinc-600 hover:bg-zinc-50"
            />
            <button type="button" onClick={() => setIsEngineeringFileOpen(true)} disabled={!hasEngineeringFile} className={`hidden md:flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold ${hasEngineeringFile ? 'border-zinc-200 text-zinc-600 hover:bg-zinc-50' : 'border-zinc-100 text-zinc-300 cursor-not-allowed'}`}>
              <FileText size={14} /> 工程文件
            </button>
            <div className="flex bg-zinc-100 p-1 rounded-lg border border-zinc-200">
              <button onClick={() => togglePanel('fileTree')} className={`p-1.5 rounded-md ${panels.fileTree ? 'bg-white text-emerald-600' : 'text-zinc-400'}`} title="切换文件树">{panels.fileTree ? <Eye size={14} /> : <EyeOff size={14} />}</button>
              <button onClick={() => togglePanel('codeViewer')} className={`p-1.5 rounded-md ${panels.codeViewer ? 'bg-white text-emerald-600' : 'text-zinc-400'}`} title="切换代码面板">{panels.codeViewer ? <Eye size={14} /> : <EyeOff size={14} />}</button>
              <button onClick={() => togglePanel('panorama')} className={`p-1.5 rounded-md ${panels.panorama ? 'bg-white text-emerald-600' : 'text-zinc-400'}`} title="切换全景图">{panels.panorama ? <Eye size={14} /> : <EyeOff size={14} />}</button>
            </div>
          </div>
        </header>

        <div className="flex-1 flex overflow-hidden">
          <aside className="w-[360px] border-r border-zinc-200 bg-white flex flex-col">
            <LogPanel logs={logs} workflowStatus={workflowStatus} workflowLabel={workflowLabel} />
            <div className="p-4 border-b border-zinc-200">
              {isGithubProject ? (
                <form onSubmit={handleSearchSubmit} className="relative">
                  <input value={urlInput} onChange={(event) => setUrlInput(event.target.value)} placeholder="GitHub 仓库地址" className="w-full bg-white border border-zinc-200 rounded-lg py-2 pl-9 pr-3 text-sm" />
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
                </form>
              ) : (
                <div className="rounded-xl border border-zinc-200 bg-zinc-50/80 p-3 space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 rounded-lg border border-emerald-100 bg-emerald-50 p-2 text-emerald-600">
                      <FolderOpen size={14} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-zinc-900">本地目录模式</p>
                      <p className="text-[11px] leading-5 text-zinc-500 break-words">
                        {projectState?.displayLocation || '请从首页重新选择本地目录'}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate('/')}
                    className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs font-semibold text-zinc-700 hover:bg-zinc-50"
                  >
                    返回首页重新选择目录
                  </button>
                </div>
              )}
            </div>
            <div className="flex-1 overflow-auto p-4 space-y-6">
              {error && <div className="rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-[11px] text-red-700 flex items-start gap-2"><AlertCircle size={14} className="mt-0.5 shrink-0" />{error}</div>}
              <section className="space-y-3">
                <h3 className="text-[10px] uppercase tracking-widest text-zinc-400 font-bold flex items-center gap-2"><Sparkles size={12} className="text-emerald-500" />AI 智能分析</h3>
                {aiResult ? (
                  <div className="space-y-3">
                    <div className="p-3 rounded-xl border border-zinc-100 bg-white shadow-sm">
                      <p className="text-[10px] text-zinc-400 uppercase font-bold mb-2">编程语言</p>
                      <div className="flex flex-wrap gap-1.5">{aiResult.languages.map((lang) => <span key={lang} className="px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded-md text-[10px] font-medium border border-emerald-100">{lang}</span>)}</div>
                    </div>
                    <div className="p-3 rounded-xl border border-zinc-100 bg-white shadow-sm">
                      <p className="text-[10px] text-zinc-400 uppercase font-bold mb-2">技术栈</p>
                      <div className="flex flex-wrap gap-1.5">{aiResult.techStack.map((tech) => <span key={tech} className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded-md text-[10px] font-medium border border-blue-100">{tech}</span>)}</div>
                    </div>
                    <div className="p-3 rounded-xl border border-zinc-100 bg-white shadow-sm">
                      <p className="text-[10px] text-zinc-400 uppercase font-bold mb-2 flex items-center gap-1"><FileCode size={10} />入口文件候选</p>
                      <div className="space-y-1">{aiResult.entryPoints.map((path) => <div key={path} onClick={() => handleFileSelect(path)} className="text-[10px] text-zinc-600 hover:text-emerald-600 cursor-pointer truncate font-mono bg-zinc-50 p-1 rounded border border-zinc-100">{path}</div>)}</div>
                    </div>
                    <div className="p-3 bg-emerald-50/30 border border-emerald-100 rounded-xl"><p className="text-[10px] text-zinc-500 italic leading-relaxed">"{aiResult.summary}"</p></div>
                  </div>
                ) : <p className="text-[11px] text-zinc-400 italic">分析结果会显示在这里</p>}
              </section>

              <ModuleListPanel modules={modules} activeModuleId={activeModuleId} loading={moduleLoading} canReanalyze={canReanalyzeModules} reanalyzing={moduleLoading} onSelectModule={setActiveModuleId} onReanalyzeModules={handleReanalyzeModules} />

              <section className="pt-6 border-t border-zinc-200 space-y-2">
                <h3 className="text-[10px] uppercase tracking-widest text-zinc-400 font-bold">项目信息</h3>
                {projectState ? (
                  <>
                    <div className="p-3 bg-white border border-zinc-100 rounded-xl shadow-sm text-xs text-zinc-700">来源: {projectState.sourceType === 'github' ? 'GitHub 仓库' : '本地目录'}</div>
                    {projectState.owner && (
                      <div className="p-3 bg-white border border-zinc-100 rounded-xl shadow-sm text-xs text-zinc-700">拥有者: {projectState.owner}</div>
                    )}
                    <div className="p-3 bg-white border border-zinc-100 rounded-xl shadow-sm text-xs text-zinc-700">项目名: {projectState.projectName}</div>
                    <div className="p-3 bg-white border border-zinc-100 rounded-xl shadow-sm text-xs text-zinc-700 break-all">位置: {projectState.displayLocation}</div>
                    <div className="p-3 bg-white border border-zinc-100 rounded-xl shadow-sm text-xs text-zinc-700">模块数: {modules.length || '尚未划分'}</div>
                    <button type="button" onClick={downloadEngineeringFile} disabled={!hasEngineeringFile} className={`w-full rounded-lg border px-3 py-2 text-xs font-semibold ${hasEngineeringFile ? 'border-zinc-200 text-zinc-700 hover:bg-zinc-50' : 'border-zinc-100 text-zinc-300 cursor-not-allowed'}`}><Download size={12} className="inline mr-1" />下载工程文件</button>
                  </>
                ) : <p className="text-[11px] text-zinc-400 italic">等待项目分析</p>}
              </section>
            </div>
          </aside>

          {panels.fileTree && (
            <aside className="w-[280px] border-r border-zinc-200 bg-white overflow-auto">
              <div className="px-4 py-3 border-b border-zinc-200 bg-zinc-50/60 text-[10px] uppercase tracking-widest text-zinc-400 font-bold">文件树</div>
              <div className="p-2">{treeNodes.length > 0 ? <FileTree nodes={treeNodes} onFileSelect={handleFileSelect} selectedPath={selectedFile.path} /> : <div className="p-8 text-center text-zinc-300 text-xs italic">暂无文件显示</div>}</div>
            </aside>
          )}

          <section className="flex-1 flex overflow-hidden">
            {panels.codeViewer && (
              <div className={`${panels.panorama ? 'w-1/2 border-r border-zinc-200' : 'w-full'} bg-white`}>
                <CodeViewer content={selectedFile.content} filename={selectedFile.path} loading={selectedFile.loading} highlightRange={selectedFile.highlightRange} focusKey={selectedFile.focusKey} />
              </div>
            )}
            {panels.panorama && (
              <div className={`${panels.codeViewer ? 'w-1/2' : 'w-full'} bg-zinc-50`}>
                <PanoramaPanel
                  data={functionTree}
                  modules={modules}
                  activeModuleId={activeModuleId}
                  projectName={projectState?.projectName}
                  onNodeSelect={handlePanoramaNodeSelect}
                  onManualDrillDown={handleManualDrillDown}
                  manualDrillLoadingNodeId={manualDrillNodeId}
                />
              </div>
            )}
          </section>
        </div>
      </div>

      {isEngineeringFileOpen && hasEngineeringFile && (
        <div className="fixed inset-0 z-[120] bg-zinc-950/40 backdrop-blur-sm flex items-stretch justify-center p-4 md:p-6">
          <div className="w-full max-w-6xl bg-white rounded-2xl shadow-2xl border border-zinc-200 overflow-hidden flex flex-col">
            <div className="px-5 py-4 border-b border-zinc-200 flex items-center justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-zinc-900">项目分析工程文件</h2>
                <p className="text-xs text-zinc-500">Markdown 工程文件已同步到 LocalStorage。</p>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={downloadEngineeringFile} className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-1.5 text-xs font-semibold text-zinc-700 hover:bg-zinc-50"><Download size={14} />下载</button>
                <button type="button" onClick={() => setIsEngineeringFileOpen(false)} className="inline-flex items-center justify-center rounded-lg border border-zinc-200 p-2 text-zinc-500 hover:bg-zinc-50"><X size={16} /></button>
              </div>
            </div>
            <div className="flex-1 overflow-auto bg-zinc-50">
              <pre className="min-h-full p-5 text-[12px] leading-6 text-zinc-700 whitespace-pre-wrap break-words font-mono">{engineeringMarkdown}</pre>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
