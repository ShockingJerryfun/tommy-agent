import type { Metadata } from "next";
import "@xyflow/react/dist/style.css";
import "./globals.css";

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
        {children}
      </body>
    </html>
  );
}
