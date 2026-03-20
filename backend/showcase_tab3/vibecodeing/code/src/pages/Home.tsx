import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Clock3,
  Code2,
  FolderOpen,
  Github,
  History,
  Layers,
  Search,
  Zap,
} from 'lucide-react';
import { motion } from 'motion/react';
import { SettingsLauncher } from '../components/SettingsLauncher';
import { parseGithubUrl } from '../services/github';
import { createLocalProjectSession } from '../services/localProjectSession';
import { listProjectAnalysisHistoryCards } from '../services/projectAnalysisStorage';
import { ProjectAnalysisHistoryCard } from '../types/analysis';

type AnalysisMode = 'github' | 'local';
type DirectoryInputAttributes = {
  webkitdirectory?: string;
  directory?: string;
};

function formatHistoryTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const Home = () => {
  const [mode, setMode] = useState<AnalysisMode>('github');
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [historyCards, setHistoryCards] = useState<ProjectAnalysisHistoryCard[]>([]);
  const localDirectoryInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    setHistoryCards(listProjectAnalysisHistoryCards());
  }, []);

  const handleAnalyzeGithub = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = parseGithubUrl(url);
    if (!parsed) {
      setError('请输入有效的 GitHub 仓库地址');
      return;
    }

    navigate(`/analysis?source=github&url=${encodeURIComponent(url.trim())}`);
  };

  const openLocalDirectoryPicker = () => {
    setError('');
    localDirectoryInputRef.current?.click();
  };

  const handleLocalDirectoryChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) {
      setError('请选择一个本地项目目录');
      return;
    }

    try {
      const { sessionId } = createLocalProjectSession(files);
      navigate(`/analysis?source=local&session=${encodeURIComponent(sessionId)}`);
    } catch (selectionError: any) {
      setError(selectionError.message || '读取本地目录失败');
    } finally {
      event.target.value = '';
    }
  };

  return (
    <div className="min-h-screen bg-white text-zinc-900 flex flex-col items-center justify-center px-6 py-20 relative overflow-hidden">
      <div className="absolute top-6 right-6 z-20">
        <SettingsLauncher />
      </div>

      <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none opacity-40">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-emerald-100 blur-[120px] rounded-full" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-blue-100 blur-[120px] rounded-full" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="w-full max-w-6xl text-center relative z-10"
      >
        <div className="flex items-center justify-center mb-8">
          <div className="w-16 h-16 bg-white border border-zinc-200 rounded-2xl flex items-center justify-center shadow-xl">
            {mode === 'github' ? (
              <Github size={32} className="text-emerald-600" />
            ) : (
              <FolderOpen size={32} className="text-emerald-600" />
            )}
          </div>
        </div>

        <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-6 bg-gradient-to-b from-zinc-900 to-zinc-500 bg-clip-text text-transparent">
          GitVisual
        </h1>

        <p className="text-lg md:text-xl text-zinc-500 mb-8 max-w-2xl mx-auto leading-relaxed">
          同时支持 GitHub 仓库和本地项目目录，以清晰文件树、AI 项目分析和调用链帮助你快速理解代码。
        </p>

        <div className="inline-flex p-1 mb-8 rounded-2xl border border-zinc-200 bg-white shadow-sm">
          <button
            type="button"
            onClick={() => {
              setMode('github');
              setError('');
            }}
            className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors ${
              mode === 'github'
                ? 'bg-zinc-900 text-white'
                : 'text-zinc-500 hover:text-zinc-800'
            }`}
          >
            <Github size={16} />
            GitHub 项目分析
          </button>
          <button
            type="button"
            onClick={() => {
              setMode('local');
              setError('');
            }}
            className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors ${
              mode === 'local'
                ? 'bg-zinc-900 text-white'
                : 'text-zinc-500 hover:text-zinc-800'
            }`}
          >
            <FolderOpen size={16} />
            本地项目分析
          </button>
        </div>

        {mode === 'github' ? (
          <form onSubmit={handleAnalyzeGithub} className="relative max-w-3xl mx-auto group">
            <div className="absolute -inset-1 bg-gradient-to-r from-emerald-500 to-blue-500 rounded-2xl blur opacity-10 group-focus-within:opacity-20 transition duration-500" />
            <div className="relative flex flex-col md:flex-row gap-3">
              <div className="relative flex-1">
                <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
                  <Search size={18} className="text-zinc-400" />
                </div>
                <input
                  type="text"
                  value={url}
                  onChange={(event) => {
                    setUrl(event.target.value);
                    setError('');
                  }}
                  placeholder="例如: https://github.com/owner/repo"
                  className="w-full bg-white border border-zinc-200 rounded-xl py-4 pl-12 pr-4 text-zinc-900 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 transition-all placeholder:text-zinc-400 shadow-sm"
                />
              </div>
              <button
                type="submit"
                className="bg-zinc-900 hover:bg-zinc-800 text-white font-bold py-4 px-8 rounded-xl transition-all flex items-center justify-center gap-2 group whitespace-nowrap shadow-lg shadow-zinc-200"
              >
                分析项目
                <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform" />
              </button>
            </div>
            {error && (
              <motion.p
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="absolute left-0 -bottom-8 text-sm text-red-500 font-medium"
              >
                {error}
              </motion.p>
            )}
          </form>
        ) : (
          <div className="max-w-3xl mx-auto">
            <div className="relative group">
              <div className="absolute -inset-1 bg-gradient-to-r from-emerald-500 to-blue-500 rounded-2xl blur opacity-10 group-focus-within:opacity-20 transition duration-500" />
              <div className="relative p-6 bg-white border border-zinc-200 rounded-2xl shadow-sm text-left">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-5">
                  <div className="space-y-2">
                    <div className="inline-flex items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
                      <FolderOpen size={14} />
                      目录选择后立即开始分析
                    </div>
                    <h2 className="text-2xl font-semibold text-zinc-900">选择一个本地项目目录</h2>
                    <p className="text-sm leading-6 text-zinc-500 max-w-xl">
                      浏览器会读取你选中的项目目录文件列表，并沿用现有 AI 分析流程完成文件树、入口点和调用链分析。
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={openLocalDirectoryPicker}
                    className="inline-flex items-center justify-center gap-2 rounded-xl bg-zinc-900 px-6 py-4 text-sm font-bold text-white shadow-lg shadow-zinc-200 transition-colors hover:bg-zinc-800 whitespace-nowrap"
                  >
                    选择本地路径
                    <ArrowRight size={18} />
                  </button>
                </div>
              </div>
            </div>

            {error && (
              <motion.p
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-4 text-sm text-red-500 font-medium"
              >
                {error}
              </motion.p>
            )}

            <input
              ref={localDirectoryInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleLocalDirectoryChange}
              {...({
                webkitdirectory: '',
                directory: '',
              } as DirectoryInputAttributes)}
            />
          </div>
        )}

        <div className="mt-16 max-w-5xl mx-auto text-left">
          <div className="flex items-center justify-between gap-4 mb-5">
            <div className="flex items-center gap-2 text-zinc-900">
              <History size={18} className="text-emerald-600" />
              <h2 className="text-lg font-semibold">历史分析记录</h2>
            </div>
            <span className="text-xs text-zinc-400">
              {historyCards.length ? `共 ${historyCards.length} 条` : '暂无历史记录'}
            </span>
          </div>

          {historyCards.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {historyCards.map((card) => (
                <button
                  key={card.id}
                  type="button"
                  onClick={() => navigate(`/analysis?history=${encodeURIComponent(card.id)}`)}
                  className="text-left p-5 bg-white border border-zinc-200 rounded-2xl shadow-sm hover:shadow-md hover:border-zinc-300 transition-all"
                >
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div>
                      <h3 className="text-base font-semibold text-zinc-900 break-all">{card.projectName}</h3>
                      <p className="text-xs text-zinc-500 mt-1 break-all">{card.githubUrl}</p>
                    </div>
                    <div className="shrink-0 flex items-center gap-1 text-[11px] text-zinc-400">
                      <Clock3 size={12} />
                      {formatHistoryTime(card.updatedAt)}
                    </div>
                  </div>

                  <p className="text-sm text-zinc-600 leading-6 min-h-[3rem]">{card.summary}</p>

                  <div className="flex flex-wrap gap-2 mt-4">
                    {card.languages.slice(0, 4).map((language) => (
                      <span
                        key={language}
                        className="px-2 py-1 rounded-md bg-emerald-50 text-emerald-700 text-[11px] font-medium border border-emerald-100"
                      >
                        {language}
                      </span>
                    ))}
                    {card.languages.length === 0 && (
                      <span className="px-2 py-1 rounded-md bg-zinc-50 text-zinc-500 text-[11px] font-medium border border-zinc-100">
                        未识别语言
                      </span>
                    )}
                  </div>

                  <div className="mt-4 pt-4 border-t border-zinc-100 flex items-center justify-between text-xs text-zinc-500">
                    <span>{card.codeFiles} 个代码文件</span>
                    <span>{card.totalFiles} 个文件条目</span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="p-6 bg-white border border-dashed border-zinc-200 rounded-2xl text-sm text-zinc-500">
              完成一次 GitHub 项目分析后，工程文件和历史记录会自动存到 LocalStorage，并展示在这里。
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-20">
          {[
            { icon: <Code2 size={20} />, title: '统一代码查看', desc: '支持 GitHub 仓库和本地目录两种代码来源' },
            { icon: <Layers size={20} />, title: '通用文件树', desc: '通过统一数据源接口展示项目结构与入口候选' },
            { icon: <Zap size={20} />, title: 'AI 深度分析', desc: '生成技术栈、摘要、模块划分与调用链' },
          ].map((feature, index) => (
            <div
              key={index}
              className="p-6 bg-white border border-zinc-100 rounded-2xl text-left hover:border-zinc-200 transition-colors shadow-sm"
            >
              <div className="w-10 h-10 bg-zinc-50 rounded-lg flex items-center justify-center mb-4 text-emerald-600 border border-zinc-100">
                {feature.icon}
              </div>
              <h3 className="font-bold mb-1 text-zinc-900">{feature.title}</h3>
              <p className="text-sm text-zinc-500">{feature.desc}</p>
            </div>
          ))}
        </div>
      </motion.div>

      <footer className="absolute bottom-8 text-zinc-400 text-xs tracking-widest uppercase">
        Built for codebase analysis
      </footer>
    </div>
  );
};
