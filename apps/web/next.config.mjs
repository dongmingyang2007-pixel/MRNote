import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin();
const DEFAULT_LOCAL_API_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"];

function normalizeOrigin(value) {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value);
    return `${url.protocol}//${url.host}`;
  } catch {
    return null;
  }
}

const internalApiOrigin =
  normalizeOrigin(process.env.INTERNAL_API_BASE_URL) ||
  normalizeOrigin(process.env.NEXT_PUBLIC_API_BASE_URL) ||
  DEFAULT_LOCAL_API_ORIGINS[0];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async redirects() {
    return [
      { source: "/zh", destination: "/", permanent: false },
      { source: "/zh/:path*", destination: "/:path*", permanent: false },
    ];
  },
  async rewrites() {
    return {
      beforeFiles: [
        { source: "/", destination: "/zh" },
        { source: "/api/:path*", destination: `${internalApiOrigin}/api/:path*` },
        // Keep console routes locale-aware even when dynamic ids contain dots
        // such as qwen3.5-plus or deepseek-v3.2.
        { source: "/app/:path*", destination: "/zh/workspace/:path*" },
        { source: "/zh/app/:path*", destination: "/zh/workspace/:path*" },
        { source: "/en/app/:path*", destination: "/en/workspace/:path*" },
        {
          source: "/:path((?!en(?:/|$)|zh(?:/|$)|api(?:/|$)|_next(?:/|$)|favicon\\.ico$|.*\\..*).*)",
          destination: "/zh/:path",
        },
      ],
    };
  },
  async headers() {
    // CSP is handled exclusively by middleware (proxy.ts) which supports
    // nonce-based strict-dynamic in production.  Defining a second static
    // CSP here would cause the browser to intersect both policies, breaking
    // the nonce mechanism.  The remaining security headers are kept as a
    // defence-in-depth fallback alongside the identical set in middleware.
    const consoleHeaders = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      {
        key: "Permissions-Policy",
        value: "camera=(self), microphone=(self), geolocation=(), browsing-topics=()",
      },
    ];

    return [
      { source: "/app", headers: consoleHeaders },
      { source: "/app/:path*", headers: consoleHeaders },
      { source: "/zh/app", headers: consoleHeaders },
      { source: "/zh/app/:path*", headers: consoleHeaders },
      { source: "/en/app", headers: consoleHeaders },
      { source: "/en/app/:path*", headers: consoleHeaders },
    ];
  },
};

export default withNextIntl(nextConfig);
