# EduGen Question Format (Canonical Record)

This document specifies the canonical question format for EduGen's curated and generated question bank. Question files are stored as **JSON Lines** (`.jsonl`), with exactly one question object per line.

---

## Schema Overview

Each question record is a valid JSON object matching the following structure:

```json
{
  "concept": "<concept-tag>",
  "difficulty": "Easy|Medium|Hard",
  "qtype": "concept|code_output|bug_find",
  "question": "<question text; Java code enclosed in ```java fences>",
  "options": [
    {"text": "<option text>", "misconception_id": null},
    {"text": "<option text>", "misconception_id": "<concept-tag>/<slug>"},
    {"text": "<option text>", "misconception_id": "<concept-tag>/<slug>"},
    {"text": "<option text>", "misconception_id": "<concept-tag>/<slug>"}
  ],
  "correct_index": 0,
  "explanation": "<explanation of correct answer and why the distractors are incorrect>",
  "source": {
    "pdf": "<source book or document name, e.g., 'think_java.pdf'>",
    "page": "<page number or chapter name, e.g., '142' or 'Chapter 7'>"
  }
}
```

---

## Field Specifications

| Field | Type | Required | Constraints & Description |
| :--- | :--- | :---: | :--- |
| `concept` | string | Yes | Must match one of the 44 canonical tags defined in `core/concepts.py` (e.g. `classes-objects`, `method-overriding`). |
| `difficulty` | string | Yes | Allowed values: `"Easy"`, `"Medium"`, `"Hard"`. |
| `qtype` | string | Yes | Allowed values: `"concept"`, `"code_output"`, `"bug_find"`. |
| `question` | string | Yes | Non-empty string. Java code snippets must be wrapped in markdown code fences (` ```java ... ``` `). All markdown code fences must be properly closed/balanced. Minimum 15 characters. |
| `options` | array | Yes | Array of **exactly 4** option objects. All 4 option `text` strings must be non-empty and pairwise distinct. |
| `options[].text` | string | Yes | The textual display for the option. |
| `options[].misconception_id` | string or null | Yes | `null` for the correct answer. For distractors, must be a valid misconception ID from `core/misconceptions.py` belonging to this question's `concept`. At most one distractor may have `null` for a pure careless/unrelated distractor. |
| `correct_index` | integer | Yes | Integer `0`, `1`, `2`, or `3` indicating the zero-based index of the correct option in `options`. |
| `explanation` | string | Yes | Non-empty string explaining why the correct option is right and addressing the primary distractor misconception. |
| `source` | object | Yes | Object containing provenance metadata (`pdf` string and `page` string/number). |
| `source.pdf` | string | Yes | File name or identifier of the source material. |
| `source.page` | string or int | Yes | Page number or chapter reference in the source. |

---

## Pedagogical & Structural Rules

1. **Exactly One Correct Option:**
   - The option at index `correct_index` must have `"misconception_id": null`.
   - The other 3 options are incorrect distractors.
2. **Misconception Catalog Grounding:**
   - Every wrong option must either reference a valid misconception ID registered for this question's `concept` in `core/misconceptions.py`, or be `null` (permitted for at most **one** careless or unrelated distractor per question).
   - When the concept's catalog has 3 or more misconceptions, the wrong options should map to **distinct** misconceptions (no two wrong options should target the same misconception ID in the same question).
3. **No Duplicate Options:**
   - All four option `text` values must be unique after trimming whitespace.
4. **Code Syntax & Compilability:**
   - Unless `qtype == "bug_find"` (where intentional compile errors are the subject of assessment), all embedded Java code must be syntactically valid and compile without errors.
   - Code fences must use ```` ```java ```` and ```` ``` ````.
5. **Deduplication Constraints:**
   - Questions in the corpus are checked for duplicate text:
     - Exact duplicate: matching normalized SHA-256 text hash.
     - Near-duplicate: token Jaccard similarity $\ge 0.85$ among questions sharing the same `concept`.

---

## Complete Example

```json
{
  "concept": "method-overriding",
  "difficulty": "Medium",
  "qtype": "code_output",
  "question": "What is printed when this program runs?\n```java\nclass Parent {\n    static void display() {\n        System.out.print(\"Parent \");\n    }\n}\nclass Child extends Parent {\n    static void display() {\n        System.out.print(\"Child \");\n    }\n}\npublic class Main {\n    public static void main(String[] args) {\n        Parent obj = new Child();\n        obj.display();\n    }\n}\n```",
  "options": [
    {
      "text": "Parent ",
      "misconception_id": null
    },
    {
      "text": "Child ",
      "misconception_id": "method-overriding/static-methods-override"
    },
    {
      "text": "Compilation error because static methods cannot have the same name in subclasses",
      "misconception_id": "method-overriding/overriding-requires-annotations"
    },
    {
      "text": "Child Parent ",
      "misconception_id": "method-overriding/super-keyword-automatic"
    }
  ],
  "correct_index": 0,
  "explanation": "Static methods are resolved at compile-time based on the declared reference type (Parent), not the runtime instance type. This is method hiding, not method overriding. Option 'Child ' reflects the common misconception that static methods participate in runtime polymorphism.",
  "source": {
    "pdf": "core_java_fundamentals.pdf",
    "page": "184"
  }
}
```
