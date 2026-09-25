"""转写结果的人工校对：文本修订与说话人改名（纯函数，不涉及存储）。"""

from copernicus.schemas.transcription import TranscriptResponse


def apply_text_edits(
    transcript: TranscriptResponse, edits: dict[int, str]
) -> tuple[TranscriptResponse, int]:
    """按句段下标替换 text_corrected（原始 text 保持不变），返回 (新转写, 实际变更条数)。

    越界下标会被忽略；内容未变化的句段不计入变更。
    """
    entries = list(transcript.transcript)
    changed = 0
    for index, new_text in edits.items():
        if not 0 <= index < len(entries):
            continue
        if entries[index].text_corrected == new_text:
            continue
        entries[index] = entries[index].model_copy(update={"text_corrected": new_text})
        changed += 1
    return transcript.model_copy(update={"transcript": entries}), changed


def apply_speaker_renames(
    transcript: TranscriptResponse, renames: dict[str, str]
) -> tuple[TranscriptResponse, int]:
    """按 {原名: 新名} 重写说话人标签，返回 (新转写, 受影响句段数)。

    多个原名映射到同一新名即实现说话人合并。
    """
    entries = []
    affected = 0
    for entry in transcript.transcript:
        new_name = renames.get(entry.speaker)
        if new_name is not None and new_name != entry.speaker:
            entry = entry.model_copy(update={"speaker": new_name})
            affected += 1
        entries.append(entry)
    return transcript.model_copy(update={"transcript": entries}), affected
