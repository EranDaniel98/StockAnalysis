import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow HMR + dev assets when the dashboard is opened from a phone /
  // tablet on the LAN. Next 16 blocks /_next/* from non-localhost
  // origins by default.
  allowedDevOrigins: ["192.168.68.51", "*.local"],
};

export default nextConfig;
