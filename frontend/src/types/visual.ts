/**
 * Visual analysis types for multi-modal audit pipeline.
 *
 * Author: afu
 */

export interface OCRRecord {
  timestamp_ms: number;
  text: string;
  confidence: number;
  frame_path: string;
  bbox: number[][];
}

export type VisualEventType = "face_detected" | "face_missing" | "scene_change";

export interface VisualEvent {
  event_type: VisualEventType;
  start_ms: number;
  end_ms: number;
  confidence: number;
  frame_path: string | null;
}
