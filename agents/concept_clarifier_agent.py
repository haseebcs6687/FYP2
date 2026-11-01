"""
=============================================================================
EduGen - Concept Clarifier Agent  (FYP-2)
=============================================================================
Agent type : Retrieval-Augmented Generation agent
Role       : The ONLY agent allowed to call an external LLM. Turns a
             retrieval brief into a lesson or a quiz.

Pipeline inside this agent
--------------------------
    retrieval brief
        |
        v
    1. RAG retrieve    ask the vector store for the passages that actually
                       cover this concept                    (rag/retriever)
        |
        v
    2. Prompt assembly grounded system prompt + numbered source passages +
                       the student's specific misconceptions
        |
        v
    3. LLM call        Groq (OpenAI-compatible). One retry on a different
                       model, then a structural retry.
        |
        v
    4. Validate        strict JSON schema check; tags forced back into the
                       44-tag canonical vocabulary
        |
        v
    5. Fallback ladder  LLM fails -> local concept note (lessons)
                                  -> quiz unavailable message (quizzes)

In FYP-2, quizzes have no static fallback: questions are generated dynamically
by the Concept Clarifier. If the LLM is unreachable or fails, quizzes report
unavailable with the exact error, while lessons fall back to local notes.
=============================================================================
"""

import collections
from concurrent.futures import ThreadPoolExecutor
import inspect
import json
import os
import re
import time
from pathlib import Path

from core.concepts import CANONICAL_CONCEPT_TAGS, CONCEPTS, concept_title, normalise_tags
from core.db_repo import record_llm_call
from core.java_check import JavaChecker
from core.misconceptions import MISCONCEPTIONS, misconceptions_for
from core.quiz_engine import (
    build_blueprint,
    check_question_novelty,
    group_slots,
    normalize_question,
)

NOTES_DIR = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "notes"


