import { Image, FileText, Mic } from "lucide-react";
import type { ViolationSource } from "../../types/compliance";

interface Props {
  source: ViolationSource;
  originalText: string;
  evidenceUrl: string | null;
  evidenceText: string | null;
  onImageClick?: () => void;
}

export function EvidenceBlock({
  source,
  originalText,
  evidenceUrl,
  evidenceText,
  onImageClick,
}: Props) {
  if (source === "transcript") {
    if (!originalText) return null;
    return (
      <blockquote className="text-xs text-base-content/60 border-l-2 border-base-300 pl-2 italic">
        <Mic className="inline h-3 w-3 mr-1 opacity-40" />
        {originalText}
      </blockquote>
    );
  }

  if (source === "ocr") {
    return (
      <div className="flex flex-col gap-1.5">
        {evidenceText && (
          <blockquote className="text-xs text-base-content/60 border-l-2 border-secondary/40 pl-2 italic">
            <FileText className="inline h-3 w-3 mr-1 opacity-40" />
            {evidenceText}
          </blockquote>
        )}
        {evidenceUrl && (
          <button
            className="relative w-full h-20 rounded overflow-hidden border border-base-300 hover:ring-2 hover:ring-primary transition-all"
            onClick={(e) => {
              e.stopPropagation();
              onImageClick?.();
            }}
          >
            <img
              src={evidenceUrl}
              alt="OCR 证据截图"
              className="w-full h-full object-cover"
              loading="lazy"
            />
            <span className="absolute bottom-0.5 right-0.5 badge badge-xs badge-neutral opacity-80">
              OCR
            </span>
          </button>
        )}
        {!evidenceText && originalText && (
          <blockquote className="text-xs text-base-content/60 border-l-2 border-base-300 pl-2 italic">
            {originalText}
          </blockquote>
        )}
      </div>
    );
  }

  // source === "vision"
  return (
    <div className="flex flex-col gap-1.5">
      {evidenceUrl && (
        <button
          className="relative w-full h-28 rounded overflow-hidden border border-base-300 hover:ring-2 hover:ring-primary transition-all"
          onClick={(e) => {
            e.stopPropagation();
            onImageClick?.();
          }}
        >
          <img
            src={evidenceUrl}
            alt="视觉违规截图"
            className="w-full h-full object-cover"
            loading="lazy"
          />
          <span className="absolute bottom-0.5 right-0.5 badge badge-xs badge-accent opacity-80">
            <Image className="h-2.5 w-2.5" />
          </span>
        </button>
      )}
      {originalText && (
        <blockquote className="text-xs text-base-content/60 border-l-2 border-accent/40 pl-2 italic">
          {originalText}
        </blockquote>
      )}
    </div>
  );
}
