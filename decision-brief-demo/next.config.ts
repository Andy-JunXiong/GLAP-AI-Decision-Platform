import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: process.env.GLAP_INTERNAL_STATIC_EXPORT === "1" ? "export" : undefined,
  typescript: process.env.GLAP_INTERNAL_STATIC_EXPORT === "1"
    ? { tsconfigPath: "tsconfig.internal.json" }
    : undefined,
};

export default nextConfig;
