import React from 'react';
import { Layers3, RefreshCcw } from 'lucide-react';
import { AnalysisModule } from '../types/analysis';

interface ModuleListPanelProps {
  modules: AnalysisModule[];
  activeModuleId: string | null;
  loading?: boolean;
  canReanalyze?: boolean;
  reanalyzing?: boolean;
  onSelectModule: (moduleId: string | null) => void;
  onReanalyzeModules?: () => void;
}

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

export const ModuleListPanel: React.FC<ModuleListPanelProps> = ({
  modules,
  activeModuleId,
  loading = false,
  canReanalyze = false,
  reanalyzing = false,
  onSelectModule,
  onReanalyzeModules,
}) => {
  return (
    <div className="pt-6 border-t border-zinc-200">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h3 className="text-[10px] uppercase tracking-widest text-zinc-400 font-bold flex items-center gap-2">
          <Layers3 size={12} className="text-emerald-500" />
          功能模块
        </h3>
        {activeModuleId && (
          <button
            type="button"
            onClick={() => onSelectModule(null)}
            className="inline-flex items-center gap-1 text-[10px] font-semibold text-zinc-500 hover:text-zinc-700"
          >
            <RefreshCcw size={10} />
            清除筛选
          </button>
        )}
      </div>

      {loading ? (
        <div className="space-y-2">
          <div className="h-16 rounded-xl bg-zinc-100 animate-pulse" />
          <div className="h-16 rounded-xl bg-zinc-100 animate-pulse" />
        </div>
      ) : modules.length > 0 ? (
        <div className="space-y-2">
          {modules.map((module) => {
            const isActive = activeModuleId === module.id;
            return (
              <button
                key={module.id}
                type="button"
                onClick={() => onSelectModule(isActive ? null : module.id)}
                className={`w-full text-left rounded-xl border p-3 transition-all ${isActive ? 'shadow-sm scale-[1.01]' : 'hover:border-zinc-300 hover:bg-zinc-50'}`}
                style={{
                  borderColor: isActive ? module.color : '#e4e4e7',
                  backgroundColor: isActive ? hexToRgba(module.color, 0.12) : '#ffffff',
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className="inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-bold"
                        style={{
                          backgroundColor: hexToRgba(module.color, 0.14),
                          color: module.color,
                        }}
                      >
                        {module.name}
                      </span>
                      <span className="text-[10px] text-zinc-400">{module.nodeIds.length} 个节点</span>
                    </div>
                    <p className="text-[11px] leading-5 text-zinc-600">{module.summary}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <p className="text-[11px] text-zinc-400 italic">
          完成函数分析后会在这里显示模块列表；旧项目可点击下方按钮补齐模块信息。
        </p>
      )}

      <button
        type="button"
        onClick={onReanalyzeModules}
        disabled={!canReanalyze || reanalyzing || !onReanalyzeModules}
        className={`mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl border px-3 py-2 text-[11px] font-semibold transition-colors ${
          !canReanalyze || reanalyzing || !onReanalyzeModules
            ? 'cursor-not-allowed border-zinc-200 bg-zinc-100 text-zinc-400'
            : 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
        }`}
      >
        <RefreshCcw size={12} className={reanalyzing ? 'animate-spin' : ''} />
        {reanalyzing ? '重新分析中...' : '重新分析模块'}
      </button>
    </div>
  );
};
