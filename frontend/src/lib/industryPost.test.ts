import { describe, expect, it } from "vitest";

import {
  distinctOriginalTitle, groupRepositoriesByRole, knownStars, postTypeLabel, publisherHost, repositoryReferencesHref, subtopicLabel,
} from "./industryPost";

describe("industry post labels", () => {
  it("labels post types and subtopics", () => {
    expect(postTypeLabel("malware-or-threat-intel")).toBe("Malware or threat intel");
    expect(subtopicLabel("memory-safety")).toBe("Memory safety");
    expect(subtopicLabel("ci-cd-and-build-compromise")).toBe("CI/CD and build compromise");
    expect(subtopicLabel("other: agent memory design")).toBe("agent memory design");
  });

  it("reduces a post URL to its publisher host", () => {
    expect(publisherHost("https://www.wiz.io/blog/post")).toBe("wiz.io");
    expect(publisherHost(null)).toBeNull();
  });

  it("shows an original title only when it is more than a publisher suffix", () => {
    expect(distinctOriginalTitle("Symlinks Are Still Scary", "Symlinks Are Still Scary | Snyk")).toBeNull();
    expect(distinctOriginalTitle("Cloud Wireshark", "云端Wireshark")).toBe("云端Wireshark");
    expect(distinctOriginalTitle("Title", null)).toBeNull();
  });
});

describe("post repository links", () => {
  it("groups by role with the post's own code first and unknown roles last", () => {
    const groups = groupRepositoriesByRole([
      { id: "1", role: "dependency" }, { id: "2", role: "target" }, { id: "3", role: null },
      { id: "4", role: "original" }, { id: "5", role: "supporting" }, { id: "6", role: "original" },
    ]);
    expect(groups.map((group) => [group.role, group.repositories.map((r) => r.id)])).toEqual([
      ["original", ["4", "6"]], ["supporting", ["5"]], ["target", ["2"]], ["dependency", ["1"]], ["other", ["3"]],
    ]);
  });

  it("hides a star count that was never observed", () => {
    expect(knownStars({ num_stars: 0, num_stars_updated_at: null })).toBeNull();
    expect(knownStars({ num_stars: 1120, num_stars_updated_at: "2026-11-13T23:34:49Z" })).toBe(1120);
  });

  it("links to the repository's references page", () => {
    expect(repositoryReferencesHref("rapid7", "metasploit-framework")).toBe("/repos/rapid7/metasploit-framework");
  });
});
