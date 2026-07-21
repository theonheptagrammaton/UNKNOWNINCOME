import type { NextConfig } from "next";

// Where the Next.js server (NOT the browser) reaches the backend. In `next dev`
// and single-host deploys that's localhost:8000; in docker-compose the frontend
// container reaches the api service at http://api:8000 (set API_PROXY_TARGET).
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Standalone output → minimal production Docker image.
  output: "standalone",
  // Same-origin proxy: the browser calls /api/* on whatever host served the page
  // (port-forward URL, tunnel, reverse proxy); Next forwards it to the backend.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_PROXY_TARGET}/api/:path*` },
    ];
  },
};

export default nextConfig;
