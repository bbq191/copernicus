interface Props {
  containerRef: React.RefObject<HTMLDivElement | null>;
}

export function WaveformDisplay({ containerRef }: Props) {
  return (
    <div
      ref={containerRef}
      className="w-full rounded-lg bg-base-200 min-h-[80px]"
    />
  );
}
