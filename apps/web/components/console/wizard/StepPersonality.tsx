"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

interface PersonalityTemplate {
  id: string;
  label: string;
  hint: string;
  prompt: string;
}

const TEMPLATES: PersonalityTemplate[] = [
  {
    id: "warm",
    label: "温暖陪伴",
    hint: "像老朋友一样，耐心、温柔、善于倾听",
    prompt: "你是一位温暖的陪伴者，像老朋友一样与用户交流。你耐心、温柔、善于倾听，总是用关怀和理解回应用户的感受，让每次对话都充满温度。",
  },
  {
    id: "efficient",
    label: "高效助理",
    hint: "简洁、直接、注重效率，帮你搞定事情",
    prompt: "你是一位高效的助理，回答简洁直接，注重效率。你善于快速理解用户需求，给出可执行的方案，不啰嗦，帮用户高效搞定事情。",
  },
  {
    id: "tutor",
    label: "学习导师",
    hint: "善于解释、引导思考、帮助你理解新知识",
    prompt: "你是一位耐心的学习导师，善于用通俗易懂的方式解释复杂概念。你通过提问引导用户思考，帮助他们建立知识体系，循序渐进地掌握新知识。",
  },
  {
    id: "creative",
    label: "创意伙伴",
    hint: "发散思维、头脑风暴、激发灵感",
    prompt: "你是一位充满创意的伙伴，擅长发散思维和头脑风暴。你不设限地探索各种可能性，用新颖的角度激发用户的灵感，让创意源源不断。",
  },
  {
    id: "calm",
    label: "冷静顾问",
    hint: "理性分析、客观建议、帮你理清思路",
    prompt: "你是一位冷静的顾问，善于理性分析问题。你客观看待各种情况，提供有条理的建议，帮助用户理清思路，做出更好的决策。",
  },
  {
    id: "humor",
    label: "幽默玩伴",
    hint: "风趣、轻松、让每次对话都充满乐趣",
    prompt: "你是一位幽默风趣的玩伴，善于用轻松愉快的方式交流。你妙语连珠，让每次对话都充满乐趣，在欢笑中帮用户解决问题。",
  },
];

const TAG_OPTIONS = [
  "\u4E13\u4E1A",
  "\u53CB\u5584",
  "\u5E7D\u9ED8",
  "\u4E25\u8C28",
  "\u521B\u610F",
  "\u8010\u5FC3",
];

interface PersonalityData {
  description: string;
  tags: string[];
}

interface StepPersonalityProps {
  personality: PersonalityData;
  onPersonalityChange: (data: PersonalityData) => void;
}

export function StepPersonality({ personality, onPersonalityChange }: StepPersonalityProps) {
  const t = useTranslations("console-assistants");

  const selectTemplate = useCallback(
    (tmpl: PersonalityTemplate) => {
      onPersonalityChange({
        ...personality,
        description: tmpl.prompt,
      });
    },
    [personality, onPersonalityChange],
  );

  const toggleTag = useCallback(
    (tag: string) => {
      const tags = personality.tags.includes(tag)
        ? personality.tags.filter((t) => t !== tag)
        : [...personality.tags, tag];
      onPersonalityChange({ ...personality, tags });
    },
    [personality, onPersonalityChange],
  );

  return (
    <div className="wizard-step-personality">
      <h2 className="wizard-step-title">{t("wizard.personality.title")}</h2>
      <p className="wizard-step-desc">{t("wizard.personality.subtitle")}</p>

      <div className="wizard-personality-grid">
        {TEMPLATES.map((tmpl) => (
          <button
            key={tmpl.id}
            type="button"
            className={`wizard-personality-card ${personality.description === tmpl.prompt && tmpl.prompt ? "wizard-personality-card--selected" : ""}`}
            onClick={() => selectTemplate(tmpl)}
          >
            <span className="wizard-personality-label">{tmpl.label}</span>
            <span className="wizard-personality-hint">{tmpl.hint}</span>
          </button>
        ))}
      </div>

      <div className="wizard-personality-prompt">
        <label className="wizard-label" htmlFor="personality-textarea">
          {t("wizard.promptLabel")}
        </label>
        <textarea
          id="personality-textarea"
          className="wizard-textarea"
          rows={4}
          value={personality.description}
          onChange={(e) =>
            onPersonalityChange({ ...personality, description: e.target.value })
          }
          placeholder={t("wizard.promptPlaceholder")}
        />
      </div>

      <div className="wizard-personality-tags">
        <span className="wizard-label">{t("wizard.tagsLabel")}</span>
        <div className="wizard-tag-chips">
          {TAG_OPTIONS.map((tag) => (
            <button
              key={tag}
              type="button"
              className={`wizard-tag-chip ${personality.tags.includes(tag) ? "wizard-tag-chip--active" : ""}`}
              onClick={() => toggleTag(tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      </div>

    </div>
  );
}
