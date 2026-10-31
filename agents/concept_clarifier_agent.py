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
import json
import os
import re
import time
from pathlib import Path

from core.concepts import CANONICAL_CONCEPT_TAGS, CONCEPTS, concept_title, normalise_tags
from core.db_repo import record_llm_call
from core.misconceptions import MISCONCEPTIONS
from core.quiz_engine import build_blueprint, group_slots, normalize_question

NOTES_DIR = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "notes"


class ConceptClarifierAgent(object):

    GROQ_BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = os.environ.get("EDUGEN_LLM_MODEL", "openai/gpt-oss-120b")
    FALLBACK_MODEL = os.environ.get("EDUGEN_LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")

    def __init__(self, api_key=None, model=None, retriever=None, log=None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model or os.environ.get("EDUGEN_LLM_MODEL") or self.DEFAULT_MODEL
        self.fallback_model = os.environ.get("EDUGEN_LLM_FALLBACK_MODEL") or self.FALLBACK_MODEL
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

        data = self._call_llm(system, "\n".join(parts))
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

    def generate_quiz_from_blueprint(self, slots, student_id=None, focus_notes=None):
        """
        Generate a multi-slot quiz from blueprint slots.
        Groups by (concept, difficulty) to minimize LLM roundtrips.
        Normalizes and validates every question. Returns build_report.
        Enforces >= 60% acceptance threshold (with 1 retry of shortfall groups).
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

        if not self.llm_available:
            unavail = self._unavailable_quiz(main_concept, main_difficulty, {})
            unavail["build_report"] = {
                "requested": requested_count,
                "accepted": 0,
                "rejected_by_reason": {"llm_unavailable": requested_count},
                "groups": len(groups),
                "latency_ms": 0.0,
                "models": [],
            }
            return unavail

        def _generate_group(grp, count_override=None):
            grp_concept = grp["concept"]
            grp_diff = grp["difficulty"]
            grp_count = count_override if count_override is not None else grp["count"]
            grp_mids = grp["target_misconceptions"]
            grp_qtypes = grp["qtypes"][:grp_count]
            if len(grp_qtypes) < grp_count:
                grp_qtypes = (grp_qtypes + ["concept"] * grp_count)[:grp_count]

            # 1. Retrieve lesson passages (max 3)
            lesson_brief = {
                "concept": grp_concept,
                "difficulty": grp_diff,
                "mode": "lesson",
                "top_k": 3,
                "student_id": student_id,
            }
            lesson_ret = self._retrieve(lesson_brief) if self.retriever else {}
            context = lesson_ret.get("context", "")
            if lesson_ret.get("citations"):
                all_citations.extend(lesson_ret["citations"])
            nonlocal first_trace
            if first_trace is None and lesson_ret.get("trace"):
                first_trace = lesson_ret["trace"]

            # 2. Retrieve reference questions (k=3)
            ref_questions = (
                self.retriever.retrieve_reference_questions(grp_concept, grp_diff, k=3)
                if self.retriever else []
            )
            ref_ids = [
                r.get("question_id") or r.get("chunk_id")
                for r in ref_questions
                if (r.get("question_id") or r.get("chunk_id"))
            ]

            # 3. Assemble prompt
            meta = CONCEPTS.get(grp_concept, {})
            title = meta.get("title", concept_title(grp_concept))
            summary = meta.get("summary", "")

            system_prompt = (
                "You are an expert Java / OOP exam author and diagnostic assessment designer.\n"
                "Your role is to write rigorous multiple-choice questions targeting specific student misconceptions.\n"
                "Output strictly a single valid JSON object and nothing else."
            )

            user_parts = [
                "Generate {} multiple-choice question(s) for Java / OOP concept '{}' ({}) at {} difficulty.".format(
                    grp_count, grp_concept, title, grp_diff
                ),
                "",
                "Concept Summary: {}".format(summary),
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
                    user_parts.append("Example {}: {}".format(idx, rq_text))
                    if rq_opts and isinstance(rq_opts, list):
                        for oi, opt in enumerate(rq_opts):
                            user_parts.append("  ({}) {}".format(oi, opt))

            if grp_mids:
                user_parts += ["", "TARGET MISCONCEPTIONS:"]
                for mid in grp_mids:
                    m_item = MISCONCEPTIONS.get(mid, {})
                    wb = m_item.get("wrong_belief", "")
                    ci = m_item.get("correct_idea", "")
                    user_parts.append("- ID: {}".format(mid))
                    if wb:
                        user_parts.append("  Wrong Belief: {}".format(wb))
                    if ci:
                        user_parts.append("  Correct Idea: {}".format(ci))

            user_parts += [
                "",
                "REQUESTED QUESTIONS PER TYPE:",
                "Write {} question(s) with these respective question types (qtype): {}.".format(
                    grp_count, ", ".join(grp_qtypes)
                ),
                "- 'concept': conceptual understanding question",
                "- 'code_output': snippet provided, asks what the code prints or returns (must contain ```java fence)",
                "- 'bug_find': snippet provided, asks what bug / compile error / exception occurs (must contain ```java fence)",
                "",
                "RULES:",
                "1. Exactly one option is correct (correct: integer 0-3).",
                "2. Each wrong option must be the plausible answer a student holding one target misconception would really pick.",
                "3. For each wrong option, set 'misconception_id' to that misconception's exact ID from the TARGET MISCONCEPTIONS list.",
                "4. Use ONLY the listed misconception IDs. At most one wrong option may have 'misconception_id': null.",
                "5. The correct option's 'misconception_id' MUST be null.",
                "6. Keep all 4 options similar in length and complexity.",
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

            data = self._call_llm(system_prompt, "\n".join(user_parts))
            if getattr(self, "last_model_used", None):
                models_used.append(self.last_model_used)

            group_accepted = []
            if data and isinstance(data.get("questions"), list):
                for raw_q in data["questions"]:
                    if not isinstance(raw_q, dict):
                        rejected_by_reason["malformed_item"] += 1
                        continue
                    raw_q["reference_ids"] = ref_ids
                    record, reject_reason = normalize_question(raw_q, grp_concept, grp_diff)
                    if record:
                        group_accepted.append(record)
                    else:
                        rejected_by_reason[reject_reason or "unknown"] += 1

            return group_accepted

        # First pass across all groups
        group_results = {}
        for g_idx, grp in enumerate(groups):
            res = _generate_group(grp)
            group_results[g_idx] = res
            accepted_questions.extend(res)

        # Retry shortfall groups once if accepted < 60% of requested
        if len(accepted_questions) < 0.60 * requested_count:
            self._emit("Accepted {}/{} questions (< 60%); retrying shortfall groups".format(
                len(accepted_questions), requested_count), "warning")
            for g_idx, grp in enumerate(groups):
                shortfall = grp["count"] - len(group_results[g_idx])
                if shortfall > 0:
                    retry_res = _generate_group(grp, count_override=shortfall)
                    group_results[g_idx].extend(retry_res)
                    accepted_questions.extend(retry_res)

        total_latency_ms = round((time.time() - t0) * 1000.0, 2)
        build_report = {
            "requested": requested_count,
            "accepted": len(accepted_questions),
            "rejected_by_reason": dict(rejected_by_reason),
            "groups": len(groups),
            "latency_ms": total_latency_ms,
            "models": sorted(list(set(models_used))) if models_used else ([self.model] if self.llm_available else []),
        }

        # Final 60% threshold check
        if len(accepted_questions) < 0.60 * requested_count:
            err = (
                "Generated quiz quality threshold not met: only {}/{} questions accepted ({:.1f}% < 60%).".format(
                    len(accepted_questions), requested_count,
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

    def _call_llm(self, system_prompt, user_prompt):
        """Try primary model, then fallback model. Returns a parsed dict or None."""
        models_to_try = [self.model, self.fallback_model]
        if len(models_to_try) > 1 and models_to_try[0] == models_to_try[1]:
            models_to_try = [models_to_try[0]]

        for attempt, model in enumerate(models_to_try):
            temperature = 0.6 if attempt == 0 else 0.4
            raw = None
            t0 = time.time()
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    max_tokens=4000,
                )
                raw = response.choices[0].message.content or ""
                lat_ms = int((time.time() - t0) * 1000)
                ptoks = getattr(response.usage, "prompt_tokens", None) if getattr(response, "usage", None) else None
                ctoks = getattr(response.usage, "completion_tokens", None) if getattr(response, "usage", None) else None
                record_llm_call(None, "concept_clarifier", "generate", model, lat_ms, True, None, ptoks, ctoks)
            except Exception as exc:                               # noqa: BLE001
                lat_ms = int((time.time() - t0) * 1000)
                record_llm_call(None, "concept_clarifier", "generate", model, lat_ms, False, str(exc))
                status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if status_code == 401 or "401" in str(exc):
                    self.last_error = "Invalid API key (HTTP 401): {}".format(exc)
                    self._emit(self.last_error, "error")
                    return None

                err_text = str(exc).lower()
                if "response_format" in err_text or "json_object" in err_text or "json mode" in err_text:
                    self._emit(
                        "Model '{}' rejected json_object response_format; retrying without it".format(model),
                        "info",
                    )
                    t_retry = time.time()
                    try:
                        response = self.client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=temperature,
                            max_tokens=4000,
                        )
                        raw = response.choices[0].message.content or ""
                        lat_retry = int((time.time() - t_retry) * 1000)
                        ptoks = getattr(response.usage, "prompt_tokens", None) if getattr(response, "usage", None) else None
                        ctoks = getattr(response.usage, "completion_tokens", None) if getattr(response, "usage", None) else None
                        record_llm_call(None, "concept_clarifier", "generate_retry", model, lat_retry, True, None, ptoks, ctoks)
                    except Exception as retry_exc:                 # noqa: BLE001
                        lat_retry = int((time.time() - t_retry) * 1000)
                        record_llm_call(None, "concept_clarifier", "generate_retry", model, lat_retry, False, str(retry_exc))
                        retry_status = getattr(retry_exc, "status_code", None) or getattr(retry_exc, "code", None)
                        if retry_status == 401 or "401" in str(retry_exc):
                            self.last_error = "Invalid API key (HTTP 401): {}".format(retry_exc)
                            self._emit(self.last_error, "error")
                            return None
                        self.last_error = "Model '{}' failed retry without response_format: {}".format(model, retry_exc)
                        self._emit(self.last_error, "warning")
                        continue
                else:
                    self.last_error = "LLM call failed on '{}': {}".format(model, exc)
                    self._emit(self.last_error, "warning")
                    continue

            data = _parse_json(raw)
            if data:
                self.last_error = None
                self.last_model_used = model
                if attempt > 0:
                    self._emit("Primary model failed; fallback model '{}' answered".format(model), "warning")
                return data
            else:
                self.last_error = "Model '{}' returned invalid JSON".format(model)
                self._emit(self.last_error, "warning")

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
