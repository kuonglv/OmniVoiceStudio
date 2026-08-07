import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: `next build` writes plain HTML/JS to `out/`, which the
  // FastAPI process serves itself. A pod is reachable through exactly one
  // RunPod proxy URL, so running a second Node server on a second port would
  // mean a second proxy hostname and CORS between them.
  output: "export",
  // Static hosting has no image optimizer behind it.
  images: { unoptimized: true },
  // `/voices` must resolve without a server rewrite → emit `voices/index.html`.
  trailingSlash: true,
};

export default nextConfig;
