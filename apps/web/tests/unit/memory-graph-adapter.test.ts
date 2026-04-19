import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { adaptGraphData } from "@/components/console/graph/memory-graph/adapter";
import type { MemoryNode, MemoryEdge } from "@/hooks/useGraphData";

function makeNode(overrides: Partial<MemoryNode> = {}): MemoryNode {
  const now = "2026-04-19T10:00:00Z";
  return {
    id: "n1",
    workspace_id: "w",
    project_id: "p",
    content: "hello",
    category: "fact",
    type: "permanent",
    confidence: 0.8,
    observed_at: null,
    valid_from: null,
    valid_to: null,
    last_confirmed_at: null,
    source_conversation_id: null,
    parent_memory_id: null,
    position_x: null,
    position_y: null,
    node_type: "fact",
    subject_kind: null,
    subject_memory_id: null,
    node_status: null,
    canonical_key: null,
    lineage_key: null,
    metadata_json: {},
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

function makeEdge(overrides: Partial<MemoryEdge> = {}): MemoryEdge {
  return {
    id: "e1",
    source_memory_id: "n1",
    target_memory_id: "n2",
    edge_type: "related",
    strength: 0.5,
    confidence: null,
    observed_at: null,
    valid_from: null,
    valid_to: null,
    metadata_json: {},
    created_at: "2026-04-19T10:00:00Z",
    ...overrides,
  };
}

describe("adaptGraphData — node role derivation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-19T12:00:00Z").getTime());
  });
  afterEach(() => { vi.useRealTimers(); });

  it("maps fact nodes", () => {
    const { nodes } = adaptGraphData({ nodes: [makeNode({ node_type: "fact" })], edges: [] });
    expect(nodes[0].role).toBe("fact");
  });

  it("maps concept nodes", () => {
    const { nodes } = adaptGraphData({
      nodes: [makeNode({ node_type: "concept", metadata_json: { node_kind: "concept" } })],
      edges: [],
    });
    expect(nodes[0].role).toBe("concept");
  });

  it("maps subject nodes", () => {
    const { nodes } = adaptGraphData({
      nodes: [makeNode({ node_type: "subject", metadata_json: { node_kind: "subject" } })],
      edges: [],
    });
    expect(nodes[0].role).toBe("subject");
  });

  it("maps summary nodes", () => {
    const { nodes } = adaptGraphData({
      nodes: [makeNode({ metadata_json: { node_kind: "summary", memory_kind: "summary" } })],
      edges: [],
    });
    expect(nodes[0].role).toBe("summary");
  });

  it("maps structure nodes (category-path / structural_only)", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({
          metadata_json: { node_kind: "category-path", concept_source: "category_path", structural_only: true },
        }),
      ],
      edges: [],
    });
    expect(nodes[0].role).toBe("structure");
  });
});

describe("adaptGraphData — field mapping", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-19T12:00:00Z").getTime());
  });
  afterEach(() => { vi.useRealTimers(); });

  it("truncates long content to LABEL_MAX_CHARS + ellipsis", () => {
    const long = "x".repeat(60);
    const { nodes } = adaptGraphData({ nodes: [makeNode({ content: long })], edges: [] });
    expect(nodes[0].label.length).toBeLessThanOrEqual(29); // 28 chars + "…"
    expect(nodes[0].label.endsWith("…")).toBe(true);
  });

  it("keeps short content intact", () => {
    const { nodes } = adaptGraphData({ nodes: [makeNode({ content: "hi" })], edges: [] });
    expect(nodes[0].label).toBe("hi");
  });

  it("falls back conf to 0.5 when confidence is null", () => {
    const { nodes } = adaptGraphData({ nodes: [makeNode({ confidence: null })], edges: [] });
    expect(nodes[0].conf).toBe(0.5);
  });

  it("reads reuse from metadata_json.retrieval_count (default 0)", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({ metadata_json: { retrieval_count: 7 } }),
        makeNode({ id: "n2", metadata_json: {} }),
      ],
      edges: [],
    });
    expect(nodes[0].reuse).toBe(7);
    expect(nodes[1].reuse).toBe(0);
  });

  it("humanizes metadata_json.last_used_at", () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60_000).toISOString();
    const { nodes } = adaptGraphData({
      nodes: [makeNode({ metadata_json: { last_used_at: twoHoursAgo } })],
      edges: [],
    });
    expect(nodes[0].lastUsed).toBe("2h");
  });

  it("coerces pinned to boolean", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({ id: "a", metadata_json: { pinned: true } }),
        makeNode({ id: "b", metadata_json: { pinned: false } }),
        makeNode({ id: "c", metadata_json: {} }),
      ],
      edges: [],
    });
    expect(nodes[0].pinned).toBe(true);
    expect(nodes[1].pinned).toBe(false);
    expect(nodes[2].pinned).toBe(false);
  });

  it("reads source from metadata_json.category_label, falling back to node.category", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({ id: "a", category: "root.cat", metadata_json: { category_label: "Prettier" } }),
        makeNode({ id: "b", category: "root.cat", metadata_json: {} }),
      ],
      edges: [],
    });
    expect(nodes[0].source).toBe("Prettier");
    expect(nodes[1].source).toBe("root.cat");
  });

  it("drops nodes that are not display-type memory (center/file roles excluded)", () => {
    const { nodes } = adaptGraphData({
      nodes: [
        makeNode({ id: "a", node_type: "fact" }),
        makeNode({ id: "b", node_type: "root", metadata_json: { node_kind: "assistant-root" } }),
        makeNode({ id: "c", category: "file", metadata_json: { node_kind: "file" } }),
      ],
      edges: [],
    });
    expect(nodes.map((n) => n.id).sort()).toEqual(["a"]);
  });
});

describe("adaptGraphData — edges", () => {
  it("maps backend edge fields straight through", () => {
    const { edges } = adaptGraphData({
      nodes: [makeNode({ id: "a" }), makeNode({ id: "b" })],
      edges: [
        makeEdge({ id: "e1", source_memory_id: "a", target_memory_id: "b", edge_type: "evidence", strength: 0.8 }),
      ],
    });
    expect(edges).toEqual([{ a: "a", b: "b", rel: "evidence", w: 0.8 }]);
  });

  it("drops edges whose endpoints were filtered out", () => {
    const { edges } = adaptGraphData({
      nodes: [
        makeNode({ id: "a" }),
        makeNode({ id: "center", node_type: "root", metadata_json: { node_kind: "assistant-root" } }),
      ],
      edges: [makeEdge({ source_memory_id: "a", target_memory_id: "center" })],
    });
    expect(edges).toEqual([]);
  });
});
