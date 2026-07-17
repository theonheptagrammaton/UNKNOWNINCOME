import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output → minimal production Docker image.
  output: "standalone",
};

export default nextConfig;
