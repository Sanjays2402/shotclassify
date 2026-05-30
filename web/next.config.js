/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typedRoutes: false,
  async rewrites() {
    const api = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
    return [{ source: "/api/proxy/:path*", destination: `${api}/:path*` }];
  },
};
module.exports = nextConfig;
