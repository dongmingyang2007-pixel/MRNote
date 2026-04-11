export function getProviderStyle(provider: string): { bg: string; label: string } {
  const p = provider.toLowerCase();
  if (p.includes("qwen") || p.includes("alibaba")) {
    return { bg: "linear-gradient(135deg, #c8734a, #e8925a)", label: "Q" };
  }
  if (p.includes("deepseek")) {
    return { bg: "linear-gradient(135deg, #3a6a9a, #4a8ac8)", label: "DS" };
  }
  return {
    bg: "linear-gradient(135deg, #6b7280, #9ca3af)",
    label: provider.charAt(0).toUpperCase(),
  };
}
