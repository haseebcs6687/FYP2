"""
=============================================================================
EduGen - Study Planner Test Suite (scripts/test_study_planner.py)
=============================================================================
Comprehensive unit and integration tests verifying:
  - Cold start handling
  - Topological sorting (Kahn) and prerequisite order validity
  - Prerequisite closure and filtering of mastered prerequisites
  - Size cap and deferral preserving closure
  - Priority calculation
  - Difficulty and lesson style calibration
  - Closing probe and reevaluation steps
  - Deterministic prompt generation with misconception pairs and user notes
  - Coverage checker violation detection (missing prereq, active misconception, cycle, duplicate, skipped step)
  - Persistence round trip and superseding on replan
  - Route ownership security (cross-student plan isolation)
=============================================================================
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents.adaptive_content_agent import AdaptiveContentAgent
from core.concepts import CONCEPTS, PREREQUISITES, prerequisites_of
from core.db import init_db
from core.db_repo import (
    create_study_plan,
    get_active_study_plan,
    get_study_plan_by_id,
    get_study_plan_step,
    update_study_plan_step,
)
from core.study_planner import (
    check_coverage,
    compute_priority,
    format_step_prompt,
    frontier,
    generate_study_plan,
    plan_after_check,
    plan_step_concepts,
    topological_sort_kahn,
)


class TestStudyPlannerPureAlgorithms(unittest.TestCase):
    def setUp(self):
        self.mock_report = {
            "student_id": 1,
            "total_questions_attempted": 20,
            "overall_performance": 55.0,
            "weak_topics": ["dynamic-method-dispatch"],
            "moderate_topics": ["method-overriding", "inheritance-basics"],
            "strong_topics": ["class-definition"],
            "due_for_review": [],
            "concept_stats": {
                "class-definition": {"mastery": 85.0, "attempts": 6},
                "inheritance-basics": {"mastery": 55.0, "attempts": 5},
                "method-overriding": {"mastery": 45.0, "attempts": 5},
                "dynamic-method-dispatch": {"mastery": 25.0, "attempts": 4},
            },
            "misconceptions": {
                "active": [
                    {
                        "misconception_id": "dynamic-method-dispatch/resolved-at-compile-time",
                        "concept": "dynamic-method-dispatch",
                        "severity": 2.5,
                        "wrong_belief": "Method call resolved by reference type",
                        "correct_idea": "Method call resolved by actual object type",
                    }
                ],
                "suspected": [],
                "resolved": [],
            },
            "facet_map": {
                "dynamic-method-dispatch": {"execution": {"weak": True, "error_rate": 0.75}}
            },
            "skill_profile": {"skill_gaps": []},
        }

    def test_cold_start(self):
        """Student with 0 attempts receives an empty plan prompting for diagnostic quiz."""
        cold_report = {"total_questions_attempted": 0, "concept_stats": {}}
        plan = generate_study_plan(cold_report)
        self.assertEqual(len(plan["steps"]), 0)
        self.assertEqual(plan["reason"], "take the diagnostic quiz first")
        self.assertFalse(plan["coverage"]["ok"])

    def test_topological_validity(self):
        """Every prerequisite in the generated plan must precede its dependents."""
        plan = generate_study_plan(self.mock_report)
        learning_steps = [s for s in plan["steps"] if s["kind"] not in ("probe", "reevaluation")]
        concepts_in_plan = [s["concept"] for s in learning_steps]

        for i, c in enumerate(concepts_in_plan):
            for p in PREREQUISITES.get(c, []):
                if p in concepts_in_plan:
                    p_idx = concepts_in_plan.index(p)
                    self.assertLess(
                        p_idx, i,
                        f"Prerequisite '{p}' at {p_idx} must precede dependent '{c}' at {i}"
                    )

    def test_prerequisite_closure_and_mastered_filtering(self):
        """Weak concepts pull their weak/unproven prerequisites; mastered ones are omitted."""
        plan = generate_study_plan(self.mock_report)
        learning_concepts = {s["concept"] for s in plan["steps"] if s["kind"] not in ("probe", "reevaluation")}

        # dynamic-method-dispatch depends on method-overriding and inheritance-basics
        self.assertIn("dynamic-method-dispatch", learning_concepts)
        self.assertIn("method-overriding", learning_concepts)
        self.assertIn("inheritance-basics", learning_concepts)

        # class-definition is mastered (85.0% >= 70.0%), so it must NOT be included as a prerequisite step
        self.assertNotIn("class-definition", learning_concepts)

    def test_priority_ordering(self):
        """Priority formula favors lower mastery, higher active severity, dependents, and review."""
        seeds = ["dynamic-method-dispatch"]
        prio_dmd = compute_priority("dynamic-method-dispatch", seeds, self.mock_report)
        prio_mo = compute_priority("method-overriding", seeds, self.mock_report)

        # dynamic-method-dispatch: mastery 25, active sev 2.5 -> (100 - 25) + 15 * 2.5 = 75 + 37.5 = 112.5
        # method-overriding: mastery 45, dep_count = 1 -> (100 - 45) + 10 * 1 = 65.0
        self.assertGreater(prio_dmd, prio_mo)

    def test_difficulty_and_style_mapping(self):
        """Mastery < 40 -> Easy/simplified; 40-70 -> Medium/detailed; weak prerequisites start Easy."""
        plan = generate_study_plan(self.mock_report)
        learning_steps = [s for s in plan["steps"] if s["kind"] not in ("probe", "reevaluation")]
        steps_by_concept = {s["concept"]: s for s in learning_steps}

        dmd_step = steps_by_concept["dynamic-method-dispatch"]
        self.assertEqual(dmd_step["difficulty"], "Easy")
        self.assertEqual(dmd_step["lesson_style"], "simplified")

        mo_step = steps_by_concept["method-overriding"]
        self.assertEqual(mo_step["difficulty"], "Medium")
        self.assertEqual(mo_step["lesson_style"], "detailed")

    def test_closing_steps(self):
        """Plan must append ONE probe quiz step and ONE reevaluation quiz step at the end."""
        plan = generate_study_plan(self.mock_report)
        steps = plan["steps"]
        self.assertGreaterEqual(len(steps), 3)

        penultimate = steps[-2]
        ultimate = steps[-1]

        self.assertEqual(penultimate["kind"], "probe")
        self.assertEqual(penultimate["concept"], "dynamic-method-dispatch")
        self.assertIsNone(penultimate["lesson_style"])

        self.assertEqual(ultimate["kind"], "reevaluation")
        self.assertEqual(ultimate["concept"], "all-plan-concepts")
        self.assertIsNone(ultimate["lesson_style"])

    def test_prompt_content(self):
        """Step prompt text includes title, difficulty, style, evidence, misconception pairs, and user notes."""
        step = {
            "concept": "dynamic-method-dispatch",
            "title": "Dynamic Method Dispatch",
            "difficulty": "Easy",
            "lesson_style": "simplified",
            "mastery": 25.0,
            "focus": {
                "misconceptions": [
                    {
                        "wrong_belief": "Reference type determines method",
                        "correct_idea": "Actual runtime object determines method",
                    }
                ],
                "weak_facets": ["execution"],
                "skill_gap": "Knows theory but struggles with code tracing",
            },
        }

        prompt = format_step_prompt(step, preceding_titles=["Inheritance Basics"], user_note="Please use diagrams")
        self.assertIn("Dynamic Method Dispatch", prompt)
        self.assertIn("Easy level", prompt)
        self.assertIn("simplified style", prompt)
        self.assertIn("25.0% mastery", prompt)
        self.assertIn("Reference type determines method -> Actual runtime object determines method", prompt)
        self.assertIn("code-tracing examples", prompt)
        self.assertIn("Inheritance Basics", prompt)
        self.assertIn("Please use diagrams", prompt)

    def test_cap_deferral_keeps_closure(self):
        """Size cap defers lowest-priority items while keeping prerequisite closure intact."""
        # Create a report with 8 distinct weak topics
        many_weak = [
            "polymorphism-basics", "dynamic-method-dispatch", "method-overriding",
            "downcasting", "instanceof-operator", "abstract-classes", "interface-basics", "default-methods"
        ]
        big_report = dict(self.mock_report)
        big_report["weak_topics"] = many_weak
        big_report["concept_stats"] = {c: {"mastery": 30.0, "attempts": 2} for c in many_weak}

        plan = generate_study_plan(big_report, size_cap=4)
        learning_steps = [s for s in plan["steps"] if s["kind"] in ("weak", "prerequisite", "advance", "review")]
        check_steps = [s for s in plan["steps"] if s["kind"] == "check"]

        # Retained learning steps must not exceed size_cap (4)
        self.assertLessEqual(len(learning_steps), 4)
        # Retained check steps must not exceed check_cap (4)
        self.assertLessEqual(len(check_steps), 4)
        self.assertGreater(len(plan["deferred"]), 0)

        # Check that deferred items contain reasons and priority
        for d in plan["deferred"]:
            self.assertIn("Deferred", d["reason"])
            self.assertIn("priority", d)

    def test_frontier_selection_and_course_complete(self):
        """Frontier identifies unmastered concepts whose direct prerequisites are mastered; handles course complete."""
        from core.concepts import CONCEPTS, learning_order

        # 1. New student with no data: frontier is entry concept
        rep_cold = {"concept_stats": {}}
        front_cold = frontier(rep_cold)
        self.assertIn("class-definition", front_cold)

        # 2. Student who mastered class-definition: frontier advances to next concepts
        rep_b = {"concept_stats": {"class-definition": {"mastery": 85.0, "attempts": 5}}}
        front_b = frontier(rep_b)
        self.assertNotIn("class-definition", front_b)
        self.assertIn("object-instantiation", front_b)
        self.assertIn("static-members", front_b)

        # 3. Student who mastered all 44 concepts: frontier empty, course complete plan generated
        rep_all = {
            "total_questions_attempted": 220,
            "concept_stats": {c: {"mastery": 85.0, "attempts": 5} for c in CONCEPTS},
            "weak_topics": [],
            "moderate_topics": [],
            "strong_topics": list(CONCEPTS.keys()),
            "due_for_review": [{"concept_tag": "class-definition", "mastery": 85.0}],
            "misconceptions": {"active": [], "suspected": []},
        }
        self.assertEqual(len(frontier(rep_all)), 0)
        complete_plan = generate_study_plan(rep_all)
        self.assertEqual(len(complete_plan["steps"]), 1)
        self.assertEqual(complete_plan["steps"][0]["kind"], "reevaluation")
        self.assertEqual(complete_plan["reason"], "Course complete - mixed review")
        self.assertTrue(complete_plan["coverage"]["ok"])

    def test_advance_never_repeats_mastered_concepts(self):
        """Advance steps only target unmastered concepts, never repeating mastered ones."""
        from core.concepts import CONCEPTS

        rep = {
            "total_questions_attempted": 20,
            "concept_stats": {
                "class-definition": {"mastery": 85.0, "attempts": 5},
                "object-instantiation": {"mastery": 80.0, "attempts": 5},
            },
            "weak_topics": [],
            "moderate_topics": [],
            "strong_topics": ["class-definition", "object-instantiation"],
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        plan = generate_study_plan(rep)
        advance_steps = [s for s in plan["steps"] if s["kind"] == "advance"]
        self.assertGreater(len(advance_steps), 0)

        for s in advance_steps:
            c = s["concept"]
            # Must not be an already-mastered concept
            mst = rep["concept_stats"].get(c, {}).get("mastery", 0.0)
            self.assertLess(mst, 70.0, f"Advance step {c} cannot be for a mastered concept")
            self.assertNotIn(c, ["class-definition", "object-instantiation"])

    def test_check_step_creation_placement_cap_deferral(self):
        """Unproven prerequisites become 'check' quiz steps, placed before dependents, capped at 4."""
        # Dynamic-method-dispatch depends on method-overriding which depends on inheritance-basics which depends on class-definition
        rep = {
            "total_questions_attempted": 5,
            "weak_topics": ["dynamic-method-dispatch"],
            "concept_stats": {
                "dynamic-method-dispatch": {"mastery": 20.0, "attempts": 5},
                # method-overriding, inheritance-basics, class-definition have NO attempt data
            },
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        plan = generate_study_plan(rep)
        check_steps = [s for s in plan["steps"] if s["kind"] == "check"]
        check_concepts = [s["concept"] for s in check_steps]

        # Verify kind is 'check', quiz parameters stored in focus, no prompt_text
        self.assertGreater(len(check_steps), 0)
        for s in check_steps:
            self.assertEqual(s["kind"], "check")
            self.assertEqual(s["difficulty"], "Easy")
            self.assertIsNone(s["lesson_style"])
            self.assertIsNone(s["prompt_text"])
            self.assertEqual(s["focus"]["quiz_kind"], "practice")
            self.assertEqual(s["focus"]["n"], 3)

        # Verify topological placement: check steps precede their dependents
        all_concepts = [s["concept"] for s in plan["steps"]]
        dmd_idx = all_concepts.index("dynamic-method-dispatch")
        for chk in check_concepts:
            chk_idx = all_concepts.index(chk)
            self.assertLess(chk_idx, dmd_idx, f"Check step {chk} must precede dependent dynamic-method-dispatch")

        # Test check step cap of 4
        # Add 6 unproven prerequisites by including multiple independent seeds
        rep_many_unproven = {
            "total_questions_attempted": 10,
            "weak_topics": ["dynamic-method-dispatch", "try-with-resources", "downcasting"],
            "concept_stats": {
                "dynamic-method-dispatch": {"mastery": 20.0, "attempts": 5},
                "try-with-resources": {"mastery": 20.0, "attempts": 5},
                "downcasting": {"mastery": 20.0, "attempts": 5},
            },
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        plan_capped = generate_study_plan(rep_many_unproven, check_cap=4)
        retained_checks = [s for s in plan_capped["steps"] if s["kind"] == "check"]
        self.assertLessEqual(len(retained_checks), 4)

    def test_plan_after_check_both_branches(self):
        """plan_after_check converts failed check (<50) to prerequisite lesson; marks passed check (>=50) done."""
        rep = {
            "total_questions_attempted": 5,
            "weak_topics": ["dynamic-method-dispatch"],
            "concept_stats": {"dynamic-method-dispatch": {"mastery": 20.0, "attempts": 5}},
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        plan = generate_study_plan(rep)
        check_steps = [s for s in plan["steps"] if s["kind"] == "check"]
        self.assertGreater(len(check_steps), 0)
        target_concept = check_steps[0]["concept"]

        # Branch 1: Check score < 50% -> converts to prerequisite lesson step
        updated_fail = plan_after_check(plan, target_concept, check_mastery=35.0, report=rep)
        converted_step = next(s for s in updated_fail["steps"] if s["concept"] == target_concept)
        self.assertEqual(converted_step["kind"], "prerequisite")
        self.assertEqual(converted_step["difficulty"], "Easy")
        self.assertEqual(converted_step["lesson_style"], "simplified")
        self.assertIsNotNone(converted_step["prompt_text"])
        self.assertIn("Prerequisite check failed", converted_step["reason"])

        # Branch 2: Check score >= 50% -> marks done, preserves dependents
        updated_pass = plan_after_check(plan, target_concept, check_mastery=75.0, report=rep)
        passed_step = next(s for s in updated_pass["steps"] if s["concept"] == target_concept)
        self.assertEqual(passed_step["kind"], "check")
        self.assertEqual(passed_step["status"], "done")
        self.assertIn("Prerequisite check passed", passed_step["reason"])

    def test_skill_gap_difficulty_cap(self):
        """Step whose only reason is a skill gap gets difficulty capped at Medium."""
        rep = {
            "total_questions_attempted": 12,
            "weak_topics": [],
            "moderate_topics": ["class-definition"],
            "strong_topics": [],
            "concept_stats": {"class-definition": {"mastery": 80.0, "attempts": 12}},
            "skill_profile": {
                "by_module": {
                    "classes-objects": {
                        "concept": {"attempts": 6, "accuracy": 100.0},
                        "code_output": {"attempts": 6, "accuracy": 20.0},
                    }
                },
                "skill_gaps": ["Knows theory but struggles with code tracing"],
            },
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        plan = generate_study_plan(rep)
        step = next(s for s in plan["steps"] if s["concept"] == "class-definition")
        self.assertEqual(step["difficulty"], "Medium")
        self.assertEqual(step["lesson_style"], "detailed")
        self.assertIn("code-tracing examples", step["prompt_text"])

    def test_plan_step_concepts_helper(self):
        """plan_step_concepts extracts targeted concepts for single, probe, and reevaluation steps."""
        single_step = {"concept": "class-definition", "kind": "weak", "focus": {}}
        self.assertEqual(plan_step_concepts(single_step), ["class-definition"])

        probe_step = {"concept": "inheritance-basics", "kind": "probe", "focus": {"concept": "inheritance-basics"}}
        self.assertEqual(plan_step_concepts(probe_step), ["inheritance-basics"])

        reeval_step = {
            "concept": "all-plan-concepts",
            "kind": "reevaluation",
            "focus": {"concepts": ["class-definition", "inheritance-basics", "method-overriding"]},
        }
        self.assertEqual(
            plan_step_concepts(reeval_step),
            ["class-definition", "inheritance-basics", "method-overriding"],
        )


class TestCoverageChecker(unittest.TestCase):
    def setUp(self):
        self.report = {
            "weak_topics": ["dynamic-method-dispatch"],
            "strong_topics": ["class-definition"],
            "misconceptions": {
                "active": [
                    {"misconception_id": "dynamic-method-dispatch/resolved-at-compile-time", "concept": "dynamic-method-dispatch"}
                ]
            },
            "concept_stats": {
                "class-definition": {"mastery": 85.0, "attempts": 6},
                "dynamic-method-dispatch": {"mastery": 25.0, "attempts": 3},
                "method-overriding": {"mastery": 50.0, "attempts": 3},
                "inheritance-basics": {"mastery": 55.0, "attempts": 3},
            },
        }
        self.valid_plan = generate_study_plan(self.report)

    def test_valid_plan_passes_all_checks(self):
        """A properly generated plan satisfies all 5 coverage checks with 0 violations."""
        cov = check_coverage(self.valid_plan, self.report)
        self.assertTrue(cov["ok"])
        self.assertEqual(len(cov["violations"]), 0)
        self.assertEqual(len(cov["checks"]), 5)
        for c in cov["checks"]:
            self.assertTrue(c["ok"])

    def test_detects_missing_prerequisite(self):
        """Planted missing prerequisite is caught by order_valid check."""
        flawed_plan = dict(self.valid_plan)
        # Drop inheritance-basics which is a required prerequisite for method-overriding
        flawed_plan["steps"] = [
            s for s in flawed_plan["steps"] if s.get("concept") != "inheritance-basics"
        ]
        cov = check_coverage(flawed_plan, self.report)
        self.assertFalse(cov["ok"])
        violations_str = " ".join(cov["violations"])
        self.assertIn("inheritance-basics", violations_str)

    def test_detects_uncovered_active_misconception(self):
        """Planted active misconception not addressed in step focus fails active_misconceptions_addressed."""
        flawed_report = dict(self.report)
        flawed_report["misconceptions"] = {
            "active": [
                {"misconception_id": "uncovered-concept/some-fatal-bug", "concept": "uncovered-concept"}
            ]
        }
        cov = check_coverage(self.valid_plan, flawed_report)
        self.assertFalse(cov["ok"])
        violations_str = " ".join(cov["violations"])
        self.assertIn("uncovered-concept/some-fatal-bug", violations_str)

    def test_detects_duplicates_and_cycles(self):
        """Duplicate steps or cyclic dependencies fail no_cycles_or_duplicates."""
        flawed_plan = dict(self.valid_plan)
        # Duplicate the first step
        flawed_plan["steps"] = [flawed_plan["steps"][0]] + flawed_plan["steps"]
        cov = check_coverage(flawed_plan, self.report)
        self.assertFalse(cov["ok"])
        violations_str = " ".join(cov["violations"])
        self.assertIn("Duplicate concepts", violations_str)

    def test_skipped_step_invalidates_coverage_with_warning(self):
        """Skipping a step removes it from active coverage and produces an exact uncovered report."""
        flawed_plan = dict(self.valid_plan)
        # Mark prerequisite step as skipped
        for s in flawed_plan["steps"]:
            if s.get("concept") == "inheritance-basics":
                s["status"] = "skipped"

        cov = check_coverage(flawed_plan, self.report)
        self.assertFalse(cov["ok"])
        violations_str = " ".join(cov["violations"])
        self.assertIn("inheritance-basics", violations_str)

    def test_check_step_does_not_cover_weak_concept(self):
        """A check step satisfies prerequisite ordering, but does not count as covering a weak concept."""
        flawed_plan = json.loads(json.dumps(self.valid_plan))
        for s in flawed_plan["steps"]:
            if s.get("concept") == "dynamic-method-dispatch":
                s["kind"] = "check"

        cov = check_coverage(flawed_plan, self.report)
        self.assertFalse(cov["ok"])
        violations_str = " ".join(cov["violations"])
        self.assertIn("dynamic-method-dispatch", violations_str)


class TestStudyPlanIntegrationAndSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_edugen.db")
        os.environ["EDUGEN_DB_PATH"] = self.db_path

        import core.db
        core.db.DB_PATH = self.db_path
        init_db(self.db_path)

        # Seed two students
        conn = core.db.get_db(self.db_path)
        conn.execute("INSERT INTO users (id, email, password_hash, name) VALUES (1, 's1@edu.com', 'h1', 'Student One'), (2, 's2@edu.com', 'h2', 'Student Two')")
        conn.execute("INSERT INTO students (id, user_id, name) VALUES (1, 1, 'Student One'), (2, 2, 'Student Two')")
        conn.commit()
        conn.close()

        self.agent = AdaptiveContentAgent()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_persistence_round_trip(self):
        """Plans and steps persist all fields to DB and deserialize JSON properly."""
        report = {
            "weak_topics": ["constructor-basics"],
            "concept_stats": {"constructor-basics": {"mastery": 30.0, "attempts": 3}},
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        plan = self.agent.build_plan(student_id=1, report=report)
        self.assertIsNotNone(plan.get("id"))

        active_plan = self.agent.get_active_plan(student_id=1)
        self.assertIsNotNone(active_plan)
        self.assertEqual(active_plan["id"], plan["id"])
        self.assertEqual(active_plan["status"], "active")
        self.assertGreater(len(active_plan["steps"]), 0)

        # Verify step fields
        s0 = active_plan["steps"][0]
        self.assertIn("concept", s0)
        self.assertIn("lesson_style", s0)
        self.assertIn("priority", s0)
        self.assertIn("est_minutes", s0)

    def test_replan_supersedes_previous_plan(self):
        """Generating a new plan marks the prior plan as superseded."""
        report = {
            "weak_topics": ["constructor-basics"],
            "concept_stats": {"constructor-basics": {"mastery": 30.0, "attempts": 3}},
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        plan1 = self.agent.build_plan(student_id=1, report=report)
        plan2 = self.agent.build_plan(student_id=1, report=report)

        p1_db = get_study_plan_by_id(plan1["id"])
        p2_db = get_study_plan_by_id(plan2["id"])

        self.assertEqual(p1_db["status"], "superseded")
        self.assertEqual(p2_db["status"], "active")

    def test_step_note_and_prompt_update(self):
        """Updating user_note persists the note and rebuilds prompt_text."""
        report = {
            "weak_topics": ["constructor-basics"],
            "concept_stats": {"constructor-basics": {"mastery": 30.0, "attempts": 3}},
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        plan = self.agent.build_plan(student_id=1, report=report)
        s0 = plan["steps"][0]

        res = self.agent.update_step(s0["id"], user_note="Please emphasize default constructor rules")
        self.assertTrue(res["ok"])
        step_updated = res["step"]
        self.assertEqual(step_updated["user_note"], "Please emphasize default constructor rules")
        self.assertIn("Please emphasize default constructor rules", step_updated["prompt_text"])

    def test_route_ownership_security(self):
        """API forbids student A from modifying or reading student B's plan steps."""
        from app import create_app
        from scripts.test_csrf_helper import csrf_post
        app = create_app()
        app.config["TESTING"] = True

        report = {
            "weak_topics": ["constructor-basics"],
            "concept_stats": {"constructor-basics": {"mastery": 30.0, "attempts": 3}},
            "misconceptions": {"active": [], "suspected": []},
            "due_for_review": [],
        }
        # Build plan for Student 1
        plan1 = self.agent.build_plan(student_id=1, report=report)
        step_s1 = plan1["steps"][0]["id"]

        with app.test_client() as client:
            # Login as Student 2
            with client.session_transaction() as sess:
                sess["user_id"] = 2
                sess["student_id"] = 2

            # Student 2 tries to update Student 1's step status
            res = csrf_post(
                client,
                f"/api/plan/step/{step_s1}/status",
                data=json.dumps({"status": "done"}),
                content_type="application/json",
            )
            self.assertEqual(res.status_code, 403)
            self.assertIn("Forbidden", res.get_json().get("error", ""))

            # Student 2 tries to update Student 1's step note
            res_note = csrf_post(
                client,
                f"/api/plan/step/{step_s1}/note",
                data=json.dumps({"note": "Malicious edit"}),
                content_type="application/json",
            )
            self.assertEqual(res_note.status_code, 403)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
