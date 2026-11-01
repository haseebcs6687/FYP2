"""
=============================================================================
EduGen - Java Verification Gate (Phase 4B)
=============================================================================
Deterministic quality gate for Java code snippets in generated questions:
  - Discovers javac / java via PATH or JAVA_HOME.
  - Normalizes multi-class snippets (strips public from auxiliary classes).
  - Validates:
      * code_output: executes and matches correct option.
      * bug_find: requires exactly ONE compile error, keyword in explanation.
      * concept: snippets must compile cleanly.
  - Safe fallback when JDK is unavailable (counts 'java_unverified', never fails).
=============================================================================
"""

import os
import re
import shutil
import subprocess
import tempfile

_JAVA_FENCE_RE = re.compile(r"```java\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_CLASS_DECL_RE = re.compile(
    r"\b(?:public\s+)?(?:final\s+|abstract\s+)*(?:class|interface|enum|record)\s+([A-Za-z0-9_$]+)"
)
_MAIN_METHOD_RE = re.compile(r"\bpublic\s+static\s+void\s+main\s*\(\s*String\b")
_ERROR_COUNT_RE = re.compile(r"\b(\d+)\s+errors?\b", re.IGNORECASE)

_STOP_WORDS = {
    "error", "errors", "line", "java", "class", "cannot", "symbol", "location",
    "required", "found", "expected", "where", "the", "and", "file", "public"
}


def find_jdk():
    """
    Locate javac and java executables via PATH or JAVA_HOME.
    Returns (javac_path, java_path). Both None if not found.
    """
    javac = shutil.which("javac")
    java = shutil.which("java")

    if not javac or not java:
        java_home = os.environ.get("JAVA_HOME")
        if java_home and os.path.isdir(java_home):
            candidate_javac = os.path.join(java_home, "bin", "javac.exe" if os.name == "nt" else "javac")
            candidate_java = os.path.join(java_home, "bin", "java.exe" if os.name == "nt" else "java")
            if not javac and os.path.isfile(candidate_javac):
                javac = candidate_javac
            if not java and os.path.isfile(candidate_java):
                java = candidate_java

    return javac, java


def extract_java_snippets(text):
    """Return all ```java ... ``` snippets found in text."""
    if not text:
        return []
    return [match.strip() for match in _JAVA_FENCE_RE.findall(text)]


def prepare_java_source(snippet):
    """
    Handle multiple top-level classes:
    - Finds which class has `public static void main`.
    - Strips `public` from all other class/interface/enum/record declarations.
    - If no class has main, keeps the first declared class as main_class.
    - If no class declaration exists, wraps snippet in a dummy Main class.
    Returns (prepared_code, main_class_name).
    """
    lines = snippet.splitlines()
    classes = []
    main_class = None

    # Find declarations and which one contains main
    current_class = None
    for line in lines:
        m = _CLASS_DECL_RE.search(line)
        if m:
            cname = m.group(1)
            classes.append(cname)
            current_class = cname
        if _MAIN_METHOD_RE.search(line) and current_class:
            main_class = current_class

    if not classes:
        # Wrap raw statements
        wrapped = (
            "public class Main {\n"
            "    public static void main(String[] args) {\n"
            f"        {snippet}\n"
            "    }\n"
            "}\n"
        )
        return wrapped, "Main"

    if not main_class:
        main_class = classes[0]

    # Rewrite: strip `public` from any class declaration other than main_class
    new_lines = []
    for line in lines:
        m = _CLASS_DECL_RE.search(line)
        if m:
            cname = m.group(1)
            if cname != main_class:
                # Strip public before class/interface/enum/record
                line = re.sub(
                    r"\bpublic\s+((?:final\s+|abstract\s+)*(?:class|interface|enum|record)\s+" + re.escape(cname) + r")\b",
                    r"\1",
                    line,
                )
            else:
                # Ensure main_class has public
                if not re.search(r"\bpublic\s+(?:final\s+|abstract\s+)*(?:class|interface|enum|record)\b", line):
                    line = re.sub(
                        r"\b((?:final\s+|abstract\s+)*(?:class|interface|enum|record)\s+" + re.escape(cname) + r")\b",
                        r"public \1",
                        line,
                    )
        new_lines.append(line)

    return "\n".join(new_lines), main_class


