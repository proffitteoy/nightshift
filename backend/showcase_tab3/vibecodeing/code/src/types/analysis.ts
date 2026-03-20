import type { AIAnalysisResult } from '../services/aiService';
import type { FunctionBridgeInfo, FunctionRouteInfo } from './functionFlow';
import type { ProjectFile } from './project';
import type { LogEntry } from './log';

export type FunctionNodeStatus = 'pending' | 'locating' | 'analyzing' | 'completed' | 'stopped';
export type WorkflowStatus = 'idle' | 'running' | 'completed' | 'failed' | 'restored';

export interface FunctionSourceLocation {
  startLine: number;
  endLine: number;
  matchedSignature: string;
  strategy: string;
}

export interface FunctionNode {
  id: string;
  name: string;
  filePath: string;
  summary: string;
  children?: FunctionNode[];
  drillDown?: -1 | 0 | 1;
  manualDrillAvailable?: boolean;
  depth?: number;
  status?: FunctionNodeStatus;
  moduleId?: string | null;
  moduleName?: string | null;
  location?: FunctionSourceLocation | null;
  route?: FunctionRouteInfo | null;
  bridge?: FunctionBridgeInfo | null;
}

export interface FlatFunctionNode {
  id: string;
  name: string;
  filePath: string;
  summary: string;
  depth: number;
  parentId: string | null;
  moduleId?: string | null;
  moduleName?: string | null;
}

export interface AnalysisModule {
  id: string;
  name: string;
  summary: string;
  color: string;
  nodeIds: string[];
}

export interface StoredLogEntry extends Omit<LogEntry, 'timestamp'> {
  timestamp: string;
}

export interface ProjectAnalysisSnapshot {
  id: string;
  version: number;
  createdAt: string;
  updatedAt: string;
  githubUrl: string;
  repo: {
    owner: string;
    repo: string;
    fullName: string;
  };
  aiResult: AIAnalysisResult | null;
  files: ProjectFile[];
  functionTree: FunctionNode | null;
  modules: AnalysisModule[];
  logs: StoredLogEntry[];
  engineeringMarkdown: string;
}

export interface ProjectAnalysisSaveInput {
  id?: string;
  createdAt?: string;
  githubUrl: string;
  repo: {
    owner: string;
    repo: string;
  };
  aiResult: AIAnalysisResult | null;
  files: ProjectFile[];
  functionTree: FunctionNode | null;
  modules?: AnalysisModule[];
  logs: StoredLogEntry[];
}

export interface ProjectAnalysisHistoryCard {
  id: string;
  githubUrl: string;
  projectName: string;
  languages: string[];
  techStack: string[];
  summary: string;
  updatedAt: string;
  totalFiles: number;
  codeFiles: number;
  moduleCount: number;
}

export const MODULE_COLOR_PALETTE = [
  '#10b981',
  '#2563eb',
  '#f59e0b',
  '#ef4444',
  '#8b5cf6',
  '#14b8a6',
  '#f97316',
  '#6366f1',
  '#ec4899',
  '#84cc16',
];
