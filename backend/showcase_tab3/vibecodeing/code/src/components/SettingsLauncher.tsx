import React, { useEffect, useMemo, useState } from 'react';
import { Save, Settings2, X } from 'lucide-react';
import {
  AI_PROVIDER_OPTIONS,
  getAIProviderDefinition,
  type AppSettings,
  type AppSettingsFieldResolution,
  type ResolvedAppSettings,
  getResolvedAppSettings,
  saveAppSettings,
  subscribeAppSettings,
} from '../services/appSettings';

interface SettingsLauncherProps {
  buttonClassName?: string;
  label?: string;
  title?: string;
}

const FIELD_LABELS: Record<keyof AppSettings, string> = {
  aiProvider: 'AI 接口厂商',
  aiBaseUrl: 'AI Base URL',
  aiApiKey: 'AI API Key',
  aiModel: 'AI 模型名称',
  githubToken: 'GitHub Token',
  maxDrillDepth: '最大下钻层数',
  keySubFunctionCount: '关键调用子函数数量',
};

function useSettingsSnapshot() {
  const [snapshot, setSnapshot] = useState(() => getResolvedAppSettings());

  useEffect(() => subscribeAppSettings(() => {
    setSnapshot(getResolvedAppSettings());
  }), []);

  return snapshot;
}

function buildFieldHint(field: AppSettingsFieldResolution) {
  if (field.source === 'env' && field.envName) {
    return field.hasStoredValue
      ? `检测到环境变量 ${field.envName}，当前分析优先使用环境变量；输入框中保留的是你保存的前端配置，环境变量移除后会自动接管。`
      : `检测到环境变量 ${field.envName}，当前分析优先使用环境变量；你仍可在这里填写前端配置，保存后会作为备用值。`;
  }

  if (field.source === 'storage') {
    return '当前使用前端持久化配置。';
  }

  return '当前使用默认值；保存后会写入本地持久化配置。';
}

function maskSecretValue(value: string) {
  if (!value) {
    return '';
  }

  if (value.length <= 8) {
    return '*'.repeat(Math.max(value.length, 4));
  }

  return `${value.slice(0, 4)}***${value.slice(-4)}`;
}

function formatEnvValue(field: AppSettingsFieldResolution) {
  if (field.source !== 'env' || !field.envValue) {
    return '';
  }

  if (field.key === 'aiApiKey' || field.key === 'githubToken') {
    return maskSecretValue(field.envValue);
  }

  return field.envValue;
}

function toFormValues(snapshot: ResolvedAppSettings): AppSettings {
  return {
    aiProvider: snapshot.fields.aiProvider.hasStoredValue
      ? snapshot.storedValues.aiProvider
      : snapshot.values.aiProvider,
    aiBaseUrl: snapshot.fields.aiBaseUrl.hasStoredValue
      ? snapshot.storedValues.aiBaseUrl
      : snapshot.values.aiBaseUrl,
    aiApiKey: snapshot.fields.aiApiKey.hasStoredValue
      ? snapshot.storedValues.aiApiKey
      : snapshot.values.aiApiKey,
    aiModel: snapshot.fields.aiModel.hasStoredValue
      ? snapshot.storedValues.aiModel
      : snapshot.values.aiModel,
    githubToken: snapshot.storedValues.githubToken || '',
    maxDrillDepth: snapshot.fields.maxDrillDepth.hasStoredValue
      ? snapshot.storedValues.maxDrillDepth
      : snapshot.values.maxDrillDepth,
    keySubFunctionCount: snapshot.fields.keySubFunctionCount.hasStoredValue
      ? snapshot.storedValues.keySubFunctionCount
      : snapshot.values.keySubFunctionCount,
  };
}

