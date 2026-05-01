import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "var(--font-inter)",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
      },
      borderRadius: {
        panel: "1.75rem",
        control: "1rem",
        bubble: "1.4rem",
      },
      boxShadow: {
        soft: "0 12px 40px -12px rgb(0 0 0 / 0.08), 0 1px 3px -1px rgb(0 0 0 / 0.04)",
        "soft-sm":
          "0 8px 24px -8px rgb(0 0 0 / 0.06), 0 1px 2px -1px rgb(0 0 0 / 0.03)",
        composer:
          "0 20px 48px -12px rgb(0 0 0 / 0.12), 0 6px 20px -8px rgb(0 0 0 / 0.08)",
      },
      animation: {
        "cursor-blink": "cursor-blink 0.9s ease-in-out infinite",
        "fade-slide-up":
          "fade-slide-up 0.28s cubic-bezier(0.22, 1, 0.36, 1) both",
        "scale-in": "scale-in 0.2s cubic-bezier(0.22, 1, 0.36, 1) both",
        "spin-slow": "spin 1.4s linear infinite",
      },
      keyframes: {
        "cursor-blink": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
        "fade-slide-up": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.95)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
