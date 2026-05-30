import type { NextConfig } from "next";

const BACKEND_API_BASE = (
  process.env.AGENT_API_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Browser fetch streams can be buffered when SSE responses are gzipped.
  compress: false,
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  devIndicators: false,
  reactStrictMode: true,
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.githubusercontent.com" },
      { protocol: "https", hostname: "**.githubassets.com" },
      { protocol: "https", hostname: "raw.githubusercontent.com" },
      { protocol: "https", hostname: "images.unsplash.com" },
      { protocol: "https", hostname: "cdn.jsdelivr.net" },
      { protocol: "https", hostname: "**.openai.com" },
      { protocol: "https", hostname: "**.openaiusercontent.com" },
    ],
  },
  async rewrites() {
    return [
      {
        source: "/agent-api/:path*",
        destination: `${BACKEND_API_BASE}/:path*`,
      },
    ];
  },
};

export default nextConfig;
