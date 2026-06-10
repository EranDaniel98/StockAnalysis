import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow HMR + dev assets when the dashboard is opened from a phone /
  // tablet on the LAN. Next 16 blocks /_next/* from non-localhost
  // origins by default — a blocked origin gets server HTML but NO
  // hydration (every client handler dead, zero console errors), so
  // 127.0.0.1 must be listed too: only `localhost` is implicit.
  allowedDevOrigins: ["127.0.0.1", "10.0.0.9", "192.168.68.51", "*.local"],
};

export default nextConfig;
