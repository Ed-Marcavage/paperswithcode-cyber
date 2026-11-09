import { axes, type Axis } from "@/lib/api/discovery";

interface Props {
  axis: Axis;
  selected: string;
  options?: Record<string, string>;
  counts?: Record<string, number>;
  disabled: boolean;
  onChange: (value: string) => void;
}

export function CatalogFacetSelect({ axis, selected, options = {}, counts, disabled, onChange }: Props) {
  return <label>{axes[axis]}
    <select value={selected} disabled={disabled} onChange={e => onChange(e.target.value)}>
      <option value="">{counts ? `All (${counts[""] ?? 0})` : "All"}</option>
      {selected && !options[selected] && <option value={selected}>{selected}{counts && " (0)"}</option>}
      {Object.entries(options).map(([value, label]) => {
        const count = counts ? counts[value] ?? 0 : undefined;
        return <option key={value} value={value} disabled={count === 0 && value !== selected}>
          {count === undefined ? label : `${label} (${count})`}
        </option>;
      })}
    </select>
  </label>;
}
