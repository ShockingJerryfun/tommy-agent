"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

type ToastOptions = {
  durationMs?: number;
  tone?: "default" | "success" | "error";
};

type ToastItem = {
  id: string;
  message: string;
  tone: ToastOptions["tone"];
};

type ToastContextValue = {
  toast: (message: string, opts?: ToastOptions) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

function createToastId() {
  return `toast-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const TOAST_TONE_STYLES = {
  default: "admin-card text-slate-800 dark:text-slate-100",
  success: "admin-card text-slate-800 dark:text-slate-100",
  error: "admin-error-card dark:bg-red-950/35 dark:text-red-100",
} as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, opts?: ToastOptions) => {
      const id = createToastId();
      const durationMs = opts?.durationMs ?? 2000;
      setToasts((current) =>
        [{ id, message, tone: opts?.tone ?? "default" }, ...current].slice(0, 3),
      );
      window.setTimeout(() => removeToast(id), durationMs);
    },
    [removeToast],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-relevant="additions"
        className="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+1rem)] z-[80] flex flex-col items-center gap-2 px-4 md:inset-x-auto md:bottom-auto md:right-5 md:top-5 md:items-end"
      >
        {toasts.map((item) => (
          <div
            key={item.id}
            className={`pointer-events-auto max-w-[min(22rem,calc(100vw-2rem))] rounded-2xl px-4 py-2.5 text-sm font-medium transition ${TOAST_TONE_STYLES[item.tone ?? "default"]}`}
            role="status"
          >
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const value = useContext(ToastContext);
  if (!value) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return value;
}