export const SettingsLauncher: React.FC<SettingsLauncherProps> = ({
  buttonClassName,
  label = '设置',
  title,
}) => {
  const snapshot = useSettingsSnapshot();
  const [isOpen, setIsOpen] = useState(false);
  const [formValues, setFormValues] = useState<AppSettings>(() => toFormValues(snapshot));
  const [saveMessage, setSaveMessage] = useState('');

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    setFormValues(toFormValues(snapshot));
  }, [isOpen, snapshot]);

  const fieldMeta = useMemo(() => snapshot.fields, [snapshot.fields]);
  const envBackedFields = useMemo(
    () => Object.values(fieldMeta).filter((field) => field.source === 'env'),
    [fieldMeta],
  );
  const selectedProvider = useMemo(
    () => getAIProviderDefinition(formValues.aiProvider),
    [formValues.aiProvider],
  );

  const updateField = <T extends keyof AppSettings>(key: T, value: AppSettings[T]) => {
    setFormValues((prev) => ({
      ...prev,
      [key]: value,
    }));
    setSaveMessage('');
  };

  const handleProviderChange = (nextProviderId: AppSettings['aiProvider']) => {
    const previousProvider = getAIProviderDefinition(formValues.aiProvider);
    const nextProvider = getAIProviderDefinition(nextProviderId);

    setFormValues((prev) => ({
      ...prev,
      aiProvider: nextProvider.id,
      aiBaseUrl:
        !prev.aiBaseUrl || prev.aiBaseUrl === previousProvider.defaultBaseUrl
          ? nextProvider.defaultBaseUrl
          : prev.aiBaseUrl,
      aiModel:
        !prev.aiModel || prev.aiModel === previousProvider.defaultModel
          ? nextProvider.defaultModel
          : prev.aiModel,
    }));
    setSaveMessage('');
  };

  const handleSave = (event: React.FormEvent) => {
    event.preventDefault();
    const nextSnapshot = saveAppSettings({
      ...formValues,
      maxDrillDepth: Number(formValues.maxDrillDepth),
      keySubFunctionCount: Number(formValues.keySubFunctionCount),
    });
    setFormValues(toFormValues(nextSnapshot));
    setSaveMessage(
      Object.values(nextSnapshot.fields).some((field) => field.source === 'env')
        ? '前端设置已保存；当前运行仍优先使用环境变量，环境变量移除后会自动切换到这里保存的值。'
        : '设置已保存，后续分析会使用最新配置。',
    );
  };

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setFormValues(toFormValues(getResolvedAppSettings()));
          setSaveMessage('');
          setIsOpen(true);
        }}
        className={buttonClassName || 'inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm font-semibold text-zinc-700 shadow-sm hover:bg-zinc-50'}
      >
        <Settings2 size={16} />
        {label && <span>{label}</span>}
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-[200] bg-zinc-950/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-3xl rounded-3xl border border-zinc-200 bg-white shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between gap-4 border-b border-zinc-200 px-6 py-4">
              <div>
                <h2 className="text-lg font-semibold text-zinc-900">{title || '分析设置'}</h2>
                <p className="text-sm text-zinc-500">
                  输入框填写的是前端持久化配置；如果检测到环境变量，下面会显示当前生效值，运行时仍以环境变量为准。
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="inline-flex items-center justify-center rounded-xl border border-zinc-200 p-2 text-zinc-500 hover:bg-zinc-50"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleSave} className="max-h-[80vh] overflow-auto px-6 py-5 space-y-5">
              {envBackedFields.length > 0 && (
                <section className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 space-y-2">
                  <p className="font-semibold">已检测到环境变量覆盖</p>
                  <div className="space-y-1 text-xs leading-5 text-amber-800">
                    {envBackedFields.map((field) => (
                      <p key={field.key}>
                        {FIELD_LABELS[field.key]}：{field.envName}
                        {formatEnvValue(field) ? ` = ${formatEnvValue(field)}` : ''}
                      </p>
                    ))}
                  </div>
                </section>
              )}

              <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="space-y-2">
                  <span className="text-sm font-semibold text-zinc-900">{FIELD_LABELS.aiProvider}</span>
                  <select
                    value={formValues.aiProvider}
                    onChange={(event) => handleProviderChange(event.target.value as AppSettings['aiProvider'])}
                    className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm text-zinc-800"
                  >
                    {AI_PROVIDER_OPTIONS.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.label}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs leading-5 text-zinc-500">
                    {buildFieldHint(fieldMeta.aiProvider)} {selectedProvider.description}
                  </p>
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-semibold text-zinc-900">{FIELD_LABELS.aiBaseUrl}</span>
                  <input
                    type="text"
                    value={formValues.aiBaseUrl}
                    onChange={(event) => updateField('aiBaseUrl', event.target.value)}
                    className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm text-zinc-800"
                  />
                  <p className="text-xs leading-5 text-zinc-500">
                    {buildFieldHint(fieldMeta.aiBaseUrl)} 当前厂商默认地址：{selectedProvider.defaultBaseUrl || '需手动填写'}。
                  </p>
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-semibold text-zinc-900">{FIELD_LABELS.aiModel}</span>
                  <input
                    type="text"
                    value={formValues.aiModel}
                    onChange={(event) => updateField('aiModel', event.target.value)}
                    className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm text-zinc-800"
                  />
                  <p className="text-xs leading-5 text-zinc-500">
                    {buildFieldHint(fieldMeta.aiModel)} 推荐模型示例：{selectedProvider.defaultModel || '请按厂商模型名填写'}。
                  </p>
                </label>

                <label className="space-y-2 md:col-span-2">
                  <span className="text-sm font-semibold text-zinc-900">{FIELD_LABELS.aiApiKey}</span>
                  <input
                    type="text"
                    value={formValues.aiApiKey}
                    onChange={(event) => updateField('aiApiKey', event.target.value)}
                    className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm font-mono text-zinc-800"
                  />
                  <p className="text-xs leading-5 text-zinc-500">{buildFieldHint(fieldMeta.aiApiKey)}</p>
                </label>

                <label className="space-y-2 md:col-span-2">
                  <span className="text-sm font-semibold text-zinc-900">{FIELD_LABELS.githubToken}</span>
                  <input
                    type="text"
                    value={formValues.githubToken}
                    onChange={(event) => updateField('githubToken', event.target.value)}
                    className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm font-mono text-zinc-800"
                  />
                  <p className="text-xs leading-5 text-zinc-500">
                    {buildFieldHint(fieldMeta.githubToken)} 用途：访问 GitHub API、减少匿名限流影响，并支持私有仓库分析。
                  </p>
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-semibold text-zinc-900">{FIELD_LABELS.maxDrillDepth}</span>
                  <input
                    type="number"
                    min={1}
                    value={formValues.maxDrillDepth}
                    onChange={(event) => updateField('maxDrillDepth', Number(event.target.value))}
                    className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm text-zinc-800"
                  />
                  <p className="text-xs leading-5 text-zinc-500">{buildFieldHint(fieldMeta.maxDrillDepth)} 默认值为 2。</p>
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-semibold text-zinc-900">{FIELD_LABELS.keySubFunctionCount}</span>
                  <input
                    type="number"
                    min={1}
                    value={formValues.keySubFunctionCount}
                    onChange={(event) => updateField('keySubFunctionCount', Number(event.target.value))}
                    className="w-full rounded-xl border border-zinc-200 px-3 py-2 text-sm text-zinc-800"
                  />
                  <p className="text-xs leading-5 text-zinc-500">{buildFieldHint(fieldMeta.keySubFunctionCount)} 默认值为 10。</p>
                </label>
              </section>

              {saveMessage && (
                <div className="rounded-2xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                  {saveMessage}
                </div>
              )}

              <div className="flex items-center justify-end gap-3 border-t border-zinc-200 pt-4">
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="rounded-xl border border-zinc-200 px-4 py-2 text-sm font-semibold text-zinc-600 hover:bg-zinc-50"
                >
                  关闭
                </button>
                <button
                  type="submit"
                  className="inline-flex items-center gap-2 rounded-xl bg-zinc-900 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-800"
                >
                  <Save size={15} />
                  保存设置
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
};
