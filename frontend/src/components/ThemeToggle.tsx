import { useEffect, useState } from "react";
import { useTheme } from "next-themes";

/**
 * Sun and moon switch in the header. The site opens in dark mode unless the visitor
 * has chosen light here; index.html applies the stored choice before first paint.
 */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  // The resolved theme is only known in the browser; render the default until then.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const dark = !mounted || resolvedTheme !== "light";
  const next = dark ? "light" : "dark";
  const label = `Switch to ${next} mode`;

  return (
    <button type="button" className="icon-btn theme-toggle" aria-label={label} title={label} onClick={() => setTheme(next)}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {dark ? (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
          </>
        ) : (
          <path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z" />
        )}
      </svg>
    </button>
  );
}
