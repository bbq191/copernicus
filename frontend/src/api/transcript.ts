import client from "./client";
import type { TranscriptResponse } from "../types/transcript";

export async function transcribeDirect(
  file: File,
  hotwords?: string,
): Promise<TranscriptResponse> {
  const form = new FormData();
  form.append("file", file);
  if (hotwords) form.append("hotwords", hotwords);
  const { data } = await client.post<TranscriptResponse>(
    "/transcribe/transcript",
    form,
  );
  return data;
}
