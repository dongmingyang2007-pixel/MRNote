export function AmbientBackground() {
  return (
    <div
      aria-hidden
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        overflow: "hidden",
        background:
          "linear-gradient(180deg, rgba(247,254,252,0.98) 0%, rgba(240,253,250,0.84) 44%, rgba(255,250,244,0.92) 100%)",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(rgba(13,148,136,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(13,148,136,0.07) 1px, transparent 1px)",
          backgroundSize: "42px 42px",
          maskImage: "linear-gradient(180deg, rgba(0,0,0,0.72), transparent 72%)",
          WebkitMaskImage: "linear-gradient(180deg, rgba(0,0,0,0.72), transparent 72%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(115deg, rgba(13,148,136,0.12), transparent 34%, rgba(249,115,22,0.1) 76%, transparent)",
          opacity: 0.8,
        }}
      />
    </div>
  );
}
