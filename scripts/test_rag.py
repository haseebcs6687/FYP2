"""
=============================================================================
EduGen RAG - Unit & Integration Tests (Phase 3)
=============================================================================
Tests the RAG subsystem with NO network dependencies:
  1. Chunk metadata completeness (collection, concept_tags, type, difficulty, level, source, page)
  2. Level heuristic classification (basic, standard, advanced)
  3. Lesson retrieval NEVER returns 'question' chunks
  4. Question retrieval respects exact difficulty and exclude_ids
  5. Near-duplicate rejection in question retrieval (cosine >= 0.90)
  6. Trace completeness and key schema validation
=============================================================================
"""

import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from rag.chunker import chunk_document, chunk_question_record
from rag.levels import infer_level
from rag.retriever import Retriever
from rag.vector_store import VectorStore


class TestRAGLevels(unittest.TestCase):
    def test_basic_definitions(self):
        self.assertEqual(infer_level("An object is a fundamental instance of a class."), "basic")
        self.assertEqual(infer_level("This section is an introduction to variables and methods."), "basic")
        self.assertEqual(infer_level("Polymorphism means many forms."), "basic")
        self.assertEqual(infer_level("The overview covers the fundamental concept of inheritance."), "basic")

    def test_advanced_signals(self):
        self.assertEqual(infer_level("However, note that this causes a subtle memory leak."), "advanced")
        self.assertEqual(infer_level("An edge case occurs when calling super() inside the block."), "advanced")
        self.assertEqual(infer_level("Beware of this common pitfall when overriding equals()."), "advanced")
        # Substantial code
        code = "public void test() {\n" + "  int x = 1;\n" * 10 + "}\n"
        self.assertEqual(infer_level("Here is an example:\n```java\n" + code + "```"), "advanced")

    def test_standard_content(self):
        text = "Java classes group state and behavior into reusable software components. " \
               "Methods define the operations that can be performed on the object's fields."
        self.assertEqual(infer_level(text), "standard")


class TestChunkMetadata(unittest.TestCase):
    def test_note_chunk_metadata(self):
        note_path = BASE_DIR / "rag" / "corpus" / "notes" / "class-definition.md"
        chunks = chunk_document(note_path, collection="note")
        self.assertGreater(len(chunks), 0)
        for c in chunks:
            self.assertEqual(c["collection"], "note")
            self.assertIn(c["type"], ("lesson", "example"))
            self.assertIsNone(c["difficulty"])
            self.assertIn(c["level"], ("basic", "standard", "advanced"))
            self.assertTrue(isinstance(c["concept_tags"], list))
            self.assertGreater(len(c["concept_tags"]), 0)
            self.assertIsNotNone(c["source"])
            self.assertIsNotNone(c["page"])

    def test_question_chunk_metadata(self):
        sample_q = {
            "question_id": "test__class-definition__b00_q01",
            "concept": "class-definition",
            "difficulty": "Easy",
            "qtype": "concept",
            "question": "What is a Java class?",
            "options": [
                {"text": "A blueprint for creating objects", "misconception_id": None},
                {"text": "A primitive variable", "misconception_id": None},
                {"text": "A runtime exception", "misconception_id": None},
                {"text": "A compiler flag", "misconception_id": None},
            ],
            "correct_index": 0,
            "explanation": "A class defines fields and methods.",
            "source": {"pdf": "thinkjava2.pdf", "page": 42},
        }
        chunk = chunk_question_record(sample_q)
        self.assertEqual(chunk["collection"], "question")
        self.assertEqual(chunk["type"], "mcq")
        self.assertEqual(chunk["difficulty"], "Easy")
        self.assertEqual(chunk["level"], "basic")
        self.assertEqual(chunk["source"], "thinkjava2.pdf")
        self.assertEqual(chunk["page"], 42)
        self.assertEqual(chunk["concept"], "class-definition")
        self.assertEqual(chunk["concept_tags"], ["class-definition"])
        self.assertIn("blueprint", chunk["text"])
        self.assertNotIn("primitive variable", chunk["text"])  # Wrong options not embedded


