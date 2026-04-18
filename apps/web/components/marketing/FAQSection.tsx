"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import clsx from "clsx";

const FAQ_COUNT = 8;

export default function FAQSection() {
  const t = useTranslations("marketing");
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <section className="marketing-section" id="faq" style={{ paddingTop: 64 }}>
      <div className="marketing-inner" style={{ textAlign: "center" }}>
        <span className="marketing-eyebrow">{t("pricingPage.faq.kicker")}</span>
        <h2 className="marketing-h2">{t("pricingPage.faq.title")}</h2>

        <div
          className="marketing-faq-list"
          data-testid="faq-accordion"
          style={{ textAlign: "left" }}
        >
          {Array.from({ length: FAQ_COUNT }).map((_, i) => {
            const idx = i + 1;
            const open = openIndex === idx;
            return (
              <div
                key={idx}
                className={clsx("marketing-faq-item", {
                  "marketing-faq-item--open": open,
                })}
              >
                <button
                  type="button"
                  className="marketing-faq-item__button"
                  aria-expanded={open}
                  aria-controls={`faq-body-${idx}`}
                  onClick={() => setOpenIndex(open ? null : idx)}
                >
                  <span>{t(`pricingPage.faq.q${idx}`)}</span>
                  <Plus className="marketing-faq-item__icon" aria-hidden="true" />
                </button>
                {open && (
                  <div id={`faq-body-${idx}`} className="marketing-faq-item__body">
                    {t(`pricingPage.faq.a${idx}`)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
