import type { NextConfig } from "next";

// The browser only talks to this Next.js server; /api/* is proxied to the local FastAPI backend, so the
// API keys never leave the backend process and no CORS setup is needed.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
