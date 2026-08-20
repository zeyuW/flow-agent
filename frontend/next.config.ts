import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const adminApiBaseUrl = process.env.ADMIN_API_BASE_URL?.replace(/\/$/, "");
    if (!adminApiBaseUrl) return [];

    return [
      {
        source: "/api/:path*",
        destination: `${adminApiBaseUrl}/api/:path*`
      }
    ];
  }
};

export default nextConfig;
