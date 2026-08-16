import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Needed by the `runner` stage in Dockerfile: emits .next/standalone with a
  // self-contained server.js and only the traced dependencies.
  output: "standalone",
  images: {
    // Team logos are small vendored PNGs served from public/. Runtime
    // optimisation would pull in sharp for no measurable gain and add a
    // failure mode to a visual element that appears on every card.
    unoptimized: true,
  },
};

export default nextConfig;
