import type { TemplateInfo } from "../../api/templates";

interface Props {
  templates: TemplateInfo[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  className?: string;
}

/** 纪要模板下拉框；只有一个可选模板时没有选择意义，不渲染。 */
export function TemplateSelect({ templates, value, onChange, disabled, className = "" }: Props) {
  if (templates.length <= 1) return null;
  return (
    <select
      className={`select select-bordered ${className}`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    >
      {templates.map((t) => (
        <option key={t.id} value={t.id} title={t.description}>
          {t.name}
        </option>
      ))}
    </select>
  );
}