class TestTwoStageRetrieval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Build an in-memory test store with synthetic chunks to test retrieval mechanics deterministically
        cls.store = VectorStore()
        chunks = [
            # Book/Note chunks
            {
                "id": "book::1", "text": "Classes and objects overview in Java.", "collection": "book",
                "concept_tags": ["class-definition"], "type": "lesson", "difficulty": None, "level": "basic",
                "source": "book.pdf", "page": 10, "concept": "class-definition", "heading": "Intro",
            },
            {
                "id": "book::2", "text": "Advanced pitfall with static member access in subclasses.", "collection": "book",
                "concept_tags": ["class-definition", "static-members"], "type": "example", "difficulty": None, "level": "advanced",
                "source": "book.pdf", "page": 15, "concept": "class-definition", "heading": "Advanced",
            },
            # Question chunks
            {
                "id": "q::1", "text": "Question 1 Easy on class-definition", "collection": "question",
                "concept_tags": ["class-definition"], "type": "mcq", "difficulty": "Easy", "level": "basic",
                "source": "test.pdf", "page": 5, "concept": "class-definition", "question_id": "q1",
                "raw_record": {"question_id": "q1", "difficulty": "Easy", "concept": "class-definition"},
            },
            {
                "id": "q::2", "text": "Question 2 Hard on class-definition", "collection": "question",
                "concept_tags": ["class-definition"], "type": "mcq", "difficulty": "Hard", "level": "advanced",
                "source": "test.pdf", "page": 6, "concept": "class-definition", "question_id": "q2",
                "raw_record": {"question_id": "q2", "difficulty": "Hard", "concept": "class-definition"},
            },
            {
                "id": "q::3", "text": "Question 3 Easy near duplicate on class-definition", "collection": "question",
                "concept_tags": ["class-definition"], "type": "mcq", "difficulty": "Easy", "level": "basic",
                "source": "test.pdf", "page": 7, "concept": "class-definition", "question_id": "q3",
                "raw_record": {"question_id": "q3", "difficulty": "Easy", "concept": "class-definition"},
            },
        ]
        # Vectors: 4 dimensions for simplicity
        # v0 and v1 for books; v2 and v4 nearly identical (cosine > 0.95) for question near-duplicate test
        vectors = [
            [1.0, 0.0, 0.0, 0.0],
            [0.8, 0.6, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.99, 0.1, 0.0],  # cosine with v2 ~ 0.99
        ]
        cls.store.chunks = chunks
        cls.store.vectors = vectors
        cls.store._build_lexical_index()

        cls.retriever = Retriever(backend="hashing", lazy=True)
        cls.retriever.store = cls.store
        cls.retriever._loaded = True
        cls.retriever._embedder = cls.retriever._embedder or type("DummyEmbedder", (), {
            "signature": lambda self: "dummy:test:4",
            "embed_one": lambda self, t: [0.0, 1.0, 0.0, 0.0],
        })()

    def test_lesson_retrieval_never_returns_questions(self):
        brief = {"concept": "class-definition", "difficulty": "Easy", "mode": "lesson", "query": "class definition"}
        res = self.retriever.retrieve(brief)
        self.assertTrue(res["ready"])
        for p in res["passages"]:
            self.assertIn(p["collection"], ("book", "note"))
            self.assertNotEqual(p["collection"], "question")

    def test_question_retrieval_respects_difficulty_and_excludes(self):
        # Strict Easy
        easy_q = self.retriever.retrieve_reference_questions("class-definition", "Easy", k=5)
        for q in easy_q:
            self.assertEqual(q["difficulty"], "Easy")

        # Exclude q1
        filtered_q = self.retriever.retrieve_reference_questions("class-definition", "Easy", k=5, exclude_ids=["q1"])
        for q in filtered_q:
            self.assertNotEqual(q["question_id"], "q1")

    def test_question_near_duplicate_rejection(self):
        # In our test setup, q::1 (v2) and q::3 (v4) have cosine ~ 0.99 > 0.90
        # With near-duplicate rejection, q::3 must be dropped
        results = self.retriever.retrieve_reference_questions("class-definition", "Easy", k=5)
        q_ids = [q["question_id"] for q in results]
        # Only one of q1 and q3 should be present
        self.assertFalse("q1" in q_ids and "q3" in q_ids, "Near duplicate question was not dropped")

    def test_trace_keys_present(self):
        brief = {"concept": "class-definition", "difficulty": "Easy", "mode": "lesson", "query": "classes"}
        res = self.retriever.retrieve(brief)
        trace = res.get("trace")
        self.assertIsNotNone(trace)
        for key in ("query", "filters", "embedder", "candidates", "latency_ms", "top"):
            self.assertIn(key, trace)

        for top_item in trace["top"]:
            for expected_key in ("chunk_id", "source", "page", "concept", "collection", "level", "difficulty", "cosine", "lexical", "final"):
                self.assertIn(expected_key, top_item)


