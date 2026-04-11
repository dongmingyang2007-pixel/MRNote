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
        background: "var(--console-bg)",
      }}
    >
      <div
        style={{
          position: "absolute",
          width: 350,
          height: 350,
          borderRadius: "50%",
          background: "rgba(99,102,241,0.08)",
          filter: "blur(90px)",
          top: "-100px",
          right: "5%",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 280,
          height: 280,
          borderRadius: "50%",
          background: "rgba(139,92,246,0.06)",
          filter: "blur(70px)",
          bottom: "-60px",
          left: "15%",
        }}
      />
    </div>
  );
}
