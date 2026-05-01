"use client";

import { ImagePlus, RotateCcw, Settings2 } from "lucide-react";
import { useRef } from "react";

import { useI18n } from "../lib/i18n";
import { InspectorPanel } from "./inspector-panel";
import { LanguageToggle } from "./language-toggle";

export type AgentSettings = {
  model: string;
  responseStyle: "balanced" | "concise" | "detailed";
  temperature: number;
  thinkingMode: boolean;
  thinkingEffort: "high" | "max";
  theme: "system" | "light" | "dark";
  density: "compact" | "comfortable";
  showRunGraph: boolean;
  expandedTools: boolean;
  commandScope: "restricted" | "unrestricted";
  workingDirectory: string;
  userAvatarUrl: string;
  tommyAvatarUrl: string;
};

type SettingsPanelProps = {
  settings: AgentSettings;
  onChange: (settings: AgentSettings) => void;
  chrome?: "panel" | "card";
};

export function SettingsPanel({
  settings,
  onChange,
  chrome = "panel",
}: SettingsPanelProps) {
  const { t } = useI18n();

  function update<K extends keyof AgentSettings>(key: K, value: AgentSettings[K]) {
    onChange({ ...settings, [key]: value });
  }

  const content = (
    <div className="space-y-4">
      <div>
        <p className="mb-2 text-[11px] font-medium text-slate-400">
          {t("settings.avatars")}
        </p>
        <div className="grid grid-cols-2 gap-2">
          <AvatarUpload
            label={t("settings.userAvatar")}
            value={settings.userAvatarUrl}
            fallback="U"
            onChange={(value) => update("userAvatarUrl", value)}
          />
          <AvatarUpload
            label={t("settings.tommyAvatar")}
            value={settings.tommyAvatarUrl}
            fallback="T"
            onChange={(value) => update("tommyAvatarUrl", value)}
          />
        </div>
      </div>

      <label className="block">
        <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
          {t("language.label")}
        </span>
        <LanguageToggle />
      </label>

      <label className="block">
        <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
          {t("settings.model")}
        </span>
        <select
          value={settings.model}
          onChange={(event) => update("model", event.target.value)}
          className="ios-glass-field soft-focus-ring w-full rounded-xl px-3 py-2 text-[13px] outline-none transition"
        >
          <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
          <option value="deepseek-chat">DeepSeek Chat</option>
          <option value="deepseek-reasoner">DeepSeek Reasoner</option>
        </select>
      </label>

      <label className="block">
        <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
          {t("settings.responseStyle")}
        </span>
        <select
          value={settings.responseStyle}
          onChange={(event) =>
            update("responseStyle", event.target.value as AgentSettings["responseStyle"])
          }
          className="ios-glass-field soft-focus-ring w-full rounded-xl px-3 py-2 text-[13px] outline-none transition"
        >
          <option value="balanced">{t("settings.style.balanced")}</option>
          <option value="concise">{t("settings.style.concise")}</option>
          <option value="detailed">{t("settings.style.detailed")}</option>
        </select>
      </label>

      <label className="block">
        <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
          {t("settings.appearance")}
        </span>
        <select
          value={settings.theme}
          onChange={(event) =>
            update("theme", event.target.value as AgentSettings["theme"])
          }
          className="ios-glass-field soft-focus-ring w-full rounded-xl px-3 py-2 text-[13px] outline-none transition"
        >
          <option value="system">{t("settings.theme.system")}</option>
          <option value="light">{t("settings.theme.light")}</option>
          <option value="dark">{t("settings.theme.dark")}</option>
        </select>
      </label>

      <fieldset>
        <legend className="mb-1.5 block text-[11px] font-medium text-slate-400">
          {t("settings.density")}
        </legend>
        <div className="ios-glass-field grid grid-cols-2 gap-1 rounded-xl p-1 text-[12px] font-medium">
          {(["compact", "comfortable"] as const).map((density) => {
            const selected = settings.density === density;
            return (
              <button
                key={density}
                type="button"
                onClick={() => update("density", density)}
                aria-pressed={selected}
                className={`min-h-10 rounded-lg px-2 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-black/10 ${
                  selected
                    ? "liquid-selected"
                    : "liquid-hover text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                {density === "compact"
                  ? t("settings.density.compact")
                  : t("settings.density.comfortable")}
              </button>
            );
          })}
        </div>
      </fieldset>

      <label className="block">
        <span className="mb-2 flex items-center justify-between text-[11px] font-medium text-slate-400">
          <span>{t("settings.temperature")}</span>
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
        label={t("settings.thinkingMode")}
        onChange={(checked) => update("thinkingMode", checked)}
      />

      <label className="block">
        <span className="mb-1.5 block text-[11px] font-medium text-slate-400">
          {t("settings.thinkingEffort")}
        </span>
        <select
          value={settings.thinkingEffort}
          onChange={(event) =>
            update("thinkingEffort", event.target.value as AgentSettings["thinkingEffort"])
          }
          disabled={!settings.thinkingMode}
          className="ios-glass-field soft-focus-ring w-full rounded-xl px-3 py-2 text-[13px] outline-none transition disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option value="high">{t("settings.effort.high")}</option>
          <option value="max">{t("settings.effort.max")}</option>
        </select>
      </label>

      <Toggle
        checked={settings.showRunGraph}
        label={t("settings.showRunGraph")}
        onChange={(checked) => update("showRunGraph", checked)}
      />
      <Toggle
        checked={settings.expandedTools}
        label={t("settings.expandedTools")}
        onChange={(checked) => update("expandedTools", checked)}
      />
    </div>
  );

  if (chrome === "card") {
    return (
      <div className="liquid-glass-strong max-h-[min(78dvh,46rem)] w-[21rem] overflow-y-auto rounded-3xl p-4 scrollbar-thin">
        <div className="mb-4 flex items-center gap-2 px-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          <Settings2 className="h-3.5 w-3.5" strokeWidth={2} />
          {t("settings.title")}
        </div>
        {content}
      </div>
    );
  }

  return (
    <InspectorPanel
      title={t("settings.title")}
      icon={<Settings2 className="h-3.5 w-3.5" strokeWidth={2} />}
      bodyClassName="p-4"
    >
      {content}
    </InspectorPanel>
  );
}

function AvatarUpload({
  label,
  value,
  fallback,
  onChange,
}: {
  label: string;
  value: string;
  fallback: string;
  onChange: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const { t } = useI18n();

  function handleFile(file: File | undefined) {
    if (!file || !file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") onChange(reader.result);
    };
    reader.readAsDataURL(file);
  }

  return (
    <div className="ios-glass-field rounded-2xl p-2.5">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => handleFile(event.target.files?.[0])}
      />
      <div className="flex items-center gap-2.5">
        {value ? (
          <img
            src={value}
            alt=""
            className="h-10 w-10 rounded-full object-cover shadow-sm"
          />
        ) : (
          <span className="liquid-selected flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold">
            {fallback}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-[12px] font-semibold text-slate-700 dark:text-slate-200">
            {label}
          </p>
          <div className="mt-1 flex gap-1.5">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="admin-secondary-action soft-focus-ring inline-flex min-h-7 items-center gap-1 px-2 text-[10px] font-semibold"
            >
              <ImagePlus className="h-3 w-3" />
              {t("settings.upload")}
            </button>
            {value && (
              <button
                type="button"
                onClick={() => onChange("")}
                className="admin-secondary-action soft-focus-ring inline-flex min-h-7 items-center gap-1 px-2 text-[10px] font-semibold"
              >
                <RotateCcw className="h-3 w-3" />
                {t("settings.reset")}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
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
