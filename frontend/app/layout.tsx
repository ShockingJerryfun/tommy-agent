import type { Metadata } from "next";
import "@xyflow/react/dist/style.css";
import "./globals.css";

import { ToastProvider } from "../components/toast-provider";
import { I18nProvider } from "../lib/i18n";

export const metadata: Metadata = {
  title: "Tommy Agent",
  description: "LangGraph-first agent workbench",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="font-sans text-slate-950 antialiased dark:text-slate-100">
        <I18nProvider>
          <ToastProvider>{children}</ToastProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
