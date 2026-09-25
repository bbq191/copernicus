from copernicus.utils.text import chunk_text, format_timestamp, split_sentences


class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        text = "短文本"
        result = chunk_text(text, chunk_size=800)
        assert result == [text]

    def test_empty_text(self):
        assert chunk_text("", chunk_size=800) == [""]

    def test_splits_at_sentence_boundary(self):
        # Build a text that exceeds chunk_size with a sentence boundary
        sentence1 = "这是第一句话。"
        sentence2 = "这是第二句话。"
        # Repeat to exceed chunk size
        text = sentence1 * 50 + sentence2 * 50
        chunks = chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) > 1
        # All chunks should be non-empty
        assert all(len(c) > 0 for c in chunks)

    def test_respects_overlap(self):
        text = "a" * 300
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        # 相邻块重叠 overlap 个字符，保证跨块的句子不被切断
        assert chunks[0][-20:] == chunks[1][:20]


class TestSplitSentences:
    def test_splits_after_sentence_terminators(self):
        assert split_sentences("你好。今天开会！好吗？") == ["你好。", "今天开会！", "好吗？"]

    def test_empty_and_unpunctuated_text(self):
        assert split_sentences("") == []
        assert split_sentences("没有标点") == ["没有标点"]


class TestFormatTimestamp:
    def test_minutes_and_seconds_are_zero_padded(self):
        assert format_timestamp(0) == "00:00"
        assert format_timestamp(65_000) == "01:05"
        assert format_timestamp(3_725_000) == "62:05"
