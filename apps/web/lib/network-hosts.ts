export const DEFAULT_LOCAL_API_PORT = "8000";

export const LOOPBACK_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "::1",
  "[::1]",
]);

export const LOCAL_BIND_HOSTS = new Set([
  "0.0.0.0",
  "::",
  "[::0]",
]);

export function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK_HOSTS.has(hostname);
}

export function isLocalBindHost(hostname: string): boolean {
  return LOCAL_BIND_HOSTS.has(hostname);
}