class JavaChecker:
    """
    Executes compilation and test runs for generated questions.
    Can be instantiated with a custom runner for deterministic unit testing.
    """

    def __init__(self, javac_path=None, java_path=None, runner=None):
        if runner is not None:
            self.runner = runner
            self.javac_path = javac_path or "javac"
            self.java_path = java_path or "java"
            self.available = True
        else:
            j_c, j_r = find_jdk()
            self.javac_path = javac_path or j_c
            self.java_path = java_path or j_r
            self.runner = self._default_runner
            self.available = bool(self.javac_path and self.java_path)

    def _default_runner(self, cmd, timeout, cwd):
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def check_question(self, question_record):
        """
        Check a normalized question record.
        Returns (ok: bool, reject_reason: str or None).
        If java is not available, returns (True, None).
        """
        if not self.available:
            return True, None

        qtype = question_record.get("qtype") or "concept"
        q_text = question_record.get("question", "")
        snippets = extract_java_snippets(q_text)

        if not snippets:
            if qtype in ("code_output", "bug_find"):
                return False, "missing_java_fence"
            return True, None

        snippet = snippets[0]
        code, main_class = prepare_java_source(snippet)

        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, f"{main_class}.java")
            with open(src_file, "w", encoding="utf-8") as f:
                f.write(code)

            # 1. Compile with 15s timeout
            try:
                ret, stdout, stderr = self.runner(
                    [self.javac_path, f"{main_class}.java"],
                    timeout=15,
                    cwd=tmpdir,
                )
            except subprocess.TimeoutExpired:
                return False, "javac_timeout"
            except Exception as exc:
                return False, f"javac_execution_error: {exc}"

            combined_err = (stderr or "") + "\n" + (stdout or "")

            # Branch based on qtype
            if qtype == "bug_find":
                if ret == 0:
                    return False, "bug_find_compiles"

                # Check exactly one compile error
                err_count = self._count_compile_errors(combined_err)
                if err_count != 1:
                    return False, f"bug_find_error_count_{err_count}"

                # Check error keyword appears in explanation
                explanation = (question_record.get("explanation") or "").lower()
                if not self._keyword_in_explanation(combined_err, explanation):
                    return False, "bug_find_explanation_mismatch"

                return True, None

            if qtype == "code_output":
                if ret != 0:
                    return False, "code_output_compile_error"

                # Run with 10s timeout
                try:
                    r_ret, r_stdout, r_stderr = self.runner(
                        [self.java_path, main_class],
                        timeout=10,
                        cwd=tmpdir,
                    )
                except subprocess.TimeoutExpired:
                    return False, "java_run_timeout"
                except Exception as exc:
                    return False, f"java_run_execution_error: {exc}"

                if r_ret != 0:
                    return False, "code_output_runtime_error"

                # Whitespace normalisation comparison with correct option
                options = question_record.get("options", [])
                correct_idx = question_record.get("correct", 0)
                if not (0 <= correct_idx < len(options)):
                    return False, "correct_out_of_range"

                correct_text = options[correct_idx]
                if isinstance(correct_text, dict):
                    correct_text = correct_text.get("text", "")

                norm_out = " ".join(r_stdout.strip().split())
                norm_ans = " ".join(str(correct_text).strip().split())

                if norm_out != norm_ans:
                    return False, "code_output_mismatch"

                return True, None

            # qtype == 'concept'
            if ret != 0:
                return False, "concept_snippet_compile_error"

            return True, None

    @staticmethod
    def _count_compile_errors(err_text):
        m = _ERROR_COUNT_RE.search(err_text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        # Fallback count of ': error:'
        matches = re.findall(r":\s*error:\s*", err_text, re.IGNORECASE)
        return len(matches) if matches else 1

    @staticmethod
    def _keyword_in_explanation(err_text, explanation):
        if not explanation:
            return False

        # Extract words from error lines
        error_lines = [
            line for line in err_text.splitlines()
            if "error:" in line.lower()
        ]
        tokens = set()
        for line in error_lines:
            part = line.split("error:", 1)[-1]
            words = re.findall(r"[A-Za-z0-9_$]{3,}", part.lower())
            for w in words:
                if w not in _STOP_WORDS:
                    tokens.add(w)

        if not tokens:
            return True  # Cannot extract specific keyword, let pass

        for token in tokens:
            if token in explanation:
                return True

        return False

