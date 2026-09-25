const COLORS = [
  "bg-primary",
  "bg-secondary",
  "bg-accent",
  "bg-info",
  "bg-success",
  "bg-warning",
  "bg-error",
];

function hashCode(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

export function getSpeakerBgColor(speaker: string): string {
  return COLORS[hashCode(speaker) % COLORS.length];
}

export function getSpeakerInitial(name: string): string {
  return name.charAt(0).toUpperCase();
}
