import { getTranslations } from "next-intl/server";

type PlanKey = "free" | "pro" | "power" | "team";
type Cell = "text" | "included" | "dash" | "unlimited";

interface Row {
  rowKey: string;
  cells: Record<PlanKey, { kind: Cell; value?: string }>;
}

const PLAN_ORDER: PlanKey[] = ["free", "pro", "power", "team"];

// Map each comparison row to the plan-specific value. Order matches
// the feature keys in the en/zh marketing JSON.
const ROWS: Row[] = [
  {
    rowKey: "notebooks",
    cells: {
      free: { kind: "text", value: "1" },
      pro: { kind: "unlimited" },
      power: { kind: "unlimited" },
      team: { kind: "unlimited" },
    },
  },
  {
    rowKey: "pages",
    cells: {
      free: { kind: "text", value: "50" },
      pro: { kind: "text", value: "500" },
      power: { kind: "unlimited" },
      team: { kind: "unlimited" },
    },
  },
  {
    rowKey: "studyAssets",
    cells: {
      free: { kind: "text", value: "5" },
      pro: { kind: "text", value: "50" },
      power: { kind: "unlimited" },
      team: { kind: "unlimited" },
    },
  },
  {
    rowKey: "aiActions",
    cells: {
      free: { kind: "text", value: "50" },
      pro: { kind: "text", value: "1,000" },
      power: { kind: "text", value: "10,000" },
      team: { kind: "text", value: "10,000" },
    },
  },
  {
    rowKey: "bookUpload",
    cells: {
      free: { kind: "dash" },
      pro: { kind: "included" },
      power: { kind: "included" },
      team: { kind: "included" },
    },
  },
  {
    rowKey: "dailyDigest",
    cells: {
      free: { kind: "dash" },
      pro: { kind: "included" },
      power: { kind: "included" },
      team: { kind: "included" },
    },
  },
  {
    rowKey: "voice",
    cells: {
      free: { kind: "dash" },
      pro: { kind: "included" },
      power: { kind: "included" },
      team: { kind: "included" },
    },
  },
  {
    rowKey: "insights",
    cells: {
      free: { kind: "dash" },
      pro: { kind: "dash" },
      power: { kind: "included" },
      team: { kind: "included" },
    },
  },
  {
    rowKey: "shared",
    cells: {
      free: { kind: "dash" },
      pro: { kind: "dash" },
      power: { kind: "dash" },
      team: { kind: "included" },
    },
  },
];

export default async function FeatureComparisonTable() {
  const t = await getTranslations("marketing");

  const cellLabel = (cell: { kind: Cell; value?: string }) => {
    switch (cell.kind) {
      case "unlimited":
        return t("pricingPage.compare.value.unlimited");
      case "included":
        return t("pricingPage.compare.value.included");
      case "dash":
        return t("pricingPage.compare.value.dash");
      case "text":
      default:
        return cell.value ?? "";
    }
  };

  return (
    <section className="marketing-section" style={{ paddingTop: 64 }}>
      <div className="marketing-inner marketing-inner--wide" style={{ margin: "0 auto" }}>
        <div
          className="marketing-inner--narrow"
          style={{ textAlign: "center", margin: "0 auto" }}
        >
          <h2 className="marketing-h2">{t("pricingPage.compare.title")}</h2>
        </div>

        <div className="marketing-compare-scroll">
          <table className="marketing-compare-table" data-testid="feature-comparison">
            <thead>
              <tr>
                <th>{t("pricingPage.compare.featureCol")}</th>
                {PLAN_ORDER.map((plan) => (
                  <th
                    key={plan}
                    className={plan === "pro" ? "marketing-compare-table__highlight" : undefined}
                    style={{ textAlign: "center" }}
                  >
                    {t(`plan.${plan}.name`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.rowKey}>
                  <td style={{ fontWeight: 500, color: "var(--text-primary)" }}>
                    {t(`pricingPage.compare.row.${row.rowKey}`)}
                  </td>
                  {PLAN_ORDER.map((plan) => (
                    <td
                      key={plan}
                      className={plan === "pro" ? "marketing-compare-table__highlight" : undefined}
                      style={{ textAlign: "center" }}
                    >
                      {cellLabel(row.cells[plan])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
