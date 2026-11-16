import React from "react";

import { Icon } from "@/components/Icon";

const FeedFilterToggle: React.FC<{
  checked: boolean;
  icon: React.ReactNode;
  label: string;
  onChange: (checked: boolean) => void;
}> = ({ checked, icon, label, onChange }) => (
  <button
    type="button"
    className={`paper-feed-filter ${checked ? "active" : ""}`}
    aria-pressed={checked}
    onClick={() => onChange(!checked)}
  >
    <span className="paper-feed-filter-content">
      <span className="paper-feed-filter-icon" aria-hidden="true">
        {icon}
      </span>
      {label}
    </span>
    {checked && (
      <span className="paper-feed-filter-check" aria-hidden="true">
        ✓
      </span>
    )}
  </button>
);

/** The catalog has no Hugging Face artifacts, so "Has code" is the only resource filter. */
export const PaperFeedFilters: React.FC<{
  hasCode: boolean;
  onHasCodeChange: (checked: boolean) => void;
  showDivider?: boolean;
  showHasCode?: boolean;
}> = ({
  hasCode,
  onHasCodeChange,
  showDivider = true,
  showHasCode = true,
}) => showHasCode ? (
  <div
    className="paper-feed-resource-controls"
    role="group"
    aria-label="Resource filters"
  >
    {showDivider && (
      <span className="paper-feed-resource-divider" aria-hidden="true" />
    )}
    <div className="paper-feed-filter-options">
      <FeedFilterToggle
        checked={hasCode}
        icon={<Icon name="github" size={14} />}
        label="Has code"
        onChange={onHasCodeChange}
      />
    </div>
  </div>
) : null;
