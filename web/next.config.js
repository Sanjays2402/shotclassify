/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typedRoutes: false,
  async rewrites() {
    const api = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
    return [
      { source: "/api/proxy/:path*", destination: `${api}/:path*` },
      // RFC 9116: serve security.txt from the same host as the web app
      // so external scanners and bug-bounty crawlers find it without
      // having to know the API origin. Forwarded transparently to the
      // API tier which owns the configured contact and rolling Expires.
      { source: "/.well-known/security.txt", destination: `${api}/.well-known/security.txt` },
      { source: "/security.txt", destination: `${api}/security.txt` },
    ];
  },
};
module.exports = nextConfig;
