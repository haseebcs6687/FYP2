"""
=============================================================================
EduGen - Adaptive Content Agent  (FYP-2)
=============================================================================
Agent type : Deterministic pedagogical policy engine
Role       : Decide WHAT to teach next and HOW HARD it should be, then write
             the retrieval brief that the Concept Clarifier will use.

Where this sits in the pipeline
-------------------------------
    Performance Analysis  --(weakness report)-->  ADAPTIVE CONTENT
    ADAPTIVE CONTENT      --(retrieval brief)-->  Concept Clarifier --> RAG + LLM

The retrieval brief is the important part and the thing that was missing in
FYP-1. The Concept Clarifier is not asked a vague question like "teach
inheritance". It is handed a precise instruction object:

    concept, difficulty, mode, query terms, concept tags, focus notes,
    and the student's actual misconceptions

so the RAG search and the LLM prompt are both targeted at the exact gap the
analysis found.

Decision policy (checked in order, first match wins)
----------------------------------------------------
 R1  no history                    -> first_lesson at the entry concept, Easy
 R2  a weak concept has a weak
     prerequisite                  -> remediate the PREREQUISITE (root cause)
 R3  a weak concept, no bad prereq -> revisit it; difficulty scales with mastery
 R4  a mastered concept has gone
     stale (> 7 days)              -> review it at one level up
 R5  moderate concepts remain      -> reinforce the weakest moderate one
 R6  everything strong             -> advance to the next unseen concept in
                                      teaching order, difficulty from overall

Every decision carries `reasoning` written for the student, and `evidence`
written for the examiner. The student can always override - the override is
recorded so FYP-2 evaluation can report how often students trusted the agent.
=============================================================================
"""

from core.concepts import (
    CONCEPTS,
    DIFFICULTIES,
    ENTRY_CONCEPT,
    LEARNING_ORDER,
    concept_title,
    module_of,
    module_title,
    prerequisites_of,
)

EASY_CEILING = 35.0      # mastery under this  -> drop to Easy
HARD_FLOOR = 80.0        # overall over this   -> allow Hard
ADVANCE_OVERALL = 80.0


