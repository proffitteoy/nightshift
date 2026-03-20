import React, { useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cpu,
  FileJson,
  Info,
  Maximize2,
  MessageSquare,
  Send,
  Sparkles,
  Terminal,
  X,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { WorkflowStatus } from '../types/analysis';
import { AIUsageStats, LogEntry } from '../types/log';

interface LogPanelProps {
  logs: LogEntry[];
  workflowStatus?: WorkflowStatus;
  workflowLabel?: string;
}

function truncateLongFields(obj: any): any {
  if (typeof obj !== 'object' || obj === null) {
    return obj;
  }

  const nextObj: any = Array.isArray(obj) ? [] : {};
  for (const key in obj) {
    let value = obj[key];
    if (typeof value === 'string' && value.length > 500) {
      const remaining = value.length - 500;
      value = `${value.substring(0, 500)}... [还有 ${remaining} 个字符]`;
    } else if (typeof value === 'object') {
      value = truncateLongFields(value);
    }
    nextObj[key] = value;
  }
  return nextObj;
}

function getWorkflowBadge(status: WorkflowStatus = 'idle') {
  switch (status) {
    case 'running':
      return {
        label: '工作中',
        className: 'bg-amber-100 text-amber-800',
      };
    case 'completed':
      return {
        label: '已结束',
        className: 'bg-emerald-100 text-emerald-800',
      };
    case 'failed':
      return {
        label: '失败',
        className: 'bg-red-100 text-red-700',
      };
    case 'restored':
      return {
        label: '历史快照',
        className: 'bg-blue-100 text-blue-700',
      };
    case 'idle':
    default:
      return {
        label: '待开始',
        className: 'bg-zinc-100 text-zinc-600',
      };
  }
}

function readUsageNumber(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

function extractUsageFromUnknown(response: unknown): AIUsageStats | null {
  if (!response || typeof response !== 'object') {
    return null;
  }

  const usage = (response as Record<string, any>).usage;
  if (!usage || typeof usage !== 'object') {
    return null;
  }

  const inputTokens = readUsageNumber(
    usage.prompt_tokens ?? usage.input_tokens ?? usage.promptTokens ?? usage.inputTokens,
  );
  const outputTokens = readUsageNumber(
    usage.completion_tokens ?? usage.output_tokens ?? usage.completionTokens ?? usage.outputTokens,
  );
  const totalTokens = readUsageNumber(usage.total_tokens ?? usage.totalTokens) || (inputTokens + outputTokens);

  if (inputTokens === 0 && outputTokens === 0 && totalTokens === 0) {
    return null;
  }

  return {
    inputTokens,
    outputTokens,
    totalTokens,
  };
}

function getUsage(log: LogEntry): AIUsageStats | null {
  return log.details?.usage || extractUsageFromUnknown(log.details?.response);
}

function buildAiStats(logs: LogEntry[]) {
  return logs.reduce(
    (acc, log) => {
      if (log.type !== 'ai') {
        return acc;
      }

      const usage = getUsage(log);
      acc.callCount += 1;
      if (usage) {
        acc.inputTokens += usage.inputTokens;
        acc.outputTokens += usage.outputTokens;
        acc.totalTokens += usage.totalTokens;
      }
      return acc;
    },
    {
      callCount: 0,
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
    },
  );
}

const DetailSection: React.FC<{ title: string; icon: React.ReactNode; data: any }> = ({ title, icon, data }) => {
  const [isOpen, setIsOpen] = useState(false);
  if (!data) {
    return null;
  }

  return (
    <div className="mt-2 border border-zinc-200 rounded-lg overflow-hidden bg-white">
      <div
        className="px-3 py-1.5 bg-zinc-50 flex items-center justify-between cursor-pointer hover:bg-zinc-100 transition-colors"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
          {icon}
          {title}
        </div>
        <span className="text-zinc-400">
          {isOpen ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        </span>
      </div>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="p-2 text-[9px] font-mono text-zinc-500 overflow-auto max-h-64 custom-scrollbar bg-white">
              <pre>{JSON.stringify(truncateLongFields(data), null, 2)}</pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const LogItem: React.FC<{ log: LogEntry }> = ({ log }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const usage = getUsage(log);

  const getIcon = () => {
    switch (log.type) {
      case 'success':
        return <CheckCircle2 size={12} className="text-emerald-500" />;
      case 'error':
        return <AlertCircle size={12} className="text-red-500" />;
      case 'ai':
        return <Cpu size={12} className="text-blue-500" />;
      default:
        return <Info size={12} className="text-zinc-400" />;
    }
  };

  return (
    <div className="border-b border-zinc-100 last:border-0">
      <div
        className="flex items-start gap-2 p-2 hover:bg-zinc-50 cursor-pointer transition-colors"
        onClick={() => log.details && setIsExpanded(!isExpanded)}
      >
        <div className="mt-0.5">{getIcon()}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-zinc-400 font-mono">
              {log.timestamp.toLocaleTimeString([], {
                hour12: false,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              })}
            </span>
            {log.details && (
              <span className="text-zinc-300">
                {isExpanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
              </span>
            )}
          </div>
          <p className="text-[11px] text-zinc-600 leading-tight break-words font-medium">{log.message}</p>
          {usage && (
            <div className="mt-1 flex flex-wrap gap-1">
              <span className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[9px] font-semibold text-blue-700 border border-blue-100">
                输入 {usage.inputTokens}
              </span>
              <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-700 border border-emerald-100">
                输出 {usage.outputTokens}
              </span>
            </div>
          )}
        </div>
      </div>

      <AnimatePresence>
        {isExpanded && log.details && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden bg-zinc-50/50 px-3 pb-3"
          >
            <DetailSection title="Token 用量" icon={<Sparkles size={10} />} data={usage} />
            <DetailSection title="请求内容" icon={<Send size={10} />} data={log.details.request} />
            <DetailSection title="响应内容" icon={<MessageSquare size={10} />} data={log.details.response} />
            <DetailSection title="过滤文件" icon={<FileJson size={10} />} data={log.details.filteredFiles} />
            <DetailSection title="附加数据" icon={<Info size={10} />} data={log.details.data} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

function StatsStrip({ logs }: { logs: LogEntry[] }) {
  const stats = buildAiStats(logs);

  return (
    <div className="grid grid-cols-3 gap-2 px-4 pb-3">
      <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2">
        <p className="text-[10px] uppercase tracking-wider text-zinc-400 font-bold">AI 调用</p>
        <p className="mt-1 text-sm font-semibold text-zinc-700">{stats.callCount}</p>
      </div>
      <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2">
        <p className="text-[10px] uppercase tracking-wider text-zinc-400 font-bold">输入 Token</p>
        <p className="mt-1 text-sm font-semibold text-zinc-700">{stats.inputTokens}</p>
      </div>
      <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2">
        <p className="text-[10px] uppercase tracking-wider text-zinc-400 font-bold">输出 Token</p>
        <p className="mt-1 text-sm font-semibold text-zinc-700">{stats.outputTokens}</p>
      </div>
    </div>
  );
}

export const LogPanel: React.FC<LogPanelProps> = ({
  logs,
  workflowStatus = 'idle',
  workflowLabel = '等待开始分析',
}) => {
  const [isOpen, setIsOpen] = useState(true);
  const [isFullScreen, setIsFullScreen] = useState(false);
  const badge = getWorkflowBadge(workflowStatus);

  const renderContent = () => (
    <div className="flex flex-col">
      <div className="flex flex-col-reverse">
        {logs.map((log) => (
          <LogItem key={log.id} log={log} />
        ))}
      </div>
      {logs.length === 0 && (
        <div className="py-12 flex items-center justify-center text-[10px] text-zinc-300 italic">
          暂无工作日志
        </div>
      )}
    </div>
  );

  return (
    <>
      <div className="border-b border-zinc-200 flex flex-col bg-white">
        <div className="px-4 py-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 cursor-pointer group min-w-0" onClick={() => setIsOpen(!isOpen)}>
            <h3 className="text-[10px] uppercase tracking-widest text-zinc-400 font-bold flex items-center gap-2 group-hover:text-zinc-600 transition-colors">
              <Terminal size={12} />
              AI 日志
            </h3>
            <span className="text-zinc-300">
              {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${badge.className}`}>
              {badge.label}
            </span>
            <button
              onClick={() => setIsFullScreen(true)}
              className="p-1 hover:bg-zinc-100 rounded text-zinc-400 hover:text-zinc-600 transition-colors"
              title="全屏查看"
            >
              <Maximize2 size={12} />
            </button>
          </div>
        </div>

        <div className="px-4 pb-2">
          <p className="text-[11px] text-zinc-500 truncate">{workflowLabel}</p>
        </div>

        <StatsStrip logs={logs} />

        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: 220 }}
              exit={{ height: 0 }}
              className="overflow-auto custom-scrollbar border-t border-zinc-100"
            >
              {renderContent()}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {isFullScreen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[100] bg-white flex flex-col"
          >
            <div className="h-14 border-b border-zinc-200 flex items-center justify-between px-6 bg-zinc-50">
              <div className="flex items-center gap-3 min-w-0">
                <Terminal size={20} className="text-zinc-400" />
                <h2 className="font-bold text-zinc-800">AI 工作日志</h2>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${badge.className}`}>
                  {badge.label}
                </span>
                <span className="text-xs text-zinc-500 truncate">{workflowLabel}</span>
              </div>
              <button
                onClick={() => setIsFullScreen(false)}
                className="p-2 hover:bg-zinc-200 rounded-full text-zinc-500 transition-colors"
              >
                <X size={20} />
              </button>
            </div>
            <StatsStrip logs={logs} />
            <div className="flex-1 overflow-auto p-6 custom-scrollbar bg-white">
              <div className="max-w-4xl mx-auto border border-zinc-100 rounded-xl shadow-sm overflow-hidden">
                {renderContent()}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};
