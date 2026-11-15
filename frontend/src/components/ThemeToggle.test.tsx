import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ThemeProvider } from "next-themes";
import { beforeEach, expect, it } from "vitest";
import { ThemeToggle } from "./ThemeToggle";

const renderToggle = () => render(
  <ThemeProvider attribute="class" defaultTheme="dark" enableSystem storageKey="pwc-theme"><ThemeToggle /></ThemeProvider>,
);

beforeEach(() => { document.documentElement.className = ""; localStorage.clear(); });

it("opens dark, switches to light and back, and remembers the choice", async () => {
  renderToggle();
  await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "Switch to light mode" }));
  await waitFor(() => expect(document.documentElement.classList.contains("light")).toBe(true));
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  expect(localStorage.getItem("pwc-theme")).toBe("light");
  fireEvent.click(screen.getByRole("button", { name: "Switch to dark mode" }));
  await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
  expect(localStorage.getItem("pwc-theme")).toBe("dark");
});

it("respects a stored light choice on load", async () => {
  localStorage.setItem("pwc-theme", "light");
  renderToggle();
  await waitFor(() => expect(screen.getByRole("button", { name: "Switch to dark mode" })).toBeTruthy());
});
