/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async rewrites() {
    // Proxy API traffic to the Hookrelay backend. The backend origin is
    // configurable so the same build works in dev and in production
    // (defaults to the local dev server; set HOOKRELAY_API_ORIGIN or
    // NEXT_PUBLIC_API_BASE_URL in the environment to override).
    const backend =
      process.env.HOOKRELAY_API_ORIGIN ??
      process.env.NEXT_PUBLIC_API_BASE_URL ??
      'http://127.0.0.1:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
      {
        source: '/webhook/:path*',
        destination: `${backend}/webhook/:path*`,
      },
      {
        source: '/bin/:path*',
        destination: `${backend}/bin/:path*`,
      },
    ];
  },
}

export default nextConfig
