import React, { useEffect, useRef } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface CodeViewerProps {
  content: string;
  filename: string;
  loading?: boolean;
  highlightRange?: { startLine: number; endLine: number } | null;
  focusKey?: number;
}

const getLanguage = (filename: string) => {
  const ext = filename.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'js': return 'javascript';
    case 'jsx': return 'jsx';
    case 'ts': return 'typescript';
    case 'tsx': return 'tsx';
    case 'py': return 'python';
    case 'go': return 'go';
    case 'rs': return 'rust';
    case 'java': return 'java';
    case 'cpp':
    case 'cc': return 'cpp';
    case 'c': return 'c';
    case 'md': return 'markdown';
    case 'json': return 'json';
    case 'css': return 'css';
    case 'html': return 'html';
    case 'sh': return 'bash';
    case 'yml':
    case 'yaml': return 'yaml';
    default: return 'text';
  }
};

export const CodeViewer: React.FC<CodeViewerProps> = ({
  content,
  filename,
  loading,
  highlightRange = null,
  focusKey = 0,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || !highlightRange?.startLine) {
      return;
    }

    const target = containerRef.current.querySelector<HTMLElement>(
      `[data-line-number="${highlightRange.startLine}"]`,
    );
    target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [content, filename, focusKey, highlightRange]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-400 font-mono text-sm animate-pulse bg-white">
        正在读取文件内容...
      </div>
    );
  }

  if (!content && !filename) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-zinc-400 space-y-4 bg-white">
        <div className="w-12 h-12 border border-zinc-100 rounded-xl flex items-center justify-center bg-zinc-50">
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <p className="text-sm font-medium">请选择一个文件以查看其内容</p>
      </div>
    );
  }

  const rangeLabel = highlightRange
    ? `L${highlightRange.startLine}${highlightRange.endLine > highlightRange.startLine ? `-${highlightRange.endLine}` : ''}`
    : '';

  return (
    <div className="h-full flex flex-col bg-white">
      <div className="px-4 py-2 border-b border-zinc-100 bg-zinc-50/50 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="block truncate text-xs font-mono text-zinc-500">{filename}</span>
          {rangeLabel && (
            <span className="inline-flex mt-1 items-center rounded-md bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 border border-emerald-100">
              定位到 {rangeLabel}
            </span>
          )}
        </div>
        <span className="shrink-0 text-[10px] uppercase tracking-wider text-zinc-400 font-bold">{getLanguage(filename)}</span>
      </div>
      <div ref={containerRef} className="flex-1 overflow-auto bg-white custom-scrollbar">
        <SyntaxHighlighter
          language={getLanguage(filename)}
          style={oneLight}
          customStyle={{
            margin: 0,
            padding: '1.5rem',
            fontSize: '13px',
            lineHeight: '1.6',
            background: 'transparent',
          }}
          wrapLines
          showLineNumbers
          lineNumberStyle={{ minWidth: '3em', paddingRight: '1em', color: '#cbd5e1', textAlign: 'right' }}
          lineProps={(lineNumber) => {
            const isHighlighted = Boolean(
              highlightRange &&
              lineNumber >= highlightRange.startLine &&
              lineNumber <= highlightRange.endLine,
            );

            return {
              'data-line-number': lineNumber,
              style: {
                display: 'block',
                backgroundColor: isHighlighted ? 'rgba(16, 185, 129, 0.12)' : 'transparent',
                boxShadow: isHighlighted ? 'inset 3px 0 0 #10b981' : 'none',
              },
            };
          }}
        >
          {content}
        </SyntaxHighlighter>
      </div>
    </div>
  );
};
