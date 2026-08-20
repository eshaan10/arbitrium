import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `standalone` is for SELF-HOSTING ONLY — the `runner` stage in Dockerfile
  // copies .next/standalone and runs its self-contained server.js. Vercel does
  // its own serverless packaging and needs the default output mode, so the
  // setting is switched off there.
  //
  // Note what this is NOT: standalone does not suppress the output-file-tracing
  // manifests. `.next/next-server.js.nft.json` is emitted either way (verified:
  // 24 .nft.json files with standalone, 13 without, the root one present in
  // both). This guard removes the only non-default output-packaging setting
  // from Vercel's build; it is not a claim that tracing depends on it.
  //
  // VERCEL=1 is set by Vercel's build environment and by nothing else, so the
  // Docker build never takes this branch and the image is unaffected.
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
  images: {
    // Team logos are small vendored PNGs served from public/. Runtime
    // optimisation would pull in sharp for no measurable gain and add a
    // failure mode to a visual element that appears on every card.
    unoptimized: true,
  },
};

export default nextConfig;