class TestDeterministicChunking(unittest.TestCase):
    def test_chunking_twice_yields_identical_chunks(self):
        note_path = BASE_DIR / "rag" / "corpus" / "notes" / "class-definition.md"
        c1 = chunk_document(note_path, collection="note")
        c2 = chunk_document(note_path, collection="note")
        self.assertEqual(len(c1), len(c2))
        self.assertEqual([c["id"] for c in c1], [c["id"] for c in c2])
        self.assertEqual([c["text"] for c in c1], [c["text"] for c in c2])
        self.assertEqual([c["level"] for c in c1], [c["level"] for c in c2])
        self.assertEqual([c["concept_tags"] for c in c1], [c["concept_tags"] for c in c2])


class TestQueryCache(unittest.TestCase):
    def test_repeated_query_does_not_call_embedder_twice(self):
        retriever = Retriever(lazy=True)
        retriever._loaded = True
        call_count = 0

        class MockEmbedder:
            def signature(self):
                return "mock:embedder:768"

            def embed_one(self, text):
                nonlocal call_count
                call_count += 1
                return [0.1, 0.2, 0.3]

        retriever._embedder = MockEmbedder()
        retriever.store = VectorStore()
        retriever.store.chunks = [{"id": "c1", "source": "note.md", "text": "hello", "collection": "note", "concept_tags": ["class-definition"]}]
        retriever.store.vectors = [[0.1, 0.2, 0.3]]

        brief = {"concept": "class-definition", "difficulty": "Easy", "mode": "lesson", "query": "what is a class"}

        # First call: cache miss
        r1 = retriever.retrieve(brief)
        self.assertEqual(call_count, 1)
        self.assertFalse(r1["trace"]["query_cache_hit"])

        # Second call: cache hit, embedder not called again
        r2 = retriever.retrieve(brief)
        self.assertEqual(call_count, 1)
        self.assertTrue(r2["trace"]["query_cache_hit"])


class TestRAGRetrievalLogging(unittest.TestCase):
    def test_lesson_request_logs_student_id_and_no_chunk_text(self):
        import json
        import tempfile
        import core.db as db
        from app import create_app

        temp_db = os.path.join(tempfile.mkdtemp(), "test_rag_log.db")
        orig_db = db.DB_PATH
        db.DB_PATH = temp_db
        os.environ["EDUGEN_DB_PATH"] = temp_db
        try:
            app = create_app()
            app.config["TESTING"] = True
            client = app.test_client()

            # Sign up student
            resp = client.post("/api/auth/signup", json={
                "name": "Audit Student", "email": "audit@example.com", "password": "password123"
            })
            self.assertEqual(resp.status_code, 201)
            student_id = resp.get_json()["student_id"]

            # Request a lesson
            l_resp = client.get("/api/lesson/class-definition/Easy")
            self.assertEqual(l_resp.status_code, 200)

            # Verify rag_retrievals in DB
            conn = db.get_db()
            cur = conn.cursor()
            cur.execute("SELECT student_id, concept, mode, embedder, results_json FROM rag_retrievals")
            rows = cur.fetchall()
            self.assertGreaterEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["student_id"], student_id)
            self.assertEqual(row["concept"], "class-definition")
            self.assertEqual(row["mode"], "lesson")

            results = json.loads(row["results_json"])
            self.assertTrue(isinstance(results, list))
            if results:
                for r in results:
                    self.assertIn("chunk_id", r)
                    # Must NOT contain chunk text
                    self.assertNotIn("text", r)
                    self.assertNotIn("content", r)
                    self.assertNotIn("body", r)
            conn.close()
        finally:
            db.DB_PATH = orig_db
            os.environ["EDUGEN_DB_PATH"] = orig_db


if __name__ == "__main__":
    unittest.main()
