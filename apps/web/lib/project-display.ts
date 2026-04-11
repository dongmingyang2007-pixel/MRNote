"use client";

type ProjectLike = {
  id: string;
  name: string;
};

function normalizeProjectName(name: string): string {
  const trimmed = name.trim();
  return trimmed || "Untitled Project";
}

export function buildProjectDisplayMap(
  projects: readonly ProjectLike[],
): Map<string, string> {
  const counts = new Map<string, number>();

  projects.forEach((project) => {
    const normalizedName = normalizeProjectName(project.name);
    counts.set(normalizedName, (counts.get(normalizedName) || 0) + 1);
  });

  return new Map(
    projects.map((project) => {
      const normalizedName = normalizeProjectName(project.name);
      const label =
        (counts.get(normalizedName) || 0) > 1
          ? `${normalizedName} (${project.id.slice(0, 8)})`
          : normalizedName;
      return [project.id, label];
    }),
  );
}
