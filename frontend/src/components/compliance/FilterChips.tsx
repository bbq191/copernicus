import type { ComponentType } from "react";

export interface ChipOption<T extends string> {
  value: T;
  label: string;
  /** 选中时的配色；缺省用主色 */
  activeClass?: string;
}

interface Props<T extends string> {
  icon: ComponentType<{ className?: string }>;
  options: readonly ChipOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** 各选项的数量，大于 0 时显示在标签后 */
  counts?: Partial<Record<T, number>>;
}

/** 一行筛选标签：违规列表的严重度/来源/状态筛选共用。 */
export function FilterChips<T extends string>({ icon: Icon, options, value, onChange, counts }: Props<T>) {
  return (
    <>
      <Icon className="h-4 w-4 opacity-50" />
      <div className="flex gap-1">
        {options.map((opt) => {
          const count = counts?.[opt.value] ?? 0;
          const active = value === opt.value ? (opt.activeClass ?? "badge-primary") : "badge-ghost";
          return (
            <button
              key={opt.value}
              className={`badge badge-sm cursor-pointer ${active}`}
              onClick={() => onChange(opt.value)}
            >
              {opt.label}
              {count > 0 && ` (${count})`}
            </button>
          );
        })}
      </div>
    </>
  );
}
