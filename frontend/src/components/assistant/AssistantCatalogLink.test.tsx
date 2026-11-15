import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import { AssistantCatalogLink } from "./AssistantCatalogLink";
import { AssistantContext, type AssistantContextValue } from "./context";

function Harness() {
  const [open, setOpen] = useState(false);
  const value = { open, setOpen, availability: { available: true, code: null, reason: null, retry_at: null } } as unknown as AssistantContextValue;
  return <AssistantContext.Provider value={value}>
    <AssistantCatalogLink />
    <p>panel {open ? "open" : "closed"}</p>
  </AssistantContext.Provider>;
}

it("opens the Ask panel on the first click and closes it on the second, reflecting the state", () => {
  render(<MemoryRouter><Harness /></MemoryRouter>);
  const link = screen.getByRole("link", { name: "Try chat" });
  expect(link).toHaveAttribute("aria-expanded", "false");
  expect(link).toHaveAttribute("aria-controls", "assistant-panel");
  fireEvent.click(link);
  expect(screen.getByText("panel open")).toBeInTheDocument();
  expect(link).toHaveAttribute("aria-expanded", "true");
  expect(link).toHaveAccessibleName("Close chat");
  fireEvent.click(link);
  expect(screen.getByText("panel closed")).toBeInTheDocument();
  expect(link).toHaveAccessibleName("Try chat");
  expect(link).toHaveAttribute("aria-expanded", "false");
});
