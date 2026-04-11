"use client";

import type { CSSProperties } from "react";

import { DownloadIcon, HeartIcon, UserAvatarIcon } from "./discover-icons";

interface MemoryPack {
  id: string;
  title: string;
  description: string;
  author: {
    id: string;
    name: string;
    avatar_seed: string;
  };
  created_at: string;
  likes_count: number;
  downloads_count: number;
}

interface DiscoverMemoryPacksProps {
  title: string;
  subtitle: string;
  comingSoonLabel: string;
  roadmapLabels: string[];
  packs: MemoryPack[];
  stageImageSrc?: string;
}

export function DiscoverMemoryPacks({
  title,
  subtitle,
  comingSoonLabel,
  roadmapLabels,
  packs,
  stageImageSrc,
}: DiscoverMemoryPacksProps) {
  const stageStyle: CSSProperties | undefined = stageImageSrc
    ? {
        backgroundImage: `linear-gradient(180deg, rgba(28, 20, 11, 0.18), rgba(28, 20, 11, 0.74)), linear-gradient(120deg, rgba(91, 63, 31, 0.14), rgba(16, 13, 9, 0.22)), url("${stageImageSrc}")`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }
    : undefined;

  return (
    <section className="dhub-memory-packs">
      <div className="dhub-memory-shell">
        <div
          className={`dhub-memory-stage${stageImageSrc ? " has-image" : ""}`}
          style={stageStyle}
        >
          <div className="dhub-memory-stage-copy">
            <span className="dhub-memory-stage-kicker">{title}</span>
            <strong className="dhub-memory-stage-title">
              {comingSoonLabel}
            </strong>
            <p className="dhub-memory-stage-subtitle">{subtitle}</p>
          </div>
          <div className="dhub-memory-packs-pills">
            {roadmapLabels.map((label) => (
              <span key={label} className="dhub-memory-packs-pill">
                {label}
              </span>
            ))}
          </div>
        </div>

        <div className="dhub-memory-feed">
          <div className="dhub-memory-packs-grid">
            {packs.map((pack) => (
              <article key={pack.id} className="dhub-memory-pack-card">
                <div className="dhub-memory-pack-author">
                  <span
                    className={`dhub-memory-pack-avatar is-${pack.author.avatar_seed}`}
                    aria-hidden="true"
                  >
                    <UserAvatarIcon size={18} />
                  </span>
                  <div className="dhub-memory-pack-author-copy">
                    <strong>{pack.author.name}</strong>
                    <span>{pack.created_at}</span>
                  </div>
                </div>
                <div className="dhub-memory-pack-copy">
                  <strong className="dhub-memory-pack-title">
                    {pack.title}
                  </strong>
                  <p className="dhub-memory-pack-desc">{pack.description}</p>
                </div>
                <div className="dhub-memory-pack-stats">
                  <span>
                    <HeartIcon size={12} /> {pack.likes_count}
                  </span>
                  <span>
                    <DownloadIcon size={12} /> {pack.downloads_count}
                  </span>
                </div>
              </article>
            ))}
          </div>
          <div className="dhub-memory-feed-note">
            <strong>{title}</strong>
            <span>{comingSoonLabel}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