class ConceptClarifierAgent(object):

    GROQ_BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = os.environ.get("EDUGEN_LLM_MODEL", "openai/gpt-oss-120b")
    FALLBACK_MODEL = os.environ.get("EDUGEN_LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")
    DEFAULT_VERIFIER_MODEL = os.environ.get("EDUGEN_VERIFIER_MODEL", "qwen/qwen3.8-27b")
    FALLBACK_VERIFIER_MODEL = os.environ.get("EDUGEN_VERIFIER_FALLBACK_MODEL", "openai/gpt-oss-20b")

    def __init__(self, api_key=None, model=None, retriever=None, log=None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model or os.environ.get("EDUGEN_LLM_MODEL") or self.DEFAULT_MODEL
        self.fallback_model = os.environ.get("EDUGEN_LLM_FALLBACK_MODEL") or self.FALLBACK_MODEL
        self.verifier_model = os.environ.get("EDUGEN_VERIFIER_MODEL") or self.DEFAULT_VERIFIER_MODEL
        self.verifier_fallback_model = os.environ.get("EDUGEN_VERIFIER_FALLBACK_MODEL") or self.FALLBACK_VERIFIER_MODEL
        self.retriever = retriever
        self.log = log
        self.client = None
        self.last_error = None
        self.last_model_used = None
        self._init_client()

    def _emit(self, message, level="info", payload=None):
        if self.log:
            self.log("Concept Clarifier", message, level, payload)
        else:
            try:
                from core.agent_log import add_log
                add_log("Concept Clarifier", message, level, payload)
            except Exception:
                pass

    def _init_client(self):
        if not self.api_key or self.api_key.strip() in ("", "your-key-here"):
            self.last_error = "No GROQ_API_KEY set. Configure it in .env and restart."
            print("[Concept Clarifier] No GROQ_API_KEY set - running in offline mode "
                  "(local notes only; quizzes require LLM).")
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(base_url=self.GROQ_BASE_URL, api_key=self.api_key)
            print("[Concept Clarifier] LLM client ready (model '{}').".format(self.model))
        except Exception as exc:                                   # noqa: BLE001
            self.last_error = "Client init failed: {}".format(exc)
            print("[Concept Clarifier] Client init failed: {}".format(exc))
            self.client = None

    @property
    def llm_available(self):
        return self.client is not None

    def _invoke_llm(self, system_prompt, user_prompt, **kwargs):
        """Invoke self._call_llm filtering kwargs if _call_llm was mocked/overridden with fewer parameters."""
        try:
            sig = inspect.signature(self._call_llm)
            accepted = sig.parameters
            has_var = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in accepted.values())
            if not has_var:
                kwargs = {k: v for k, v in kwargs.items() if k in accepted}
        except Exception:
            pass
        return self._call_llm(system_prompt, user_prompt, **kwargs)

    # =========================================================
    # LESSON
    # =========================================================
    def generate_lesson(self, brief):
        """brief: retrieval brief from the Adaptive Content Agent (or build_brief)."""
        brief = _coerce_brief(brief, mode="lesson")
        concept = brief["concept"]
        difficulty = brief["difficulty"]

        retrieval = self._retrieve(brief)
        grounded = bool(retrieval.get("passages"))

        if self.llm_available:
            lesson = self._llm_lesson(brief, retrieval)
            if lesson:
                lesson.update({
                    "concept": concept,
                    "difficulty": difficulty,
                    "grounded": grounded,
                    "sources": retrieval.get("citations", []),
                    "passages": retrieval.get("passages", []),
                    "retrieval_trace": retrieval.get("trace"),
                    "generated_by": "llm+rag" if grounded else "llm",
                    "model": self.model,
                })
                self._emit("Lesson generated for '{}' ({}){}".format(
                    concept_title(concept), difficulty,
                    " grounded in {} sources".format(len(retrieval.get("citations", []))) if grounded else ""),
                    "success")
                return lesson
            self._emit("LLM lesson generation failed - falling back to the local note", "warning")

        return self._note_lesson(concept, difficulty, retrieval)

    def _llm_lesson(self, brief, retrieval):
        context = retrieval.get("context", "")
        notes = brief.get("focus_notes", [])

        system = (
            "You are an expert Java and object-oriented programming tutor writing material "
            "for a university student.\n"
            "Rules:\n"
            "1. If SOURCE MATERIAL is provided, ground every claim in it and stay consistent "
            "with its terminology. Do not contradict it.\n"
            "2. Java code must compile as written and be idiomatic.\n"
            "3. Reply with a single valid JSON object and nothing else."
        )

        parts = [
            "Write a lesson on the concept '{}' ({}) at {} difficulty.".format(
                brief["concept"], concept_title(brief["concept"]), brief["difficulty"]),
            "",
            "Difficulty guidance:",
            _difficulty_guidance(brief["difficulty"]),
        ]
        if notes:
            parts += ["", "This student specifically needs:"] + ["- " + n for n in notes]
        if context:
            parts += ["", "SOURCE MATERIAL (cite passage numbers where you use them):", context]
        parts += [
            "",
            "Return JSON with exactly these keys:",
            '  "title"         : a short lesson title',
            '  "explanation"   : 3-4 paragraphs of plain prose, separated by \\n\\n',
            '  "code_example"  : one complete, compilable Java snippet with comments',
            '  "code_walkthrough": 2-4 short strings explaining what the snippet demonstrates',
            '  "key_points"    : 4-5 short strings a student could revise from',
            '  "common_mistake": one sentence naming the mistake students usually make',
            '  "concept_tags"  : 1-3 tags from this list: ' + ", ".join(CANONICAL_CONCEPT_TAGS),
        ]

        data = self._invoke_llm(
            system,
            "\n".join(parts),
            max_tokens=3000,
            purpose="lesson",
            reasoning_effort="medium",
        )
        if not data:
            return None

        title = _string(data.get("title")) or "{} ({})".format(
            concept_title(brief["concept"]), brief["difficulty"])
        explanation = _string(data.get("explanation"))
        if not explanation or len(explanation) < 80:
            return None

        return {
            "title": title,
            "explanation": explanation,
            "code_example": _string(data.get("code_example")),
            "code_walkthrough": _string_list(data.get("code_walkthrough"))[:4],
            "key_points": _string_list(data.get("key_points"))[:6] or [],
            "common_mistake": _string(data.get("common_mistake")),
            "concept_tags": normalise_tags(_string_list(data.get("concept_tags"))) or [brief["concept"]],
        }

    def _note_lesson(self, concept, difficulty, retrieval):
        """Offline lesson: render the local concept note, enriched with RAG passages."""
        meta = CONCEPTS.get(concept, {})
        note = _read_note(concept)

        if note:
            self._emit("Served the local concept note for '{}' (offline mode)".format(
                concept_title(concept)), "warning")
            body = note
        else:
            body = meta.get("summary", "No note available for this concept yet.")

        explanation, code, points = _split_note(body)

        extra = []
        for p in (retrieval.get("passages") or [])[:2]:
            extra.append(p["text"][:600])

        return {
            "title": "{}".format(concept_title(concept)),
            "explanation": explanation + (("\n\n" + "\n\n".join(extra)) if extra else ""),
            "code_example": code,
            "code_walkthrough": [],
            "key_points": points,
            "common_mistake": "",
            "concept": concept,
            "concept_tags": [concept],
            "difficulty": difficulty,
            "grounded": bool(retrieval.get("passages")),
            "sources": retrieval.get("citations", []),
            "passages": retrieval.get("passages", []),
            "retrieval_trace": retrieval.get("trace"),
            "generated_by": "local-note",
            "model": None,
            "offline_reason": (
                "No LLM key configured" if not self.llm_available
                else "LLM request failed, local note served instead"
            ),
        }

    # =========================================================
    # QUIZ
    # =========================================================
    def generate_quiz(self, brief, num_questions=5):
        """
        Thin 'practice' wrapper forwarding to generate_quiz_from_blueprint.
        Keeps backward compatibility with the Coordinator and tests.
        """
        brief = _coerce_brief(brief, mode="quiz")
        concept = brief.get("concept") or "class-definition"
        difficulty = brief.get("difficulty") or "Easy"
        student_id = brief.get("student_id")
        slots = build_blueprint(
            kind="practice",
            student_id=student_id,
            concepts=[concept],
            n=num_questions,
            difficulty=difficulty,
        )
        return self.generate_quiz_from_blueprint(
            slots, student_id=student_id, focus_notes=brief.get("focus_notes")
        )

    def verify_group(self, group_questions, concept):
        """
        Independent verifier gate (Phase 4B).
        Input per question: stem and four options WITHOUT answer key and WITHOUT tags,
        plus concept misconception catalog (id + wrong_belief).
        Verifier model = EDUGEN_VERIFIER_MODEL (default qwen/qwen3.8-27b, fallback openai/gpt-oss-20b).
        Must differ from generator model.
        Returns: (accepted, rejected_with_reasons, tags_removed_count, warning_str_or_None, verifier_model_used)
        """
        if not group_questions:
            return [], [], 0, None, None

        v_model = os.environ.get("EDUGEN_VERIFIER_MODEL") or self.verifier_model
        v_fallback = os.environ.get("EDUGEN_VERIFIER_FALLBACK_MODEL") or self.verifier_fallback_model

        if v_model == self.model:
            v_model = v_fallback
            if v_model == self.model:
                v_model = "openai/gpt-oss-20b" if self.model != "openai/gpt-oss-20b" else "qwen/qwen3.8-27b"

        if not self.llm_available:
            for q in group_questions:
                q["verified"] = 0
                q["verifier_model"] = None
            return group_questions, [], 0, "verifier_unavailable_no_llm", None

        cat = misconceptions_for(concept) or []
        cat_summary = [{"id": m["id"], "wrong_belief": m["wrong_belief"]} for m in cat]

        system_prompt = (
            "You are an independent Java / OOP exam verifier, quality assessor, and grader.\n"
            "Evaluate each multiple-choice question independently without an answer key.\n"
            "Determine the single correct option index (0, 1, 2, or 3).\n"
            "If more than one option is arguably true, or none is true, or the question is unanswerable, set ambiguous: true.\n"
            "For bug_find questions, state the first javac compile error in 'note'.\n"
            "For each option (0-3), assign the matching misconception ID from the catalog if it represents that misconception; otherwise null.\n"
            "Output strictly valid JSON and nothing else."
        )

        user_parts = [
            f"Verify the following {len(group_questions)} question(s) for Java concept '{concept}'.",
            "",
            "MISCONCEPTION CATALOG FOR THIS CONCEPT:",
        ]
        if cat_summary:
            for m in cat_summary:
                user_parts.append(f"- ID: {m['id']}")
                user_parts.append(f"  Wrong Belief: {m['wrong_belief']}")
        else:
            user_parts.append("(No misconceptions cataloged for this concept)")

        user_parts.append("\nQUESTIONS TO VERIFY (Answer key is omitted):")
        for idx, q in enumerate(group_questions):
            user_parts.append(f"\n--- Question #{idx} (qtype: {q.get('qtype')}) ---")
            user_parts.append(f"Stem: {q['question']}")
            user_parts.append("Options:")
            for oi, opt in enumerate(q["options"]):
                opt_str = opt["text"] if isinstance(opt, dict) else str(opt)
                user_parts.append(f"  [{oi}] {opt_str}")

        user_parts.append(
            "\nOUTPUT FORMAT:\n"
            'Return a JSON object: {"verifications": [\n'
            '  {"index": 0, "answer": 0, "ambiguous": false, "labels": [null, "catalog_id", null, null], "difficulty_estimate": "Easy|Medium|Hard", "note": "..."},\n'
            '  ...\n'
            ']}'
        )

        try:
            resp = self._invoke_llm(
                system_prompt,
                "\n".join(user_parts),
                model=v_model,
                fallback_model=v_fallback,
                max_tokens=1500,
                purpose="verify",
                reasoning_effort="low",
            )
        except Exception:
            resp = None

        if not resp:
            warning = f"verifier_unavailable: model '{v_model}' call failed"
            self._emit(warning, "warning")
            for q in group_questions:
                q["verified"] = 0
                q["verifier_model"] = None
            return group_questions, [], 0, warning, None

        v_items = resp.get("verifications") or resp.get("questions") or resp.get("items") or []
        if not isinstance(v_items, list):
            warning = f"verifier_unavailable: invalid response format from '{v_model}'"
            self._emit(warning, "warning")
            for q in group_questions:
                q["verified"] = 0
                q["verifier_model"] = None
            return group_questions, [], 0, warning, None

        v_map = {}
        for i, item in enumerate(v_items):
            idx = item.get("index", i)
            try:
                v_map[int(idx)] = item
            except (ValueError, TypeError):
                v_map[i] = item

        accepted = []
        rejected = []
        tags_removed = 0

        DIFF_LEVELS = {"Easy": 0, "Medium": 1, "Hard": 2}

        for idx, q in enumerate(group_questions):
            v = v_map.get(idx)
            if not v and idx < len(v_items):
                v = v_items[idx]
            if not v:
                rejected.append((q, "verifier_missing_result"))
                continue

            ans = v.get("answer")
            if ans is None and "correct" in v:
                ans = v.get("correct")
            amb = bool(v.get("ambiguous", False))
            labels = v.get("labels")
            if labels is None and "options" in v:
                labels = [
                    opt.get("misconception_id") if isinstance(opt, dict) else None
                    for opt in v.get("options", [])
                ]
            if labels is None:
                labels = []

            try:
                ans = int(ans)
            except (TypeError, ValueError):
                ans = None

            # Difficulty estimate check (Phase 4C)
            diff_est_raw = v.get("difficulty_estimate")
            diff_est_str = str(diff_est_raw or "").strip().capitalize()
            v_level = DIFF_LEVELS.get(diff_est_str)
            q_diff = str(q.get("difficulty") or "Easy").strip().capitalize()
            lbl_level = DIFF_LEVELS.get(q_diff, 0)

            diff_mismatch = False
            if v_level is not None:
                if abs(v_level - lbl_level) >= 2:
                    diff_mismatch = True

            if diff_mismatch:
                rejected.append((q, "verifier_difficulty_mismatch"))
                continue

            if ans == q["correct"] and not amb:
                q["verified"] = 1
                q["verifier_model"] = v_model
                q["difficulty_verified"] = v_level if v_level is not None else lbl_level
                q["verifier_labels"] = labels
                orig_mids = list(q.get("option_misconception_ids") or [None] * 4)
                while len(orig_mids) < 4:
                    orig_mids.append(None)
                while len(labels) < 4:
                    labels.append(None)

                aligned_mids = []
                for oi in range(4):
                    if oi == q["correct"]:
                        aligned_mids.append(None)
                    elif orig_mids[oi] is not None:
                        if orig_mids[oi] == labels[oi]:
                            aligned_mids.append(orig_mids[oi])
                        else:
                            tags_removed += 1
                            aligned_mids.append(None)
                    else:
                        aligned_mids.append(None)

                q["option_misconception_ids"] = aligned_mids
                accepted.append(q)
            else:
                reason = (
                    "verifier_ambiguous"
                    if amb
                    else ("verifier_wrong_answer" if ans != q["correct"] else "verifier_rejected")
                )
                rejected.append((q, reason))

        return accepted, rejected, tags_removed, None, v_model

    def generate_quiz_from_blueprint(
        self,
        slots,
        student_id=None,
        focus_notes=None,
        prior_questions=None,
        allow_partial=False,
    ):
        """
        Generate a multi-slot quiz from blueprint slots through the full Phase 4B quality gates:
          - Parallel group generation with ThreadPoolExecutor (max 4 workers).
          - Prompt fixes targeting realistic misconceptions, strict compile counts, and length balance.
          - Deterministic normalization gates (length ratio, null tags count <= 2).
          - Java check (compilation, code_output matching, bug_find single compile error & keyword).
          - Independent verifier (model != generator, ambiguous rejection, tag consensus).
          - Novelty / dedupe against same quiz, student history, and bank reference.
        """
        if not slots:
            return self._unavailable_quiz("class-definition", "Easy", {})

        main_concept = slots[0]["concept"]
        main_difficulty = slots[0]["difficulty"]

        t0 = time.time()
        groups = group_slots(slots)
        requested_count = len(slots)
        accepted_questions = []
        rejected_by_reason = collections.defaultdict(int)
        models_used = []
        all_citations = []
        first_trace = None
        warnings = []
        total_tags_removed = 0
        dedupe_mode = "vector"

        stage_timings = {
            "retrieve": 0.0,
            "generate": 0.0,
            "verify": 0.0,
            "java": 0.0,
            "dedupe": 0.0,
        }

        java_checker = JavaChecker()
        java_status = "available" if java_checker.available else "unavailable"

        if not self.llm_available:
            unavail = self._unavailable_quiz(main_concept, main_difficulty, {})
            unavail["build_report"] = {
                "requested": requested_count,
                "accepted": 0,
                "rejected_by_reason": {"llm_unavailable": requested_count},
                "groups": len(groups),
                "latency_ms": 0.0,
                "models": [],
                "java_check": java_status,
                "dedupe": dedupe_mode,
                "verifier_tags_removed": 0,
                "stage_timings_ms": stage_timings,
                "warnings": ["llm_unavailable"],
            }
            return unavail

        def _execute_group(grp, count_override=None):
            grp_concept = grp["concept"]
            grp_diff = grp["difficulty"]
            grp_count = count_override if count_override is not None else grp["count"]
            grp_mids = grp["target_misconceptions"]
            grp_qtypes = grp["qtypes"][:grp_count]
            if len(grp_qtypes) < grp_count:
                grp_qtypes = (grp_qtypes + ["concept"] * grp_count)[:grp_count]

            # 1. Retrieve (Shrunk: at most 2 passages <= 1200 chars, at most 2 ref questions)
            t_r0 = time.time()
            lesson_brief = {
                "concept": grp_concept,
                "difficulty": grp_diff,
                "mode": "lesson",
                "top_k": 2,
                "student_id": student_id,
            }
            lesson_ret = self._retrieve(lesson_brief) if self.retriever else {}
            raw_passages = lesson_ret.get("passages") or []
            truncated_passages = []
            for p in raw_passages[:2]:
                ptxt = str(p.get("text") or "").strip()
                if len(ptxt) > 1200:
                    ptxt = ptxt[:1197] + "..."
                if ptxt:
                    truncated_passages.append(ptxt)
            context = "\n\n".join(truncated_passages) if truncated_passages else (lesson_ret.get("context", "")[:2400])
            citations = lesson_ret.get("citations", [])[:2]
            trace = lesson_ret.get("trace")

            ref_questions = (
                self.retriever.retrieve_reference_questions(grp_concept, grp_diff, k=2)
                if self.retriever else []
            )[:2]
            ref_ids = [
                r.get("question_id") or r.get("chunk_id")
                for r in ref_questions
                if (r.get("question_id") or r.get("chunk_id"))
            ]
            t_retrieve = (time.time() - t_r0) * 1000.0

            # 2. Assemble prompt & Generate
            t_g0 = time.time()
            meta = CONCEPTS.get(grp_concept, {})
            title = meta.get("title", concept_title(grp_concept))
            summary = meta.get("summary", "")

            system_prompt = (
                "You are an expert Java / OOP exam author and diagnostic assessment designer.\n"
                "Your role is to write rigorous multiple-choice questions targeting specific student misconceptions.\n"
                "Output strictly a single valid JSON object and nothing else."
            )

            user_parts = [
                f"Generate {grp_count} multiple-choice question(s) for Java / OOP concept '{grp_concept}' ({title}) at {grp_diff} difficulty.",
                "",
                f"Concept Summary: {summary}",
            ]

            if context:
                user_parts += ["", "SOURCE MATERIAL (Knowledge Base):", context]

            if ref_questions:
                user_parts += [
                    "",
                    "REFERENCE QUESTIONS (STYLE AND DIFFICULTY EXAMPLES ONLY):",
                    "Do NOT copy or adapt these questions. Use completely new scenarios, classes, and code.",
                ]
                for idx, rq in enumerate(ref_questions, 1):
                    rq_text = rq.get("question") or rq.get("question_text", "")
                    rq_opts = rq.get("options") or []
                    user_parts.append(f"Example {idx}: {rq_text}")
                    if rq_opts and isinstance(rq_opts, list):
                        for oi, opt in enumerate(rq_opts):
                            user_parts.append(f"  ({oi}) {opt}")

            if grp_mids:
                user_parts += ["", "TARGET MISCONCEPTIONS:"]
                for mid in grp_mids:
                    m_item = MISCONCEPTIONS.get(mid, {})
                    wb = m_item.get("wrong_belief", "")
                    user_parts.append(f"- ID: {mid}")
                    if wb:
                        user_parts.append(f"  Wrong Belief: {wb}")

            prior_stems = [
                q.get("question")
                for q in (prior_questions or [])
                if q.get("concept") == grp_concept and q.get("question")
            ]
            if prior_stems:
                user_parts += [
                    "",
                    "DO NOT REPEAT OR DUPLICATE THESE PREVIOUS QUESTIONS (test a completely different facet or scenario):",
                ]
                for ps in prior_stems[:3]:
                    user_parts.append(f"- {ps.strip()[:140]}")

            user_parts += [
                "",
                "REQUESTED QUESTIONS PER TYPE:",
                f"Write {grp_count} question(s) with these respective question types (qtype): {', '.join(grp_qtypes)}.",
                "- 'concept': conceptual understanding question",
                "- 'code_output': snippet provided, asks what the code prints or returns (must contain ```java fence)",
                "- 'bug_find': snippet provided, asks what bug / compile error / exception occurs (must contain ```java fence)",
            ]
            if grp_count > 1:
                user_parts.append(
                    f"Ensure each of the {grp_count} questions tests a completely distinct scenario or facet with no code or text overlap."
                )

            user_parts += [
                "",
                "RULES:",
                "1. Exactly ONE option may be true. No option may be a true statement about the code. For bug_find the snippet must contain exactly ONE compile error.",
                "2. Design each question so a target misconception can appear as a REALISTIC wrong answer to THIS question. If a target cannot be expressed naturally here, do NOT force it: give that option misconception_id null and make it a different plausible slip. Never write a distractor that contradicts the code shown (e.g. mentions final, static or a visibility change the code does not contain).",
                "3. Difficulty Guidelines: Easy = recognise one fact, short stem, snippet of at most 8 lines that compiles. Medium = one rule applied to a short snippet with one trap. Hard = two interacting rules or a subtle trap.",
                "4. All four options similar in length and detail; the correct one must not be the longest.",
                "5. For each wrong option, set 'misconception_id' to that misconception's exact ID from the TARGET MISCONCEPTIONS list if applicable, else null. At most two wrong options may have 'misconception_id': null.",
                "6. The correct option's 'misconception_id' MUST be null.",
                "7. The explanation refers strictly to option content and why the concept works, NEVER naming options by letter or number (do NOT say 'Option A', 'Choice 1', '(B)', etc.).",
                "8. Java code MUST be enclosed in ```java ... ``` fences and must compile, unless qtype is 'bug_find'.",
                "9. Spread the correct position (do not put all answers at index 0).",
                "",
                "OUTPUT FORMAT:",
                'Return a JSON object with a "questions" array. Each item must have:',
                '{',
                '  "question": "question text (with ```java snippet if code_output or bug_find)",',
                '  "qtype": "concept" | "code_output" | "bug_find",',
                '  "options": [',
                '    {"text": "option 0 text", "misconception_id": "... or null"},',
                '    {"text": "option 1 text", "misconception_id": "... or null"},',
                '    {"text": "option 2 text", "misconception_id": "... or null"},',
                '    {"text": "option 3 text", "misconception_id": "... or null"}',
                '  ],',
                '  "correct": 0,',
                '  "explanation": "...",',
                '  "facet": "..."',
                '}',
            ]

            data = self._invoke_llm(
                system_prompt,
                "\n".join(user_parts),
                max_tokens=3000,
                purpose="generate",
                reasoning_effort="low",
            )
            m_used = self.last_model_used or self.model
            t_generate = (time.time() - t_g0) * 1000.0

            # 3. Deterministic Normalization Gate
            norm_accepted = []
            local_rejections = collections.defaultdict(int)
            if data and isinstance(data.get("questions"), list):
                for raw_q in data["questions"]:
                    if not isinstance(raw_q, dict):
                        local_rejections["malformed_item"] += 1
                        continue
                    raw_q["reference_ids"] = ref_ids
                    record, reject_reason = normalize_question(raw_q, grp_concept, grp_diff)
                    if record:
                        norm_accepted.append(record)
                    else:
                        local_rejections[reject_reason or "unknown"] += 1

            # 4. Java Check Gate
            t_j0 = time.time()
            java_passed = []
            if java_checker.available:
                for q in norm_accepted:
                    j_ok, j_reason = java_checker.check_question(q)
                    if j_ok:
                        java_passed.append(q)
                    else:
                        local_rejections[j_reason or "java_rejected"] += 1
            else:
                for q in norm_accepted:
                    local_rejections["java_unverified"] += 1
                    java_passed.append(q)
            t_java = (time.time() - t_j0) * 1000.0

            # 5. Independent Verifier Gate
            t_v0 = time.time()
            v_accepted, v_rejected, v_tags_rem, v_warning, v_model = self.verify_group(java_passed, grp_concept)
            for _, v_reason in v_rejected:
                local_rejections[v_reason or "verifier_rejected"] += 1
            t_verify = (time.time() - t_v0) * 1000.0

            return {
                "candidates": v_accepted,
                "rejections": local_rejections,
                "model_used": m_used,
                "citations": citations,
                "trace": trace,
                "ref_questions": ref_questions,
                "tags_removed": v_tags_rem,
                "warning": v_warning,
                "timings": {
                    "retrieve": t_retrieve,
                    "generate": t_generate,
                    "java": t_java,
                    "verify": t_verify,
                },
            }

        # First pass: execute groups in parallel
        max_workers = min(4, max(1, len(groups)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            group_futures = [executor.submit(_execute_group, grp) for grp in groups]
            group_outputs = [f.result() for f in group_futures]

        group_accepted_counts = collections.defaultdict(int)

        for g_idx, res in enumerate(group_outputs):
            if res.get("model_used"):
                models_used.append(res["model_used"])
            if res.get("citations"):
                all_citations.extend(res["citations"])
            if first_trace is None and res.get("trace"):
                first_trace = res["trace"]
            if res.get("warning"):
                warnings.append(res["warning"])
            total_tags_removed += res.get("tags_removed", 0)

            for reason, count in res["rejections"].items():
                rejected_by_reason[reason] += count

            for k, dur in res["timings"].items():
                stage_timings[k] += dur

            # Stage 6: Dedupe
            for q in res["candidates"]:
                t_d0 = time.time()
                d_ok, d_reason, d_mode = check_question_novelty(
                    q,
                    accepted_questions,
                    student_id=student_id,
                    ref_questions=res["ref_questions"],
                    prior_questions=prior_questions,
                )
                stage_timings["dedupe"] += (time.time() - t_d0) * 1000.0
                if d_mode == "lexical":
                    dedupe_mode = "lexical"

                if d_ok:
                    accepted_questions.append(q)
                    group_accepted_counts[g_idx] += 1
                else:
                    rejected_by_reason[d_reason or "dedupe_rejected"] += 1

        # Check for shortfall groups and retry failed groups once
        shortfall_groups = []
        for g_idx, grp in enumerate(groups):
            needed = grp["count"] - group_accepted_counts[g_idx]
            if needed > 0:
                shortfall_groups.append((g_idx, grp, needed))

        if shortfall_groups:
            self._emit(
                f"Shortfall across {len(shortfall_groups)} group(s) - retrying failed groups once",
                "info",
            )
            with ThreadPoolExecutor(max_workers=min(4, len(shortfall_groups))) as retry_executor:
                retry_futures = [
                    (g_idx, retry_executor.submit(_execute_group, grp, count_override=needed))
                    for g_idx, grp, needed in shortfall_groups
                ]
                for g_idx, f in retry_futures:
                    res = f.result()
                    if res.get("model_used"):
                        models_used.append(res["model_used"])
                    if res.get("warning"):
                        warnings.append(res["warning"])
                    total_tags_removed += res.get("tags_removed", 0)

                    for reason, count in res["rejections"].items():
                        rejected_by_reason[reason] += count

                    for k, dur in res["timings"].items():
                        stage_timings[k] += dur

                    for q in res["candidates"]:
                        t_d0 = time.time()
                        d_ok, d_reason, d_mode = check_question_novelty(
                            q,
                            accepted_questions,
                            student_id=student_id,
                            ref_questions=res["ref_questions"],
                            prior_questions=prior_questions,
                        )
                        stage_timings["dedupe"] += (time.time() - t_d0) * 1000.0
                        if d_mode == "lexical":
                            dedupe_mode = "lexical"

                        if d_ok:
                            accepted_questions.append(q)
                        else:
                            rejected_by_reason[d_reason or "dedupe_rejected"] += 1

        total_latency_ms = round((time.time() - t0) * 1000.0, 2)
        build_report = {
            "requested": requested_count,
            "accepted": len(accepted_questions),
            "rejected_by_reason": dict(rejected_by_reason),
            "groups": len(groups),
            "latency_ms": total_latency_ms,
            "models": sorted(list(set(models_used))) if models_used else ([self.model] if self.llm_available else []),
            "java_check": java_status,
            "dedupe": dedupe_mode,
            "verifier_tags_removed": total_tags_removed,
            "stage_timings_ms": {k: round(v, 2) for k, v in stage_timings.items()},
            "warnings": warnings,
        }

        # Final 60% threshold check
        if len(accepted_questions) < 0.60 * requested_count and not allow_partial:
            err = (
                "Generated quiz quality threshold not met: only {}/{} questions accepted ({:.1f}% < 60%).".format(
                    len(accepted_questions),
                    requested_count,
                    (len(accepted_questions) / requested_count) * 100.0 if requested_count else 0.0,
                )
            )
            self._emit(err, "error")
            unavail = self._unavailable_quiz(main_concept, main_difficulty, {"citations": all_citations, "trace": first_trace})
            unavail["error"] = err
            unavail["build_report"] = build_report
            return unavail

        self._emit(
            "Quiz generated: {}/{} questions accepted in {:.1f}s across {} group(s)".format(
                len(accepted_questions), requested_count, total_latency_ms / 1000.0, len(groups)
            ),
            "success",
        )

        return {
            "concept": main_concept,
            "concept_title": concept_title(main_concept),
            "difficulty": main_difficulty,
            "questions": accepted_questions,
            "total_generated": len(accepted_questions),
            "grounded": bool(all_citations),
            "sources": all_citations,
            "retrieval_trace": first_trace,
            "generated_by": "llm+rag" if all_citations else "llm",
            "model": models_used[0] if models_used else self.model,
            "build_report": build_report,
        }

    def _unavailable_quiz(self, concept, difficulty, retrieval):
        """
        There is no static question bank in FYP-2 - questions are the Concept
        Clarifier's job. If the LLM cannot be reached we say so plainly rather
        than silently serving stale hand-written questions.
        """
        reason = self.last_error or (
            "No LLM API key is configured. Set GROQ_API_KEY in .env and restart."
            if not self.llm_available
            else "The language model did not return a usable quiz."
        )
        self._emit("Quiz generation unavailable for '{}' - {}".format(
            concept_title(concept), reason), "error")
        return {
            "concept": concept,
            "concept_title": concept_title(concept),
            "difficulty": difficulty,
            "questions": [],
            "total_generated": 0,
            "grounded": False,
            "sources": retrieval.get("citations", []),
            "retrieval_trace": retrieval.get("trace"),
            "generated_by": "unavailable",
            "model": None,
            "error": reason,
        }

    # =========================================================
    # Shared plumbing
    # =========================================================
    def _retrieve(self, brief):
        if not self.retriever:
            return {"ready": False, "passages": [], "context": "", "citations": []}
        try:
            result = self.retriever.retrieve(brief)
        except Exception as exc:                                   # noqa: BLE001
            self._emit("Retrieval error: {}".format(exc), "error")
            return {"ready": False, "passages": [], "context": "", "citations": []}

        if result.get("ready"):
            self._emit(
                "Retrieved {} passages from the knowledge base for '{}'".format(
                    len(result["passages"]), brief["concept"]),
                "info",
                {"sources": [c["source"] for c in result.get("citations", [])]},
            )

            # Log retrieval to database and activity log (Requirement 5)
            try:
                from core.agent_log import add_log
                from core.db_repo import record_rag_retrieval

                trace = result.get("trace") or {}
                top_items = trace.get("top") or []
                top1_cos = top_items[0].get("cosine", 0.0) if top_items else 0.0
                cand_count = trace.get("candidates", len(top_items))
                emb_sig = trace.get("embedder", "unknown")
                concept = brief.get("concept", "")
                mode = brief.get("mode", "lesson")
                student_id = brief.get("student_id")
                if not student_id:
                    try:
                        from core.auth import current_student_id
                        student_id = current_student_id()
                    except Exception:
                        student_id = None

                record_rag_retrieval(
                    run_id=None,
                    student_id=student_id,
                    concept=concept,
                    mode=mode,
                    query=brief.get("query", ""),
                    embedder=emb_sig,
                    results=top_items,
                )
                add_log(
                    "Concept Clarifier",
                    f"RAG: {concept} {mode} -> top1 cosine {top1_cos:.2f}, {cand_count} candidates, embedder {emb_sig}",
                    "info",
                )
            except Exception as exc:
                try:
                    from core.agent_log import add_log
                    add_log("Concept Clarifier", f"RAG log failed: {exc}", "warn")
                except Exception:
                    pass
        elif result.get("error"):
            self._emit("Knowledge base unavailable: {}".format(result["error"]), "warning")
        return result

    def _create_completion(
        self,
        model,
        messages,
        temperature,
        max_tokens,
        json_mode=True,
        purpose="generate",
        reasoning_effort=None,
    ):
        """Call Groq/OpenAI with HTTP 429 rate limit retry, token tracking, and reasoning_effort support."""
        from core.token_budget import check_429_exhaustion, is_reasoning_supported, mark_reasoning_unsupported

        max_429_retries = 2
        for retry_idx in range(max_429_retries + 1):
            t0 = time.time()
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if reasoning_effort and is_reasoning_supported(model):
                kwargs["reasoning_effort"] = reasoning_effort

            try:
                response = self.client.chat.completions.create(**kwargs)
                raw = response.choices[0].message.content or ""
                lat_ms = int((time.time() - t0) * 1000)
                ptoks = getattr(response.usage, "prompt_tokens", None) if getattr(response, "usage", None) else None
                ctoks = getattr(response.usage, "completion_tokens", None) if getattr(response, "usage", None) else None
                ttoks = getattr(response.usage, "total_tokens", None) if getattr(response, "usage", None) else (
                    (ptoks + ctoks) if (ptoks is not None and ctoks is not None) else None
                )
                record_llm_call(None, "concept_clarifier", purpose, model, lat_ms, True, None, ptoks, ctoks, ttoks)
                return raw, None
            except Exception as exc:
                lat_ms = int((time.time() - t0) * 1000)
                status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                err_text = str(exc).lower()

                # If HTTP 400 occurred with reasoning_effort, retry once without it and remember model
                if (status_code == 400 or "400" in str(exc)) and "reasoning_effort" in kwargs:
                    mark_reasoning_unsupported(model)
                    del kwargs["reasoning_effort"]
                    try:
                        t0_retry = time.time()
                        response = self.client.chat.completions.create(**kwargs)
                        raw = response.choices[0].message.content or ""
                        lat_ms = int((time.time() - t0_retry) * 1000)
                        ptoks = getattr(response.usage, "prompt_tokens", None) if getattr(response, "usage", None) else None
                        ctoks = getattr(response.usage, "completion_tokens", None) if getattr(response, "usage", None) else None
                        ttoks = getattr(response.usage, "total_tokens", None) if getattr(response, "usage", None) else (
                            (ptoks + ctoks) if (ptoks is not None and ctoks is not None) else None
                        )
                        record_llm_call(None, "concept_clarifier", purpose, model, lat_ms, True, None, ptoks, ctoks, ttoks)
                        return raw, None
                    except Exception as retry_exc:
                        exc = retry_exc
                        status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                        err_text = str(exc).lower()

                record_llm_call(None, "concept_clarifier", purpose, model, lat_ms, False, str(exc))

                is_429 = (
                    status_code == 429
                    or "429" in str(exc)
                    or "rate_limit" in err_text
                    or "rate limit" in err_text
                    or "too many requests" in err_text
                )
                if is_429:
                    retry_after = None
                    resp_obj = getattr(exc, "response", None)
                    if resp_obj and hasattr(resp_obj, "headers"):
                        retry_after = resp_obj.headers.get("retry-after")
                    if not retry_after:
                        m_wait = re.search(r"try again in (\d+(?:\.\d+)?)s", err_text)
                        if m_wait:
                            retry_after = float(m_wait.group(1))
                        m_min = re.search(r"try again in (\d+)m([\d\.]+)s", err_text)
                        if m_min:
                            mins = float(m_min.group(1))
                            secs = float(m_min.group(2))
                            retry_after = mins * 60.0 + secs

                    # If 429 says tokens-per-day or Retry-After > 60s, mark exhausted today without sleeping
                    if check_429_exhaustion(model, err_text, retry_after):
                        self._emit(
                            f"Model '{model}' reached daily token limit or Retry-After > 60s; marked exhausted for today.",
                            "warning",
                        )
                        return None, exc

                    if retry_idx < max_429_retries:
                        try:
                            sleep_sec = min(20.0, max(1.0, float(retry_after) if retry_after else 2.0))
                        except (ValueError, TypeError):
                            sleep_sec = 2.0
                        self._emit(
                            f"HTTP 429 rate limit on '{model}': sleeping {sleep_sec:.1f}s (retry {retry_idx + 1}/{max_429_retries})",
                            "warning",
                        )
                        time.sleep(sleep_sec)
                        continue
                return None, exc

    def _call_llm(
        self,
        system_prompt,
        user_prompt,
        model=None,
        fallback_model=None,
        max_tokens=3000,
        purpose="generate",
        reasoning_effort=None,
    ):
        """Try primary model, then fallback model. Returns a parsed dict or None."""
        from core.token_budget import is_model_exhausted

        if model:
            models_to_try = [model]
            if fallback_model and fallback_model != model:
                models_to_try.append(fallback_model)
        else:
            models_to_try = [self.model, self.fallback_model]
            if len(models_to_try) > 1 and models_to_try[0] == models_to_try[1]:
                models_to_try = [models_to_try[0]]

        # Exclude models marked exhausted today or exceeding daily token budget
        available_models = [
            m for m in models_to_try
            if not is_model_exhausted(m, self.model, self.fallback_model)
        ]
        if not available_models:
            self.last_error = "Daily LLM budget reached"
            self._emit("Daily LLM budget reached. Live generation is disabled.", "warning")
            return None

        models_to_try = available_models
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for attempt, target_model in enumerate(models_to_try):
            temperature = 0.6 if attempt == 0 else 0.4
            raw, exc = self._create_completion(
                target_model,
                messages,
                temperature,
                max_tokens,
                json_mode=True,
                purpose=purpose,
                reasoning_effort=reasoning_effort,
            )

            if exc:
                status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if status_code == 401 or "401" in str(exc):
                    self.last_error = "Invalid API key (HTTP 401): {}".format(exc)
                    self._emit(self.last_error, "error")
                    return None

                err_text = str(exc).lower()
                if "response_format" in err_text or "json_object" in err_text or "json mode" in err_text:
                    self._emit(
                        "Model '{}' rejected json_object response_format; retrying without it".format(target_model),
                        "info",
                    )
                    raw, retry_exc = self._create_completion(
                        target_model,
                        messages,
                        temperature,
                        max_tokens,
                        json_mode=False,
                        purpose=purpose,
                        reasoning_effort=reasoning_effort,
                    )
                    if retry_exc:
                        retry_status = getattr(retry_exc, "status_code", None) or getattr(retry_exc, "code", None)
                        if retry_status == 401 or "401" in str(retry_exc):
                            self.last_error = "Invalid API key (HTTP 401): {}".format(retry_exc)
                            self._emit(self.last_error, "error")
                            return None
                        self.last_error = "Model '{}' failed retry without response_format: {}".format(target_model, retry_exc)
                        self._emit(self.last_error, "warning")
                        continue
                else:
                    self.last_error = "LLM call failed on '{}': {}".format(target_model, exc)
                    self._emit(self.last_error, "warning")
                    continue

            data = _parse_json(raw)
            if data:
                self.last_error = None
                self.last_model_used = target_model
                if attempt > 0:
                    self._emit("Primary model failed; fallback model '{}' answered".format(target_model), "warning")
                return data
            else:
                self.last_error = "Model '{}' returned invalid JSON".format(target_model)
                self._emit(self.last_error, "warning")

        return None

        return None

    def status(self):
        return {
            "llm_available": self.llm_available,
            "model": self.model if self.llm_available else None,
            "fallback_model": self.fallback_model if self.llm_available else None,
            "rag_attached": self.retriever is not None,
            "last_error": self.last_error,
        }


# =============================================================
# Helpers
# =============================================================
def _coerce_brief(brief, mode):
    """Accept either a full brief dict or a plain (concept, difficulty) pair."""
    if isinstance(brief, dict):
        out = dict(brief)
    else:
        out = {"concept": brief, "difficulty": "Easy"}
    out.setdefault("concept", "class-definition")
    out.setdefault("difficulty", "Easy")
    out.setdefault("mode", mode)
    out.setdefault("concept_tags", [out["concept"]])
    out.setdefault("focus_notes", [])
    out.setdefault("top_k", 6)
    if not out.get("query"):
        meta = CONCEPTS.get(out["concept"], {})
        out["query"] = " ".join([
            meta.get("title", out["concept"].replace("-", " ")),
            meta.get("summary", ""),
            " ".join(meta.get("keywords", [])),
        ]).strip()
    return out


def _difficulty_guidance(difficulty, quiz=False):
    if difficulty == "Easy":
        return ("Assume the student is meeting this for the first time. Define every term, keep the "
                "code under 20 lines, and test recall and recognition."
                if quiz else
                "Assume the student is meeting this for the first time. Define every term, use one "
                "small example, avoid edge cases.")
    if difficulty == "Hard":
        return ("Assume the student knows the basics. Test subtle behaviour, output prediction, "
                "compile-time vs runtime distinctions and realistic traps."
                if quiz else
                "Assume the student knows the basics. Cover edge cases, JVM-level behaviour and how "
                "this interacts with other OOP features.")
    return ("Test application rather than recall: short code snippets where the student must reason "
            "about what happens."
            if quiz else
            "The student knows the definition. Focus on how and when to apply it, with a realistic "
            "example and one common pitfall.")


def _parse_json(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except ValueError:
            return None
    return None


def _validate_questions(questions, concept):
    if not isinstance(questions, list) or not questions:
        return None
    cleaned = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        text = _string(q.get("question"))
        options = q.get("options")
        correct = q.get("correct")
        if not text or not isinstance(options, list) or len(options) != 4:
            continue
        options = [_string(o) for o in options]
        if any(not o for o in options) or len(set(options)) < 4:
            continue
        if isinstance(correct, str) and correct.strip().isdigit():
            correct = int(correct.strip())
        if isinstance(correct, str) and len(correct.strip()) == 1:
            correct = "ABCD".find(correct.strip().upper())
        if not isinstance(correct, int) or not 0 <= correct < 4:
            continue
        cleaned.append({
            "question": text,
            "options": options,
            "correct": correct,
            "explanation": _string(q.get("explanation")),
            "concept_tags": normalise_tags(_string_list(q.get("concept_tags"))) or [concept],
        })
    return cleaned or None


def _string(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n\n".join(str(v) for v in value)
    return str(value).strip()


def _string_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split("\n") if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _read_note(concept):
    path = NOTES_DIR / "{}.md".format(concept)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    # drop front matter
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    return text.strip()


def _split_note(markdown_text):
    """Turn a concept note into (prose, java_code, key_points)."""
    code_blocks = re.findall(r"```java\s*\n(.*?)```", markdown_text, re.DOTALL)
    code = code_blocks[0].strip() if code_blocks else ""
    without_code = re.sub(r"```.*?```", "", markdown_text, flags=re.DOTALL)

    points = []
    key_section = re.search(r"##\s*Key points\s*\n(.*?)(?:\n##|\Z)", without_code,
                            re.DOTALL | re.IGNORECASE)
    if key_section:
        for line in key_section.group(1).splitlines():
            line = line.strip().lstrip("-*").strip()
            if line:
                points.append(line)
        without_code = without_code.replace(key_section.group(0), "")

    prose_lines = []
    for line in without_code.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        prose_lines.append(line)
    prose = re.sub(r"\n{3,}", "\n\n", "\n".join(prose_lines)).strip()
    return prose, code, points[:6]
