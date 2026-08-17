from luminary_memory.recall.dedup import dedup_jaccard, jaccard_similarity
from luminary_memory.types import Memory


def test_jaccard_identical_texts_scores_one():
    assert jaccard_similarity("hello world", "hello world") == 1.0


def test_jaccard_disjoint_scores_zero():
    assert jaccard_similarity("hello world", "completely different") == 0.0


def test_dedup_removes_near_duplicate():
    a = Memory(id=1, content="postgres vector index is fast and reliable")
    b = Memory(id=2, content="postgres vector index is fast and reliable today")
    result = dedup_jaccard([(a, 0.9), (b, 0.8)], threshold=0.85)
    assert len(result) == 1
    assert result[0][0].id == 1


def test_dedup_keeps_distinct_memories():
    a = Memory(id=1, content="postgres vector index is fast and reliable")
    b = Memory(id=2, content="cooking pasta with tomato sauce tonight")
    result = dedup_jaccard([(a, 0.9), (b, 0.8)], threshold=0.85)
    assert len(result) == 2


def test_dedup_keeps_higher_score():
    a = Memory(id=1, content="hello world token unique")
    b = Memory(id=2, content="hello world token unique content")
    # whichever is first has higher score and should survive
    result = dedup_jaccard([(a, 0.95), (b, 0.9)], threshold=0.85)
    assert result[0][0].id == 1
    result2 = dedup_jaccard([(b, 0.95), (a, 0.9)], threshold=0.85)
    assert result2[0][0].id == 2


def test_dedup_empty_input_returns_empty():
    assert dedup_jaccard([], threshold=0.85) == []


def test_dedup_threshold_boundary():
    a = Memory(id=1, content="alpha beta gamma")
    b = Memory(id=2, content="alpha beta gamma")
    assert len(dedup_jaccard([(a, 1.0), (b, 0.9)], threshold=1.0)) == 1
    assert len(dedup_jaccard([(a, 1.0), (b, 0.9)], threshold=1.01)) == 2
