"use client";

import { Settings2 } from "lucide-react";

import { InspectorPanel } from "./inspector-panel";

export type AgentSettings = {
  model: string;
  responseStyle: "balanced" | "concise" | "detailed";
  temperature: number;
  thinkingMode: boolean;
  thinkingEffort: "high" | "max";
  theme: "system" | "light" | "dark";
  showRunGraph: boolean;
  expandedTools: boolean;
  commandScope: "restricted" | "unrestricted";
  workingDirectory: string;
};

type SettingsPanelProps = {
  settings: AgentSettings;
  onChange: (settings: AgentSettings) => void;
};

export function SettingsPanel({ settings, onChange }: SettingsPanelProps) {
  function update<K extends keyof AgentSettings>(key: K, value: AgentSettings[K]) {
    onChange({ ...settings, [key]: value });
  }

  return (
    <InspectorPanel
      title="Settings"
      icon={<Settings2 className="h-3.5 w-3.5" strokeWidth={2} />}
      bodyClassName="p-4"
    >
        <div className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
              模型
            </span>
            <select
              value={settings.model}
              onChange={(event) => update("model", event.target.value)}
              className="w-full rounded-xl bg-slate-950/[0.04] px-3 py-2 text-[13px] outline-none ring-1 ring-transparent transition focus:ring-slate-400/30 dark:bg-slate-900/80"
            >
              <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
              <option value="deepseek-chat">DeepSeek Chat</option>
              <option value="deepseek-reasoner">DeepSeek Reasoner</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
              回复风格
            </span>
            <select
              value={settings.responseStyle}
              onChange={(event) =>
                update("responseStyle", event.target.value as AgentSettings["responseStyle"])
              }
              className="w-full rounded-xl bg-slate-950/[0.04] px-3 py-2 text-[13px] outline-none ring-1 ring-transparent transition focus:ring-slate-400/30 dark:bg-slate-900/80"
            >
              <option value="balanced">平衡</option>
              <option value="concise">简洁</option>
              <option value="detailed">详细</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
              外观
            </span>
            <select
              value={settings.theme}
              onChange={(event) =>
                update("theme", event.target.value as AgentSettings["theme"])
              }
              className="w-full rounded-xl bg-slate-950/[0.04] px-3 py-2 text-[13px] outline-none ring-1 ring-transparent transition focus:ring-slate-400/30 dark:bg-slate-900/80"
            >
              <option value="system">跟随系统</option>
              <option value="light">浅色</option>
              <option value="dark">深色</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-2 flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span>创造性</span>
              <span>{settings.temperature.toFixed(1)}</span>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={settings.temperature}
              onChange={(event) => update("temperature", Number(event.target.value))}
              className="w-full accent-slate-900 dark:accent-slate-400"
            />
          </label>

          <Toggle
            checked={settings.thinkingMode}
            label="思考模式"
            onChange={(checked) => update("thinkingMode", checked)}
          />

          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
              思考深度
            </span>
            <select
              value={settings.thinkingEffort}
              onChange={(event) =>
                update("thinkingEffort", event.target.value as AgentSettings["thinkingEffort"])
              }
              disabled={!settings.thinkingMode}
              className="w-full rounded-xl bg-slate-950/[0.04] px-3 py-2 text-[13px] outline-none ring-1 ring-transparent transition focus:ring-slate-400/30 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-900/80"
            >
              <option value="high">高</option>
              <option value="max">最深</option>
            </select>
          </label>

          <Toggle
            checked={settings.showRunGraph}
            label="显示运行图"
            onChange={(checked) => update("showRunGraph", checked)}
          />
          <Toggle
            checked={settings.expandedTools}
            label="默认展开工具结果"
            onChange={(checked) => update("expandedTools", checked)}
          />
        </div>
    </InspectorPanel>
  );
}

function Toggle({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-[13px] text-slate-600 dark:text-slate-300">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded accent-slate-900 dark:accent-slate-400"
      />
    </label>
  );
}
