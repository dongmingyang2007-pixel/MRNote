import { describe, expect, it } from "vitest";
import { ROLE_CONTENT, ROLE_KEYS, type RoleKey } from "@/lib/marketing/role-content";

describe("ROLE_CONTENT", () => {
  it("defines exactly 6 roles in a fixed order", () => {
    expect(ROLE_KEYS).toEqual([
      "researcher", "lawyer", "doctor", "teacher", "founder", "designer",
    ]);
    expect(Object.keys(ROLE_CONTENT)).toHaveLength(6);
  });

  it.each(["researcher", "lawyer", "doctor", "teacher", "founder", "designer"] as RoleKey[])(
    "role %s has all required fields populated in both locales",
    (key) => {
      const c = ROLE_CONTENT[key];
      expect(c.key).toBe(key);
      expect(c.label.zh.length).toBeGreaterThan(0);
      expect(c.label.en.length).toBeGreaterThan(0);
      expect(c.iconKey.length).toBeGreaterThan(0);
      expect(c.domainNoun.zh.length).toBeGreaterThan(0);
      expect(c.domainNoun.en.length).toBeGreaterThan(0);
      expect(c.stat.count).toBeGreaterThan(0);
      expect(c.stat.asOf).toMatch(/^\d{4}-\d{2}$/);
      expect(c.demo.title.zh.length).toBeGreaterThan(0);
      expect(c.demo.title.en.length).toBeGreaterThan(0);
      expect(c.demo.description.zh.length).toBeGreaterThan(0);
      expect(c.demo.description.en.length).toBeGreaterThan(0);
      expect(c.demo.animationKey.length).toBeGreaterThan(0);
      expect(c.templatePack.title.zh.length).toBeGreaterThan(0);
      expect(c.templatePack.title.en.length).toBeGreaterThan(0);
      expect(c.templatePack.items.length).toBeGreaterThanOrEqual(3);
      expect(c.templatePack.cta.zh.length).toBeGreaterThan(0);
      expect(c.offer.title.zh.length).toBeGreaterThan(0);
      expect(c.offer.title.en.length).toBeGreaterThan(0);
      expect(c.offer.cta.zh.length).toBeGreaterThan(0);
      expect(c.offer.href.startsWith("/")).toBe(true);
      expect(c.testimonial.quote.zh.length).toBeGreaterThan(0);
      expect(c.testimonial.quote.en.length).toBeGreaterThan(0);
      expect(c.testimonial.name.length).toBeGreaterThan(0);
      expect(c.testimonial.title.zh.length).toBeGreaterThan(0);
      expect(c.testimonial.avatarInitial.length).toBe(1);
      expect(c.institutions).toHaveLength(5);
    },
  );
});
