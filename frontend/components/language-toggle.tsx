"use client";

import { Languages } from "lucide-react";

import { useI18n } from "../lib/i18n";

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();

  return (
    <div
      className={`ios-glass-field inline-flex items-center gap-1 rounded-xl p-1 ${
        compact ? "" : "min-w-[142px]"
      }`}
      aria-label={t("language.label")}
    >
      {!compact && <Languages className="ml-1 h-3.5 w-3.5 text-slate-400" />}
      {(["en", "zh"] as const).map((item) => {
        const selected = locale === item;
        return (
          <button
            key={item}
            type="button"
            onClick={() => setLocale(item)}
            aria-pressed={selected}
            className={`min-h-8 rounded-lg px-2.5 text-[11px] font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-black/10 ${
              selected
                ? "liquid-selected"
                : "liquid-hover text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            {item === "en" ? t("language.english") : t("language.chinese")}
          </button>
        );
      })}
    </div>
  );
}
