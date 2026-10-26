# Setup — step by step on a MacBook

## 1. Python and dependencies

```bash
cd edugen
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

`sentence-transformers` pulls in PyTorch (~2 GB). If you want a fast first run:

```bash
pip install flask python-dotenv numpy openai pypdf
```

and set `EDUGEN_EMBEDDING_BACKEND=hashing` in `.env`. Everything works; the
retrieval is just lexical rather than semantic. Install the full set later and
rebuild the index.

## 2. Configuration

```bash
cp .env.example .env
```

Open `.env` and set two things:

**`GROQ_API_KEY`** — free, no card required, from <https://console.groq.com>.
Without it lessons fall back to the local concept notes and quizzes are
unavailable.

**`EDUGEN_SECRET_KEY`** — without it you are logged out on every restart:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 3. Build the knowledge base

```bash
python scripts/build_corpus.py   # 44 concept notes
python -m rag.ingest             # chunk, embed, index
```

Expected output ends with `Index ready` and `Concept coverage: 44/44 tags`.

Optional — add three open-licence Java textbooks:

```bash
python scripts/fetch_books.py
python -m rag.ingest --rebuild
```

Or just drop your own PDFs into `rag/corpus/books/` and rebuild.

## 4. Run

```bash
python run.py
```

Open <http://localhost:5000>, create an account, and the dashboard will show
the Coordinator routing your first session.

## 5. Verify

```bash
python scripts/smoke_test.py        # 52 checks, no browser needed
python scripts/test_adaptivity.py   # 11 adaptive-policy scenarios
```

Both should end with `0 failed`.

---

## Troubleshooting

**`Index was built with 'hashing:...' but the active embedder is 'sentence-transformers:...'`**
You changed backends. Vectors from different models are not comparable:
`python -m rag.ingest --rebuild`

**Lessons say "Served offline"**
No `GROQ_API_KEY`, or the key was rejected. Check the terminal on startup — it
prints whether the Concept Clarifier came up with an LLM.

**Quiz generation returns 503**
Same cause. Quizzes have no offline fallback by design.

**`No module named 'openai'`**
`pip install openai httpx`

**PDF produces zero chunks**
It is probably a scanned image with no text layer. `pip install pdfplumber`
helps with awkward PDFs; genuinely scanned books need OCR first.

**Port 5000 is busy (macOS AirPlay)**
`PORT=5050 python run.py`

**Logged out on every restart**
Set `EDUGEN_SECRET_KEY` in `.env`.

---

## Demonstrating it to an examiner

1. Start with `/about` — the architecture, one page.
2. Sign up live. The dashboard shows rule R1 firing for a new student.
3. Take a quiz, answer some wrong deliberately.
4. Go to `/analysis` — mastery, trend and the root-cause chain.
5. Go to `/pipeline` and press **Run the pipeline**. The rail lights up agent by
   agent, and the retrieval brief and retrieved passages appear.
6. Open `/library` and search — same index, same scores the agent saw.
7. Keep the agent activity console open the whole time. Hide it with
   `EDUGEN_SHOW_LOGS=0` if you prefer a clean interface.
