import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import SiteFooter from "@/components/SiteFooter";

afterEach(() => vi.unstubAllEnvs());

it("links the catalog's Discord in a new tab beside the other footer links", () => {
  vi.stubEnv("VITE_LOCAL_CATALOG", "true");
  render(<MemoryRouter><SiteFooter /></MemoryRouter>);
  const discord = screen.getByRole("link", { name: "Discord" });
  expect(discord).toHaveAttribute("href", "https://discord.gg/73FvhSy8vb");
  expect(discord).toHaveAttribute("target", "_blank");
  expect(discord).toHaveAttribute("rel", "noopener");
  expect(discord.querySelector("svg")).not.toBeNull();
});
