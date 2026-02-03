import {
  getSpeakerBgColor,
  getSpeakerInitial,
} from "../../utils/speakerColor";

interface Props {
  speaker: string;
  displayName: string;
}

export function SpeakerAvatar({ speaker, displayName }: Props) {
  const bgColor = getSpeakerBgColor(speaker);
  const initial = getSpeakerInitial(displayName);

  return (
    <div className="avatar placeholder">
      <div
        className={`${bgColor} text-neutral-content mask mask-squircle w-10`}
      >
        <span className="text-sm font-semibold">{initial}</span>
      </div>
    </div>
  );
}
