"""
Standalone LLM checker for EduGen.
Loads .env, tests both the primary and fallback models with a tiny JSON prompt,
and verifies if JSON object mode is supported.

Usage:
    python scripts/check_llm.py
"""

import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()


def check_model(client, model_name):
    print(f"\nTesting model: '{model_name}'")
    system_prompt = "You are a test assistant. Reply with a single valid JSON object."
    user_prompt = 'Return JSON with exactly this shape: {"status": "ok", "model": "' + model_name + '"}'

    json_mode_ok = False
    json_mode_error = None
    call_ok = False
    call_error = None
    parsed_data = None

    # 1. Try with response_format={"type": "json_object"}
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=500,
        )
        raw = response.choices[0].message.content or ""
        parsed_data = json.loads(raw)
        json_mode_ok = True
        call_ok = True
    except Exception as exc:
        json_mode_error = str(exc)

    # 2. If json_object failed, retry without response_format
    if not call_ok:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=500,
            )
            raw = response.choices[0].message.content or ""
            # Strip backticks if any
            clean_raw = raw.strip()
            if clean_raw.startswith("```"):
                clean_raw = clean_raw.split("\n", 1)[1] if "\n" in clean_raw else clean_raw
                if clean_raw.endswith("```"):
                    clean_raw = clean_raw.rsplit("```", 1)[0]
            parsed_data = json.loads(clean_raw)
            call_ok = True
        except Exception as exc:
            call_error = str(exc)

    # Report results
    if call_ok:
        status_str = "OK"
        print(f"  Result    : {status_str}")
        print(f"  JSON Mode : {'Supported' if json_mode_ok else f'Not supported ({json_mode_error})'}")
        print(f"  Output    : {parsed_data}")
        return True
    else:
        status_str = "FAIL"
        print(f"  Result    : {status_str}")
        print(f"  JSON Mode : Failed ({json_mode_error})")
        print(f"  Reason    : {call_error or json_mode_error}")
        return False


def main():
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key or api_key == "your-key-here":
        print("FAIL: No valid GROQ_API_KEY found in .env")
        sys.exit(1)

    primary_model = os.environ.get("EDUGEN_LLM_MODEL", "openai/gpt-oss-120b")
    fallback_model = os.environ.get("EDUGEN_LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")
    extra_model = "qwen/qwen3.8-27b"
    base_url = "https://api.groq.com/openai/v1"

    print("==================================================")
    print("  EduGen LLM Diagnostics (Groq Endpoint)")
    print(f"  Base URL        : {base_url}")
    print(f"  Primary Model   : {primary_model}")
    print(f"  Fallback Model  : {fallback_model}")
    print(f"  Extra (Info)    : {extra_model}")
    print("==================================================")

    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=api_key)
    except Exception as exc:
        print(f"FAIL: Could not initialize OpenAI client: {exc}")
        sys.exit(1)

    primary_ok = check_model(client, primary_model)
    fallback_ok = check_model(client, fallback_model)

    print(f"\n[Informational] Testing extra model: '{extra_model}'")
    extra_ok = check_model(client, extra_model)

    print("\n--------------------------------------------------")
    print(f"Summary: Primary {'OK' if primary_ok else 'FAILED'} | Fallback {'OK' if fallback_ok else 'FAILED'} | Extra ({extra_model}): {'OK' if extra_ok else 'FAILED'}")
    print("--------------------------------------------------")

    if not (primary_ok or fallback_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
