import type { NextConfig } from "next";

const adminApi = process.env.ADMIN_API_URL ?? "http://127.0.0.1:8001";

const config: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${adminApi}/api/:path*` }];
  },
};

export default config;
