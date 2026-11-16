import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PaperFeedFilters } from "@/components/PaperFeedFilters";

describe("PaperFeedFilters", () => {
  it("renders the code toggle and no Hugging Face artifact toggle", async () => {
    const onHasCodeChange = vi.fn();
    const user = userEvent.setup();

    render(<PaperFeedFilters hasCode={false} onHasCodeChange={onHasCodeChange} />);

    const hasCode = screen.getByRole("button", { name: "Has code" });
    expect(hasCode).toHaveAttribute("aria-pressed", "false");
    expect(hasCode.querySelector(".paper-feed-filter-check")).toBeNull();
    expect(screen.queryByRole("button", { name: "Has artifacts" })).toBeNull();

    await user.click(hasCode);
    expect(onHasCodeChange).toHaveBeenCalledWith(true);
  });

  it("shows a check on an active code filter", () => {
    render(<PaperFeedFilters hasCode onHasCodeChange={vi.fn()} />);
    const hasCode = screen.getByRole("button", { name: "Has code" });
    expect(hasCode).toHaveAttribute("aria-pressed", "true");
    expect(hasCode.querySelector(".paper-feed-filter-check")).toHaveTextContent("✓");
  });

  it("renders nothing when the code toggle is omitted", () => {
    const { container } = render(
      <PaperFeedFilters hasCode={false} onHasCodeChange={vi.fn()} showHasCode={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
