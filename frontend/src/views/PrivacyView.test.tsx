import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PrivacyView from "@/views/PrivacyView";

describe("PrivacyView chat retention", () => {
  it("discloses verified contributor email collection", () => {
    render(<PrivacyView />);

    expect(screen.getByText(/If you request contributor access/i)).toHaveTextContent(
      /verified email address.*review and communicate/i,
    );
  });

  it("states retention, archive, deletion, sharing, and export behavior", () => {
    render(<PrivacyView />);

    const retention = screen.getByText(/Private chats are retained until you delete them/i);
    expect(retention).toHaveTextContent("500 active chats");
    expect(retention).toHaveTextContent("100 MB");
    expect(retention).toHaveTextContent(/Archiving.*does not delete/i);
    expect(retention).toHaveTextContent(/unlisted snapshot/i);
    expect(retention).toHaveTextContent(/No dedicated private-chat export format/i);
  });
});

describe("PrivacyView catalog analytics", () => {
  it("says sessions are recorded, what is left out, the referring domain, retention and the opt-outs", async () => {
    const { vi } = await import("vitest");
    vi.stubEnv("VITE_LOCAL_CATALOG", "true");
    try {
      render(<PrivacyView />);
      const recording = screen.getByText(/We also record sessions/);
      expect(recording).toHaveTextContent(/pointer movement, clicks and scrolling/);
      expect(recording).toHaveTextContent(/does not include text you type into the search box or any other field/);
      expect(recording).toHaveTextContent(/kept for 30 days/);
      expect(screen.getByText(/we record that site's domain/)).toHaveTextContent(/not the address of the page that linked here/);
      expect(screen.getByText(/Do Not Track or Global Privacy Control/)).toHaveTextContent(
        /no analytics, no session recording and no referring domain/);
      expect(screen.queryByText(/do not send .*session recordings/i)).not.toBeInTheDocument();
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
