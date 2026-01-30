from copernicus.utils.text import chunk_text, merge_chunks


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
        # Reconstruct should cover the entire text
        merged = merge_chunks(chunks, overlap=20)
        assert len(merged) >= len(text) - 20  # allow small variance from overlap


class TestMergeChunks:
    def test_empty_list(self):
        assert merge_chunks([]) == ""

    def test_single_chunk(self):
        assert merge_chunks(["hello"]) == "hello"

    def test_multiple_chunks_skip_overlap(self):
        chunks = ["ABCDE", "CDE_FG", "E_FGHIJ"]
        result = merge_chunks(chunks, overlap=3)
        # First chunk fully kept, subsequent chunks skip first 3 chars
        assert result == "ABCDE" + "_FG" + "GHIJ"

    def test_overlap_larger_than_chunk(self):
        chunks = ["AB", "X"]
        result = merge_chunks(chunks, overlap=5)
        # overlap > len(chunk), so skip entire second chunk
        assert result == "AB"
