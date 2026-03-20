import React, { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { Download, Maximize2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';
import { AnalysisModule, FunctionNode } from '../types/analysis';
import { formatFunctionRouteLabel } from '../types/functionFlow';
import { moduleLookupById } from '../utils/analysisModules';

interface PanoramaPanelProps {
  data: FunctionNode | null;
  modules?: AnalysisModule[];
  activeModuleId?: string | null;
  projectName?: string;
  onNodeSelect?: (node: FunctionNode) => void;
  onManualDrillDown?: (node: FunctionNode) => void;
  manualDrillLoadingNodeId?: string | null;
}

interface LayoutNode {
  node: FunctionNode;
  x: number;
  y: number;
  depth: number;
  hasChildren: boolean;
  isExpanded: boolean;
  canManualDrill: boolean;
}

interface LayoutLink {
  source: LayoutNode;
  target: LayoutNode;
}

const CARD_WIDTH = 250;
const CARD_HEIGHT = 146;
const HEADER_HEIGHT = 32;
const HORIZONTAL_INDENT = 332;
const VERTICAL_STEP = 184;
const CONTROL_CIRCLE_RADIUS = 11;
const CONTROL_PILL_WIDTH = 84;
const CONTROL_PILL_HEIGHT = 24;
const CONTROL_CENTER_OFFSET = 14;
const CONTROL_CENTER_Y = CARD_HEIGHT / 2 + CONTROL_CENTER_OFFSET;
const VIEW_MARGIN = { top: 32, right: 64, bottom: 56, left: 32 };

function hexToRgba(hex: string, alpha: number) {
  const normalized = hex.replace('#', '');
  const full = normalized.length === 3
    ? normalized.split('').map((char) => `${char}${char}`).join('')
    : normalized;

  const red = Number.parseInt(full.slice(0, 2), 16);
  const green = Number.parseInt(full.slice(2, 4), 16);
  const blue = Number.parseInt(full.slice(4, 6), 16);

  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function getStatusPalette(status: FunctionNode['status'], depth: number) {
  if (depth === 0) {
    return {
      border: '#10b981',
      header: '#ecfdf5',
      headerText: '#065f46',
      badgeBg: '#d1fae5',
      badgeText: '#065f46',
      dot: '#10b981',
    };
  }

  switch (status) {
    case 'pending':
      return {
        border: '#f59e0b',
        header: '#fffbeb',
        headerText: '#92400e',
        badgeBg: '#fef3c7',
        badgeText: '#92400e',
        dot: '#f59e0b',
      };
    case 'locating':
      return {
        border: '#0ea5e9',
        header: '#f0f9ff',
        headerText: '#0c4a6e',
        badgeBg: '#dbeafe',
        badgeText: '#1d4ed8',
        dot: '#0ea5e9',
      };
    case 'analyzing':
      return {
        border: '#14b8a6',
        header: '#f0fdfa',
        headerText: '#115e59',
        badgeBg: '#ccfbf1',
        badgeText: '#115e59',
        dot: '#14b8a6',
      };
    case 'stopped':
      return {
        border: '#94a3b8',
        header: '#f8fafc',
        headerText: '#334155',
        badgeBg: '#e2e8f0',
        badgeText: '#334155',
        dot: '#64748b',
      };
    case 'completed':
    default:
      return {
        border: '#cbd5e1',
        header: '#f1f5f9',
        headerText: '#0f172a',
        badgeBg: '#dcfce7',
        badgeText: '#166534',
        dot: '#10b981',
      };
  }
}

function getStatusLabel(status: FunctionNode['status']) {
  switch (status) {
    case 'pending':
      return '待处理';
    case 'locating':
      return '定位中';
    case 'analyzing':
      return '分析中';
    case 'stopped':
      return '已停止';
    case 'completed':
    default:
      return '完成';
  }
}

function truncateText(value: string, chineseLimit: number, latinLimit: number) {
  const limit = /[^\x00-\xff]/.test(value) ? chineseLimit : latinLimit;
  return value.length > limit ? `${value.slice(0, limit - 1)}...` : value;
}

function canContinueManualDrill(node: FunctionNode) {
  return !node.children?.length
    && node.manualDrillAvailable !== false
    && (node.drillDown === 0 || node.drillDown === 1);
}

function collectExpandableNodeIds(node: FunctionNode | null, ids: Set<string> = new Set<string>()) {
  if (!node) {
    return ids;
  }

  if (node.children?.length) {
    ids.add(node.id);
  }

  for (const child of node.children ?? []) {
    collectExpandableNodeIds(child, ids);
  }

  return ids;
}

function buildIndentedLayout(data: FunctionNode, expandedNodeIds: Set<string>) {
  const nodes: LayoutNode[] = [];
  const links: LayoutLink[] = [];
  let rowIndex = 0;
  let maxDepth = 0;

  const visit = (node: FunctionNode, depth: number, parent?: LayoutNode) => {
    const hasChildren = Boolean(node.children?.length);
    const isExpanded = hasChildren && expandedNodeIds.has(node.id);
    const layoutNode: LayoutNode = {
      node,
      depth,
      hasChildren,
      isExpanded,
      canManualDrill: canContinueManualDrill(node),
      x: depth * HORIZONTAL_INDENT + CARD_WIDTH / 2,
      y: rowIndex * VERTICAL_STEP + CARD_HEIGHT / 2,
    };

    rowIndex += 1;
    maxDepth = Math.max(maxDepth, depth);
    nodes.push(layoutNode);

    if (parent) {
      links.push({ source: parent, target: layoutNode });
    }

    if (!isExpanded) {
      return;
    }

    for (const child of node.children ?? []) {
      visit(child, depth + 1, layoutNode);
    }
  };

  visit(data, 0);

  return {
    nodes,
    links,
    width: maxDepth * HORIZONTAL_INDENT + CARD_WIDTH,
    height: Math.max(rowIndex, 1) * VERTICAL_STEP,
  };
}

export const PanoramaPanel: React.FC<PanoramaPanelProps> = ({
  data,
  modules = [],
  activeModuleId = null,
  projectName = 'project',
  onNodeSelect,
  onManualDrillDown,
  manualDrillLoadingNodeId = null,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const zoomTransformRef = useRef(d3.zoomIdentity);
  const expansionInitializedRef = useRef(false);
  const previousExpandableIdsRef = useRef<Set<string>>(new Set<string>());
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(new Set<string>());

  const expandableNodeIds = collectExpandableNodeIds(data);

  useEffect(() => {
    const nextExpandableNodeIds = collectExpandableNodeIds(data);

    if (!data) {
      zoomTransformRef.current = d3.zoomIdentity;
      expansionInitializedRef.current = false;
      previousExpandableIdsRef.current = new Set<string>();
      setExpandedNodeIds(new Set<string>());
      return;
    }

    setExpandedNodeIds((prev) => {
      if (!expansionInitializedRef.current) {
        expansionInitializedRef.current = true;
        previousExpandableIdsRef.current = new Set(nextExpandableNodeIds);
        return new Set(nextExpandableNodeIds);
      }

      const next = new Set([...prev].filter((nodeId) => nextExpandableNodeIds.has(nodeId)));
      for (const nodeId of nextExpandableNodeIds) {
        if (!previousExpandableIdsRef.current.has(nodeId)) {
          next.add(nodeId);
        }
      }

      previousExpandableIdsRef.current = new Set(nextExpandableNodeIds);
      return next;
    });
  }, [data]);

  const handleReset = () => {
    if (svgRef.current && zoomRef.current) {
      d3.select(svgRef.current)
        .transition()
        .duration(300)
        .call(zoomRef.current.transform, d3.zoomIdentity);
    }
  };

  const handleZoomIn = () => {
    if (svgRef.current && zoomRef.current) {
      d3.select(svgRef.current)
        .transition()
        .duration(200)
        .call(zoomRef.current.scaleBy, 1.2);
    }
  };

  const handleZoomOut = () => {
    if (svgRef.current && zoomRef.current) {
      d3.select(svgRef.current)
        .transition()
        .duration(200)
        .call(zoomRef.current.scaleBy, 0.8);
    }
  };

  const handleExpandAll = () => {
    setExpandedNodeIds(new Set(collectExpandableNodeIds(data)));
  };

  const handleCollapseAll = () => {
    setExpandedNodeIds(new Set<string>());
  };

  const handleDownloadSvg = () => {
    const svgElement = svgRef.current;
    if (!svgElement || !data) {
      return;
    }

    const clonedSvg = svgElement.cloneNode(true) as SVGSVGElement;
    const viewBox = clonedSvg.getAttribute('viewBox') || '0 0 1200 800';
    const [, , width, height] = viewBox.split(/\s+/);
    clonedSvg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clonedSvg.setAttribute('version', '1.1');
    clonedSvg.setAttribute('width', width || '1200');
    clonedSvg.setAttribute('height', height || '800');
    clonedSvg.removeAttribute('class');

    const serializedSvg = new XMLSerializer().serializeToString(clonedSvg);
    const blob = new Blob(
      [`<?xml version="1.0" encoding="UTF-8"?>\n${serializedSvg}`],
      { type: 'image/svg+xml;charset=utf-8' },
    );
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const safeName = (projectName || 'project').replace(/[^\w.-]+/g, '-');
    link.href = objectUrl;
    link.download = `${safeName}-panorama.svg`;
    link.click();
    URL.revokeObjectURL(objectUrl);
  };

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    if (!data || !svgRef.current) {
      return;
    }

    const moduleLookup = moduleLookupById(modules);
    const layout = buildIndentedLayout(data, expandedNodeIds);
    const viewWidth = layout.width + VIEW_MARGIN.left + VIEW_MARGIN.right;
    const viewHeight = layout.height + VIEW_MARGIN.top + VIEW_MARGIN.bottom;

    svg
      .attr('viewBox', `0 0 ${viewWidth} ${viewHeight}`)
      .style('font', '10px sans-serif')
      .style('user-select', 'none');

    const rootGroup = svg
      .append('g')
      .attr('transform', `translate(${VIEW_MARGIN.left}, ${VIEW_MARGIN.top})`);

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 2.5])
      .on('zoom', (event) => {
        zoomTransformRef.current = event.transform;
        rootGroup.attr(
          'transform',
          `translate(${event.transform.x + VIEW_MARGIN.left}, ${event.transform.y + VIEW_MARGIN.top}) scale(${event.transform.k})`,
        );
      });

    zoomRef.current = zoom;
    svg.call(zoom);
    svg.call(zoom.transform, zoomTransformRef.current);

    const isNodeHighlighted = (node: FunctionNode) => {
      if (!activeModuleId) {
        return true;
      }

      return node.moduleId === activeModuleId;
    };

    rootGroup
      .append('g')
      .attr('fill', 'none')
      .selectAll('path')
      .data(layout.links)
      .join('path')
      .attr('d', (link) => {
        const sourceX = link.source.x;
        const sourceControlY = link.source.y + CONTROL_CENTER_Y;
        const targetLeftX = link.target.x - CARD_WIDTH / 2;
        const targetY = link.target.y;

        return [`M${sourceX},${sourceControlY}`, `L${sourceX},${targetY}`, `L${targetLeftX},${targetY}`].join(' ');
      })
      .attr('stroke', (link) => {
        const module = moduleLookup.get(link.target.node.moduleId || '');
        if (activeModuleId && link.target.node.moduleId !== activeModuleId) {
          return '#d4d4d8';
        }
        return module?.color || '#475569';
      })
      .attr('stroke-opacity', (link) => {
        if (!activeModuleId) {
          return 0.9;
        }
        return link.target.node.moduleId === activeModuleId ? 0.95 : 0.35;
      })
      .attr('stroke-width', 2)
      .attr('stroke-dasharray', '10 8');

    const nodeGroup = rootGroup
      .append('g')
      .selectAll('g')
      .data(layout.nodes)
      .join('g')
      .attr('transform', (entry) => `translate(${entry.x},${entry.y})`)
      .style('cursor', onNodeSelect ? 'pointer' : 'default')
      .on('click', (_event, entry) => {
        onNodeSelect?.(entry.node);
      });

    nodeGroup
      .append('rect')
      .attr('x', -CARD_WIDTH / 2)
      .attr('y', -CARD_HEIGHT / 2)
      .attr('width', CARD_WIDTH)
      .attr('height', CARD_HEIGHT)
      .attr('rx', 10)
      .attr('fill', (entry) => (isNodeHighlighted(entry.node) ? 'white' : '#f8fafc'))
      .attr('stroke', (entry) => {
        const module = moduleLookup.get(entry.node.moduleId || '');
        if (isNodeHighlighted(entry.node) && module) {
          return module.color;
        }
        return activeModuleId ? '#d4d4d8' : getStatusPalette(entry.node.status, entry.depth).border;
      })
      .attr('stroke-width', (entry) => (entry.depth === 0 ? 3 : 1.5))
      .style('filter', (entry) => (isNodeHighlighted(entry.node) ? 'drop-shadow(0 4px 6px rgb(0 0 0 / 0.08))' : 'none'));

    nodeGroup
      .append('path')
      .attr(
        'd',
        `M${-CARD_WIDTH / 2 + 10},${-CARD_HEIGHT / 2} h${CARD_WIDTH - 20} a10,10 0 0 1 10,10 v${HEADER_HEIGHT - 10} h${-CARD_WIDTH} v${-HEADER_HEIGHT + 10} a10,10 0 0 1 10,-10 z`,
      )
      .attr('fill', (entry) => {
        const module = moduleLookup.get(entry.node.moduleId || '');
        if (isNodeHighlighted(entry.node) && module) {
          return module.color;
        }
        return activeModuleId ? '#e2e8f0' : getStatusPalette(entry.node.status, entry.depth).header;
      });

    nodeGroup
      .append('line')
      .attr('x1', -CARD_WIDTH / 2)
      .attr('y1', -CARD_HEIGHT / 2 + HEADER_HEIGHT)
      .attr('x2', CARD_WIDTH / 2)
      .attr('y2', -CARD_HEIGHT / 2 + HEADER_HEIGHT)
      .attr('stroke', '#e2e8f0')
      .attr('stroke-width', 1);

    nodeGroup
      .append('text')
      .attr('dy', -CARD_HEIGHT / 2 + 20)
      .attr('x', 0)
      .attr('text-anchor', 'middle')
      .attr('font-weight', '700')
      .attr('font-size', '12px')
      .attr('fill', (entry) => {
        const module = moduleLookup.get(entry.node.moduleId || '');
        if (isNodeHighlighted(entry.node) && module) {
          return '#ffffff';
        }
        return activeModuleId ? '#475569' : getStatusPalette(entry.node.status, entry.depth).headerText;
      })
      .text((entry) => truncateText(entry.node.name, 14, 22));

    nodeGroup
      .append('text')
      .attr('dy', -CARD_HEIGHT / 2 + HEADER_HEIGHT + 18)
      .attr('x', -CARD_WIDTH / 2 + 12)
      .attr('text-anchor', 'start')
      .attr('font-size', '9px')
      .attr('font-weight', '700')
      .attr('fill', '#94a3b8')
      .text('文件');

    nodeGroup
      .append('text')
      .attr('dy', -CARD_HEIGHT / 2 + HEADER_HEIGHT + 18)
      .attr('x', -CARD_WIDTH / 2 + 44)
      .attr('text-anchor', 'start')
      .attr('font-size', '10px')
      .attr('font-family', 'monospace')
      .attr('fill', (entry) => (isNodeHighlighted(entry.node) ? '#334155' : '#94a3b8'))
      .text((entry) => truncateText(entry.node.filePath, 16, 24));

    nodeGroup
      .append('text')
      .attr('dy', -CARD_HEIGHT / 2 + HEADER_HEIGHT + 40)
      .attr('x', -CARD_WIDTH / 2 + 12)
      .attr('text-anchor', 'start')
      .attr('font-size', '9px')
      .attr('font-weight', '700')
      .attr('fill', '#94a3b8')
      .text('简介');

    nodeGroup
      .append('text')
      .attr('dy', -CARD_HEIGHT / 2 + HEADER_HEIGHT + 40)
      .attr('x', -CARD_WIDTH / 2 + 44)
      .attr('text-anchor', 'start')
      .attr('font-size', '10px')
      .attr('fill', (entry) => (isNodeHighlighted(entry.node) ? '#475569' : '#94a3b8'))
      .text((entry) => truncateText(entry.node.summary, 15, 18));

    nodeGroup
      .append('text')
      .attr('dy', -CARD_HEIGHT / 2 + HEADER_HEIGHT + 62)
      .attr('x', -CARD_WIDTH / 2 + 12)
      .attr('text-anchor', 'start')
      .attr('font-size', '9px')
      .attr('font-weight', '700')
      .attr('fill', '#94a3b8')
      .text((entry) => entry.node.route ? 'URL' : '');

    nodeGroup
      .append('text')
      .attr('dy', -CARD_HEIGHT / 2 + HEADER_HEIGHT + 62)
      .attr('x', -CARD_WIDTH / 2 + 44)
      .attr('text-anchor', 'start')
      .attr('font-size', '9px')
      .attr('font-family', 'monospace')
      .attr('fill', (entry) => entry.node.route && isNodeHighlighted(entry.node) ? '#0f766e' : '#94a3b8')
      .text((entry) => truncateText(formatFunctionRouteLabel(entry.node.route), 14, 18));

    nodeGroup
      .append('rect')
      .attr('x', -CARD_WIDTH / 2 + 12)
      .attr('y', CARD_HEIGHT / 2 - 26)
      .attr('width', 84)
      .attr('height', 16)
      .attr('rx', 8)
      .attr('fill', (entry) => {
        const module = moduleLookup.get(entry.node.moduleId || '');
        if (module) {
          return hexToRgba(module.color, isNodeHighlighted(entry.node) ? 0.14 : 0.08);
        }
        return activeModuleId ? '#e2e8f0' : '#f1f5f9';
      });

    nodeGroup
      .append('text')
      .attr('x', -CARD_WIDTH / 2 + 54)
      .attr('y', CARD_HEIGHT / 2 - 15)
      .attr('text-anchor', 'middle')
      .attr('font-size', '9px')
      .attr('font-weight', '700')
      .attr('fill', (entry) => {
        const module = moduleLookup.get(entry.node.moduleId || '');
        return module && isNodeHighlighted(entry.node) ? module.color : '#64748b';
      })
      .text((entry) => truncateText(entry.node.moduleName || '未分组', 6, 8));

    nodeGroup
      .append('rect')
      .attr('x', CARD_WIDTH / 2 - 78)
      .attr('y', CARD_HEIGHT / 2 - 26)
      .attr('width', 66)
      .attr('height', 16)
      .attr('rx', 8)
      .attr('fill', (entry) => activeModuleId && !isNodeHighlighted(entry.node)
        ? '#e2e8f0'
        : getStatusPalette(entry.node.status, entry.depth).badgeBg);

    nodeGroup
      .append('text')
      .attr('x', CARD_WIDTH / 2 - 45)
      .attr('y', CARD_HEIGHT / 2 - 15)
      .attr('text-anchor', 'middle')
      .attr('font-size', '9px')
      .attr('font-weight', '700')
      .attr('fill', (entry) => activeModuleId && !isNodeHighlighted(entry.node)
        ? '#64748b'
        : getStatusPalette(entry.node.status, entry.depth).badgeText)
      .text((entry) => getStatusLabel(entry.node.status));

    nodeGroup
      .append('circle')
      .attr('cx', CARD_WIDTH / 2 - 16)
      .attr('cy', -CARD_HEIGHT / 2 + 16)
      .attr('r', 4)
      .attr('fill', (entry) => {
        const module = moduleLookup.get(entry.node.moduleId || '');
        if (module && isNodeHighlighted(entry.node)) {
          return '#ffffff';
        }
        return activeModuleId && !isNodeHighlighted(entry.node)
          ? '#94a3b8'
          : getStatusPalette(entry.node.status, entry.depth).dot;
      })
      .attr('cursor', 'help')
      .append('title')
      .text((entry) => {
        const routeLabel = formatFunctionRouteLabel(entry.node.route);
        return routeLabel ? `${entry.node.summary}\n${routeLabel}` : entry.node.summary;
      });

    nodeGroup
      .append('title')
      .text((entry) => entry.node.location
        ? `点击打开源码: ${entry.node.filePath}:${entry.node.location.startLine}`
        : `点击打开源码: ${entry.node.filePath}`);

    nodeGroup
      .filter((entry) => entry.hasChildren || entry.canManualDrill)
      .append('line')
      .attr('x1', 0)
      .attr('y1', CARD_HEIGHT / 2)
      .attr('x2', 0)
      .attr('y2', (entry) => entry.canManualDrill
        ? CONTROL_CENTER_Y - CONTROL_PILL_HEIGHT / 2
        : CONTROL_CENTER_Y - CONTROL_CIRCLE_RADIUS)
      .attr('stroke', '#cbd5e1')
      .attr('stroke-width', 2);

    const toggleControls = nodeGroup
      .filter((entry) => entry.hasChildren)
      .append('g')
      .style('cursor', 'pointer')
      .on('click', (event, entry) => {
        event.stopPropagation();
        setExpandedNodeIds((prev) => {
          const next = new Set(prev);
          if (next.has(entry.node.id)) {
            next.delete(entry.node.id);
          } else {
            next.add(entry.node.id);
          }
          return next;
        });
      });

    toggleControls
      .append('circle')
      .attr('cx', 0)
      .attr('cy', CONTROL_CENTER_Y)
      .attr('r', CONTROL_CIRCLE_RADIUS)
      .attr('fill', (entry) => (entry.isExpanded ? '#ffffff' : '#f8fafc'))
      .attr('stroke', (entry) => (entry.isExpanded ? '#0f172a' : '#94a3b8'))
      .attr('stroke-width', 1.5);

    toggleControls
      .append('text')
      .attr('x', 0)
      .attr('y', CONTROL_CENTER_Y + 4)
      .attr('text-anchor', 'middle')
      .attr('font-size', '14px')
      .attr('font-weight', '700')
      .attr('fill', '#0f172a')
      .text((entry) => (entry.isExpanded ? '-' : '+'));

    toggleControls
      .append('title')
      .text((entry) => (entry.isExpanded ? '收起子节点' : '展开子节点'));

    const manualControls = nodeGroup
      .filter((entry) => entry.canManualDrill)
      .append('g')
      .style('cursor', (entry) => (manualDrillLoadingNodeId === entry.node.id ? 'wait' : 'pointer'))
      .on('click', (event, entry) => {
        event.stopPropagation();
        if (manualDrillLoadingNodeId === entry.node.id) {
          return;
        }
        onManualDrillDown?.(entry.node);
      });

    manualControls
      .append('rect')
      .attr('x', -CONTROL_PILL_WIDTH / 2)
      .attr('y', CONTROL_CENTER_Y - CONTROL_PILL_HEIGHT / 2)
      .attr('width', CONTROL_PILL_WIDTH)
      .attr('height', CONTROL_PILL_HEIGHT)
      .attr('rx', CONTROL_PILL_HEIGHT / 2)
      .attr('fill', (entry) => {
        if (manualDrillLoadingNodeId === entry.node.id) {
          return '#d1fae5';
        }
        return '#ecfccb';
      })
      .attr('stroke', (entry) => (manualDrillLoadingNodeId === entry.node.id ? '#10b981' : '#84cc16'))
      .attr('stroke-width', 1.5);

    manualControls
      .append('text')
      .attr('x', 0)
      .attr('y', CONTROL_CENTER_Y + 3.5)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('font-weight', '700')
      .attr('fill', '#3f6212')
      .text((entry) => (manualDrillLoadingNodeId === entry.node.id ? '下钻中...' : '继续下钻'));

    manualControls
      .append('title')
      .text((entry) => (manualDrillLoadingNodeId === entry.node.id ? '正在手动下钻' : '继续下钻一层'));
  }, [activeModuleId, data, expandedNodeIds, manualDrillLoadingNodeId, modules, onManualDrillDown, onNodeSelect]);

  return (
    <div className="w-full h-full bg-zinc-50 relative overflow-hidden flex flex-col">
      <div className="px-4 py-2 border-b border-zinc-200 bg-white flex items-center justify-between gap-3">
        <h3 className="text-[10px] uppercase tracking-widest text-zinc-400 font-bold flex items-center gap-2">
          <Maximize2 size={12} className="text-emerald-500" />
          全景调用图
        </h3>
        <div className="flex items-center gap-1">
          <button
            onClick={handleExpandAll}
            disabled={expandableNodeIds.size === 0}
            className={`px-2 py-1 rounded text-[11px] transition-colors ${
              expandableNodeIds.size > 0
                ? 'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900'
                : 'text-zinc-300 cursor-not-allowed'
            }`}
            title="全部展开"
          >
            全部展开
          </button>
          <button
            onClick={handleCollapseAll}
            disabled={expandableNodeIds.size === 0}
            className={`px-2 py-1 rounded text-[11px] transition-colors ${
              expandableNodeIds.size > 0
                ? 'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900'
                : 'text-zinc-300 cursor-not-allowed'
            }`}
            title="全部收起"
          >
            全部收起
          </button>
          <button
            onClick={handleDownloadSvg}
            disabled={!data}
            className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] transition-colors ${
              data
                ? 'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900'
                : 'text-zinc-300 cursor-not-allowed'
            }`}
            title="下载 SVG"
          >
            <Download size={13} />
            下载 SVG
          </button>
          <button
            onClick={handleZoomIn}
            className="p-1 hover:bg-zinc-100 rounded text-zinc-400 hover:text-zinc-900 transition-colors"
            title="放大"
          >
            <ZoomIn size={14} />
          </button>
          <button
            onClick={handleZoomOut}
            className="p-1 hover:bg-zinc-100 rounded text-zinc-400 hover:text-zinc-900 transition-colors"
            title="缩小"
          >
            <ZoomOut size={14} />
          </button>
          <button
            onClick={handleReset}
            className="p-1 hover:bg-zinc-100 rounded text-zinc-400 hover:text-zinc-900 transition-colors"
            title="重置视图"
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </div>
      <div className="flex-1 relative">
        <svg ref={svgRef} className="w-full h-full cursor-move" />
      </div>
    </div>
  );
};
