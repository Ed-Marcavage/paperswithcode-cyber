import { describe, expect, it } from "vitest";

import { distinctOriginalTitle, postTypeLabel, publisherHost, subtopicLabel } from "./industryPost";

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
