import { describe, expect, it } from "vitest";

import type { Paper, Repository } from "./api/papers.types";
import { displayTaskName, toSotaRanks, transformPaperForCard } from "./transform";

describe("displayTaskName", () => {
  it("keeps the catalog namespace in routes only", () => {
    expect(displayTaskName("Cyberintel Penetration Testing", "cyberintel-penetration-testing")).toBe("Penetration Testing");
    expect(displayTaskName(undefined, "cyberintel-binary-analysis")).toBe("Binary Analysis");
  });
  it("keeps acronyms written in capitals in the task name", () => {
    expect(displayTaskName("PII Detection", "pii-detection")).toBe("PII Detection");
    expect(displayTaskName("LLM Evaluation", "llm-evaluation")).toBe("LLM Evaluation");
  });

  it("title-cases ordinary words", () => {
    expect(displayTaskName("named entity recognition", "named-entity-recognition")).toBe(
      "Named Entity Recognition",
    );
    expect(displayTaskName("egocentric vision", "egocentric-vision")).toBe(
      "Egocentric Vision",
    );
  });

  it("still applies known acronyms and display overrides", () => {
    expect(displayTaskName("3d tracking", "3d-tracking")).toBe("3D Tracking");
    expect(displayTaskName("ocr", "ocr")).toBe("OCR");
    expect(displayTaskName("Text to SQL", "text-to-sql")).toBe("Text-to-SQL");
  });

  it("falls back to the slug when the name is missing", () => {
    expect(displayTaskName(undefined, "robotic-manipulation")).toBe("Robotic Manipulation");
  });
});

describe("toSotaRanks", () => {
  it("links each placement to its highlighted evaluation row", () => {
    expect(
      toSotaRanks([
        { evaluation_id: "42", dataset_name: "ImageNet", dataset_slug: "imagenet", best_rank: 1, task_slug: "image-classification" },
        { evaluation_id: "7", dataset_name: "COCO", dataset_slug: "coco", best_rank: 2, task_slug: null },
        { evaluation_id: "9", dataset_name: "Unlisted", dataset_slug: null, best_rank: 3 },
        { evaluation_id: "8", dataset_name: "Low", dataset_slug: "low", best_rank: 4 },
      ]),
    ).toEqual([
      { name: "ImageNet", href: "/benchmark/imagenet?task=image-classification&eval=42", rank: 1 },
      { name: "COCO", href: "/benchmark/coco?eval=7", rank: 2 },
      { name: "Unlisted", href: null, rank: 3 },
    ]);
  });
});

describe("transformPaperForCard code badge", () => {
  const repository = (overrides: Partial<Repository>): Repository => ({
    id: "1", paper_id: "9", url: "https://github.com/acme/tool", owner: "acme", name: "tool",
    num_stars: 0, is_official: false, source: "post-review", num_stars_updated_at: null, ...overrides,
  });
  const card = (overrides: Partial<Paper>) => transformPaperForCard({
    id: "9", arxiv_id: null, title: "A post", authors: [], published: "2026-11-01", repositories: [], ...overrides,
  } as unknown as Paper);

  it("credits a post only with code it released", () => {
    const post = card({
      catalog_kind: "post",
      repositories: [repository({ url: "https://github.com/torvalds/linux", role: "target", num_stars: 0 })],
    });
    expect(post.githubUrl).toBeNull();
    expect(post.github).toBeNull();

    const released = card({
      catalog_kind: "post",
      repositories: [
        repository({ url: "https://github.com/big/dependency", role: "dependency", num_stars: 90000, num_stars_updated_at: "2026-11-13T00:00:00Z" }),
        repository({ url: "https://github.com/acme/tool", role: "original", is_official: true, num_stars: 1120, num_stars_updated_at: "2026-11-13T00:00:00Z" }),
      ],
    });
    expect(released.githubUrl).toBe("https://github.com/acme/tool");
    expect(released.github).toBe(1120);
  });

  it("links a post's released code without a star count that was never observed", () => {
    const post = card({ catalog_kind: "post", repositories: [repository({ role: "original", is_official: true })] });
    expect(post.githubUrl).toBe("https://github.com/acme/tool");
    expect(post.github).toBeNull();
  });

  it("keeps the most-starred repository for papers", () => {
    const paper = card({
      catalog_kind: "paper",
      repositories: [repository({ url: "https://github.com/a/b", num_stars: 5 }), repository({ url: "https://github.com/c/d", num_stars: 50 })],
    });
    expect(paper.githubUrl).toBe("https://github.com/c/d");
    expect(paper.github).toBe(50);
  });
});
