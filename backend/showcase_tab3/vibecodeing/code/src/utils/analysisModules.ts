import { AnalysisModule, FlatFunctionNode, FunctionNode, MODULE_COLOR_PALETTE } from '../types/analysis';

interface RawModule {
  name: string;
  summary: string;
  nodeIds: string[];
}

function slugifyModuleName(name: string, index: number) {
  const normalized = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-')
    .replace(/^-+|-+$/g, '');

  return normalized ? `module-${normalized}` : `module-${index + 1}`;
}

export function flattenFunctionTree(
  node: FunctionNode | null,
  parentId: string | null = null,
  depth = 0,
): FlatFunctionNode[] {
  if (!node) {
    return [];
  }

  const currentNode: FlatFunctionNode = {
    id: node.id,
    name: node.name,
    filePath: node.filePath,
    summary: node.summary,
    depth,
    parentId,
    moduleId: node.moduleId,
    moduleName: node.moduleName,
  };

  return [
    currentNode,
    ...(node.children ?? []).flatMap((child) => flattenFunctionTree(child, node.id, depth + 1)),
  ];
}

export function applyModulesToFunctionTree(
  node: FunctionNode | null,
  modules: AnalysisModule[],
): FunctionNode | null {
  if (!node) {
    return null;
  }

  const moduleLookup = new Map<string, AnalysisModule>();
  for (const module of modules) {
    for (const nodeId of module.nodeIds) {
      moduleLookup.set(nodeId, module);
    }
  }

  const visit = (currentNode: FunctionNode): FunctionNode => {
    const module = moduleLookup.get(currentNode.id);

    return {
      ...currentNode,
      moduleId: module?.id || null,
      moduleName: module?.name || null,
      children: currentNode.children?.map(visit),
    };
  };

  return visit(node);
}

export function normalizeModuleAssignments(
  rawModules: RawModule[],
  nodes: FlatFunctionNode[],
): AnalysisModule[] {
  const knownNodeIds = new Set(nodes.map((node) => node.id));
  const assignedNodeIds = new Set<string>();

  const normalizedModules: AnalysisModule[] = rawModules
    .slice(0, 10)
    .map((module, index) => {
      const uniqueNodeIds: string[] = [];

      for (const nodeId of module.nodeIds) {
        if (!knownNodeIds.has(nodeId) || assignedNodeIds.has(nodeId) || uniqueNodeIds.includes(nodeId)) {
          continue;
        }

        assignedNodeIds.add(nodeId);
        uniqueNodeIds.push(nodeId);
      }

      return {
        id: slugifyModuleName(module.name, index),
        name: module.name.trim() || `模块 ${index + 1}`,
        summary: module.summary.trim() || '暂无说明',
        color: MODULE_COLOR_PALETTE[index % MODULE_COLOR_PALETTE.length],
        nodeIds: uniqueNodeIds,
      };
    })
    .filter((module) => module.nodeIds.length > 0);

  const missingNodeIds = nodes
    .map((node) => node.id)
    .filter((nodeId) => !assignedNodeIds.has(nodeId));

  if (missingNodeIds.length === 0) {
    return normalizedModules;
  }

  const fallbackModule = normalizedModules.find((module) => module.name === '未归类');
  if (fallbackModule) {
    fallbackModule.nodeIds.push(...missingNodeIds);
    return normalizedModules;
  }

  if (normalizedModules.length < 10) {
    normalizedModules.push({
      id: 'module-unassigned',
      name: '未归类',
      summary: 'AI 未明确划分的函数节点。',
      color: MODULE_COLOR_PALETTE[normalizedModules.length % MODULE_COLOR_PALETTE.length],
      nodeIds: missingNodeIds,
    });
    return normalizedModules;
  }

  normalizedModules[normalizedModules.length - 1].nodeIds.push(...missingNodeIds);
  return normalizedModules;
}

export function moduleLookupById(modules: AnalysisModule[]) {
  return new Map(modules.map((module) => [module.id, module]));
}