class AdaptiveContentAgent(object):

    def __init__(self, log=None):
        self.log = log
        print("[Adaptive Agent] Pedagogical policy engine initialised (6 rules, graph-aware).")

    def _emit(self, message, level="info", payload=None):
        if self.log:
            self.log("Adaptive Content", message, level, payload)

    # ─────────────────────────────────────────────────────────
    def decide(self, analysis, mode="lesson"):
        """analysis: the Performance Analysis Agent report. Returns a decision dict."""
        if not isinstance(analysis, dict):
            analysis = {}

        rec = analysis.get("recommendation_input", {}) or {}
        weak = analysis.get("weak_topics", []) or []
        moderate = analysis.get("moderate_topics", []) or []
        strong = analysis.get("strong_topics", []) or []
        root_causes = analysis.get("root_causes", []) or []
        due = analysis.get("due_for_review", []) or []
        stats = analysis.get("concept_stats", {}) or {}
        overall = float(rec.get("overall_performance", analysis.get("overall_performance", 0.0)) or 0.0)
        quizzes = int(analysis.get("total_quizzes_taken", 0) or 0)

        decision = self._apply_rules(
            quizzes=quizzes, weak=weak, moderate=moderate, strong=strong,
            root_causes=root_causes, due=due, stats=stats, overall=overall,
        )

        decision["alternatives"] = self._alternatives(decision["focus_concept"], weak, moderate, stats)
        decision["retrieval_brief"] = self._build_brief(decision, stats, mode)
        decision["module"] = module_of(decision["focus_concept"])
        decision["module_title"] = module_title(decision["module"])
        decision["focus_title"] = concept_title(decision["focus_concept"])

        self._emit(
            "Rule {} fired -> teach '{}' at {} ({})".format(
                decision["rule"], decision["focus_title"],
                decision["recommended_difficulty"], decision["action"]),
            "success",
            {"rule": decision["rule"], "concept": decision["focus_concept"]},
        )
        return decision

    # ─────────────────────────────────────────────────────────
    def _apply_rules(self, quizzes, weak, moderate, strong, root_causes, due, stats, overall):

        # ── R1: brand-new student ────────────────────────────
        if quizzes == 0 and not (weak or moderate or strong):
            return self._decision(
                rule="R1",
                concept=ENTRY_CONCEPT,
                difficulty="Easy",
                action="first_lesson",
                reasoning=(
                    "You have not taken a quiz yet, so we start at the beginning with "
                    "{} on Easy. One quiz is enough for the system to start adapting."
                ).format(concept_title(ENTRY_CONCEPT)),
                evidence={"quizzes_taken": 0},
            )

        # ── R2: fix the prerequisite, not the symptom ────────
        if root_causes:
            cause = root_causes[0]
            target = cause["teach_first"]
            mastery = (stats.get(target) or {}).get("mastery")
            difficulty = "Easy" if (mastery is None or mastery < EASY_CEILING) else "Medium"
            return self._decision(
                rule="R2",
                concept=target,
                difficulty=difficulty,
                action="remediate_prerequisite",
                reasoning=(
                    "You are struggling with {} ({}% mastery), but {} is a prerequisite for it "
                    "and is not solid yet. Fixing the foundation first is faster than repeating "
                    "the harder topic."
                ).format(cause["symptom_title"], cause["symptom_mastery"], cause["teach_first_title"]),
                evidence={
                    "symptom": cause["symptom"],
                    "symptom_mastery": cause["symptom_mastery"],
                    "weak_prerequisites": cause["weak_prerequisites"],
                },
                related=[cause["symptom"]],
            )

        # ── R3: plain weakness ───────────────────────────────
        if weak:
            target = weak[0]
            tag = target["concept_tag"]
            mastery = target.get("mastery", target.get("accuracy", 0.0))
            trend = target.get("trend", "new")

            if mastery < EASY_CEILING:
                difficulty = "Easy"
            elif trend == "improving":
                difficulty = "Medium"
            else:
                difficulty = "Easy" if mastery < WEAK_MIDPOINT else "Medium"

            reason = (
                "{} is your weakest concept right now - {}% mastery over {} question(s). "
                "We will work on it at {} difficulty."
            ).format(target.get("title", concept_title(tag)), mastery, target.get("attempts", 0), difficulty)
            if trend == "improving":
                reason += " Your recent answers are trending upward, so the level is being held rather than dropped."
            elif trend == "declining":
                reason += " Recent answers have slipped, so we are stepping back to rebuild it."

            return self._decision(
                rule="R3", concept=tag, difficulty=difficulty, action="revisit",
                reasoning=reason,
                evidence={"mastery": mastery, "attempts": target.get("attempts"),
                          "trend": trend, "misconceptions": target.get("misconceptions", [])},
            )

        # ── R4: spaced repetition ────────────────────────────
        if due:
            item = due[0]
            tag = item["concept_tag"]
            difficulty = _step_up((stats.get(tag) or {}).get("difficulty_hint", "Medium"))
            return self._decision(
                rule="R4", concept=tag, difficulty=difficulty, action="review",
                reasoning=(
                    "You mastered {} but have not touched it in {} days. A short review at {} "
                    "keeps it from fading."
                ).format(item["title"], item["days_since"], difficulty),
                evidence={"days_since": item["days_since"], "mastery": item["mastery"]},
            )

        # ── R5: consolidate the middle ───────────────────────
        if moderate:
            target = moderate[0]
            tag = target["concept_tag"]
            mastery = target.get("mastery", 0.0)
            difficulty = "Medium" if mastery < 70 else "Hard"
            return self._decision(
                rule="R5", concept=tag, difficulty=difficulty, action="reinforce",
                reasoning=(
                    "Nothing is failing, but {} is only at {}% mastery. Consolidating it at {} "
                    "before moving on gives you a cleaner base."
                ).format(target.get("title", concept_title(tag)), mastery, difficulty),
                evidence={"mastery": mastery, "attempts": target.get("attempts")},
            )

        # ── R6: advance ──────────────────────────────────────
        seen = set(stats.keys())
        next_concept = next((t for t in LEARNING_ORDER if t not in seen), ENTRY_CONCEPT)
        difficulty = "Hard" if overall >= ADVANCE_OVERALL else "Medium"
        return self._decision(
            rule="R6", concept=next_concept, difficulty=difficulty, action="advance",
            reasoning=(
                "Every concept you have been tested on is solid (overall {}%). Moving forward to "
                "{}, a concept you have not seen yet, at {} difficulty."
            ).format(overall, concept_title(next_concept), difficulty),
            evidence={"overall": overall, "concepts_mastered": len(strong)},
        )

    # ─────────────────────────────────────────────────────────
    def _decision(self, rule, concept, difficulty, action, reasoning, evidence=None, related=None):
        if concept not in CONCEPTS:
            concept = ENTRY_CONCEPT
        if difficulty not in DIFFICULTIES:
            difficulty = "Easy"
        return {
            "rule": rule,
            "focus_concept": concept,
            "recommended_difficulty": difficulty,
            "action": action,
            "reasoning": reasoning,
            "evidence": evidence or {},
            "related_concepts": related or [],
        }

    # ─────────────────────────────────────────────────────────
    def _alternatives(self, chosen, weak, moderate, stats):
        """Two or three other defensible choices, shown on the override screen."""
        out, seen = [], {chosen}
        for bucket, label in ((weak, "still weak"), (moderate, "needs consolidation")):
            for entry in bucket:
                tag = entry["concept_tag"]
                if tag in seen:
                    continue
                seen.add(tag)
                out.append({
                    "concept": tag,
                    "title": entry.get("title", concept_title(tag)),
                    "why": "{} - {}% mastery".format(label, entry.get("mastery", 0)),
                })
                if len(out) >= 3:
                    return out

        for tag in prerequisites_of(chosen):
            if tag in seen:
                continue
            seen.add(tag)
            out.append({
                "concept": tag,
                "title": concept_title(tag),
                "why": "prerequisite of {}".format(concept_title(chosen)),
            })
            if len(out) >= 3:
                break
        return out

    # ─────────────────────────────────────────────────────────
    def _build_brief(self, decision, stats, mode):
        """
        The instruction object handed to the Concept Clarifier Agent.
        Built here (not inside the Clarifier) because choosing WHAT to look up
        is a pedagogical decision, and pedagogy is this agent's job.
        """
        concept = decision["focus_concept"]
        meta = CONCEPTS.get(concept, {})
        stat = stats.get(concept, {})

        focus_notes = []
        related_stats = [stat]

        if decision["action"] == "remediate_prerequisite":
            symptom = decision["evidence"].get("symptom")
            if symptom:
                focus_notes.append(
                    "Explain {} in a way that prepares the student for {}.".format(
                        concept_title(concept), concept_title(symptom))
                )
                # the symptom's misconceptions are the gap we are really closing,
                # so they travel with the brief even though we teach the prerequisite
                if stats.get(symptom):
                    related_stats.append(stats[symptom])

        seen_answers = set()
        for source in related_stats:
            for miss in (source.get("misconceptions") or [])[:2]:
                if miss["answer"] in seen_answers:
                    continue
                seen_answers.add(miss["answer"])
                focus_notes.append(
                    "The student repeatedly chose: \"{}\" - correct that directly.".format(
                        miss["answer"]))
        if stat.get("fragile"):
            focus_notes.append("The student answers this correctly but slowly - emphasise the quick mental model.")
        if decision["action"] == "review":
            focus_notes.append("This is a refresher, not a first exposure - be brisk and lead with the trickiest part.")

        tags = [concept] + [t for t in prerequisites_of(concept)][:2]
        query_terms = [
            meta.get("title", concept.replace("-", " ")),
            meta.get("summary", ""),
            " ".join(meta.get("keywords", [])),
        ]

        return {
            "concept": concept,
            "concept_title": concept_title(concept),
            "difficulty": decision["recommended_difficulty"],
            "mode": mode,
            "query": " ".join(q for q in query_terms if q).strip(),
            "concept_tags": tags,
            "focus_notes": focus_notes,
            "top_k": 6 if mode == "lesson" else 5,
            "issued_by": "Adaptive Content Agent",
            "rule": decision["rule"],
        }


WEAK_MIDPOINT = 42.0


def _step_up(difficulty):
    order = {"Easy": "Medium", "Medium": "Hard", "Hard": "Hard"}
    return order.get(difficulty, "Medium")
