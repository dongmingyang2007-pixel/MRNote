import { getTranslations } from "next-intl/server";

export default async function ScreenshotSection() {
  const t = await getTranslations("marketing");
  return (
    <section className="marketing-section" style={{ paddingTop: 48 }}>
      <div className="marketing-inner">
        <div
          className="marketing-inner--narrow"
          style={{ textAlign: "center", margin: "0 auto" }}
        >
          <span className="marketing-eyebrow">{t("screenshot.kicker")}</span>
          <h2 className="marketing-h2 font-display tracking-tight text-3xl md:text-4xl lg:text-5xl">
            {t("screenshot.title")}
          </h2>
          <p
            className="marketing-lead text-lg md:text-xl leading-relaxed"
            style={{ marginTop: 16, maxWidth: 620, marginInline: "auto" }}
          >
            {t("screenshot.sub")}
          </p>
        </div>

        <div className="marketing-screenshot">
          <div style={{ textAlign: "center" }}>
            <div
              style={{
                fontWeight: 600,
                color: "var(--text-primary)",
                marginBottom: 6,
              }}
            >
              {t("screenshot.placeholder.label")}
            </div>
            <div>{t("screenshot.placeholder.hint")}</div>
          </div>
        </div>
      </div>
    </section>
  );
}
