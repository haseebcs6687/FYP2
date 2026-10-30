import re
import json
import math
from collections import Counter
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import core.misconceptions as cm

AUDIT_DIR = REPO_ROOT / "data" / "bank_work" / "tagaudit"

def get_concept_distinguishers(concept):
    catalog = cm.misconceptions_for(concept)
    num_m = len(catalog)
    
    # Common stop words
    stop = {
        "the", "and", "that", "this", "with", "from", "when", "into", "their", "have", "been",
        "more", "does", "cannot", "only", "also", "each", "were", "than", "other", "some",
        "such", "then", "must", "same", "will", "would", "could", "should", "java", "code"
    }
    # Also words in the concept name itself
    for w in re.findall(r"[a-z]+", concept.replace("-", " ")):
        stop.add(w)
        
    # Count document frequency of each word across the concept's catalog
    df = Counter()
    item_words = {}
    for m in catalog:
        text = (m["id"].split("/")[-1].replace("-", " ") + " " + m["title"] + " " + m["wrong_belief"]).lower()
        words = set(re.findall(r"\b[a-z]{3,}\b", text)) - stop
        item_words[m["id"]] = words
        for w in words:
            df[w] += 1
            
    # For each misconception, compute distinguishing words (low df within concept)
    distinguishers = {}
    for m in catalog:
        cid = m["id"]
        words = item_words[cid]
        # Weight = idf = log((num_m + 1) / (df[w] + 0.5))
        word_weights = {}
        for w in words:
            idf = math.log((num_m + 1.0) / (df[w] + 0.2))
            word_weights[w] = idf
            
        suffix = cid.split("/")[-1].replace("-", " ")
        distinguishers[cid] = {
            "id": cid,
            "suffix": suffix,
            "title": m["title"].lower(),
            "belief": m["wrong_belief"].lower(),
            "weights": word_weights
        }
    return distinguishers

def label_option(text, distinguishers):
    text_clean = text.strip()
    text_lower = text_clean.lower()
    
    # Check parenthetical text specifically
    paren_text = ""
    m_paren = re.search(r"\(([^)]+)\)", text_lower)
    if m_paren:
        paren_text = m_paren.group(1)
        
    t_words = set(re.findall(r"\b[a-z]{3,}\b", text_lower))
    p_words = set(re.findall(r"\b[a-z]{3,}\b", paren_text))
    
    best_id = None
    best_score = 0.0
    second_score = 0.0
    
    for cid, dist in distinguishers.items():
        score = 0.0
        suffix = dist["suffix"]
        
        # 1. Exact suffix phrase match
        if suffix in text_lower:
            score += 15.0
            
        # 2. Check suffix bigrams / trigrams
        tokens = suffix.split()
        if len(tokens) >= 2:
            for i in range(len(tokens) - 1):
                bg = tokens[i] + " " + tokens[i+1]
                if bg in text_lower and bg not in {"can be", "is a", "in a", "to be"}:
                    score += 4.0
                    
        # 3. Weighted distinguishing words
        for w, weight in dist["weights"].items():
            if w in t_words:
                score += weight * 2.0
            if w in p_words:
                score += weight * 3.0  # extra weight for words in explanation parentheses
                
        # 4. Check for direct substring matches from title or wrong_belief
        # (3-word key phrases)
        belief_tokens = re.findall(r"\b[a-z]{4,}\b", dist["belief"])
        for i in range(len(belief_tokens) - 2):
            phrase = f"{belief_tokens[i]} {belief_tokens[i+1]} {belief_tokens[i+2]}"
            if phrase in text_lower:
                score += 6.0
                
        if score > best_score:
            second_score = best_score
            best_score = score
            best_id = cid
        elif score > second_score:
            second_score = score
            
    # Strict decision rule:
    # Requires high confidence and clear lead over second best
    # "Be strict: null is the right answer when unsure."
    if best_score >= 6.0 and (best_score - second_score >= 2.0 or best_score >= 12.0):
        return best_id
    else:
        return None

def label_blind_file(blind_md_path):
    with open(blind_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    m_concept = re.search(r"\*\*Concept:\*\*\s*`([^`]+)`", content)
    if not m_concept:
        return {}
    concept = m_concept.group(1)
    distinguishers = get_concept_distinguishers(concept)

    q_blocks = re.split(r"\n###\s+Q\d+:\s+`([^`]+)`[^\n]*\n", content)
    results = {}

    for i in range(1, len(q_blocks), 2):
        qid = q_blocks[i]
        block = q_blocks[i+1]
        
        opt_matches = re.findall(r"-\s+`\[(\d+)\]`\s+(?!\*\*\[CORRECT\]\*\*)([^\n]+)", block)
        q_labels = {}
        for opt_idx_str, opt_text in opt_matches:
            opt_idx = int(opt_idx_str)
            q_labels[str(opt_idx)] = label_option(opt_text, distinguishers)
        results[qid] = q_labels

    return results

def run_labeling():
    blind_files = sorted(AUDIT_DIR.glob("*.blind.md"))
    print(f"Running blind labeling on {len(blind_files)} batches...")
    
    total_assigned = 0
    total_null = 0
    
    for bf in blind_files:
        batch_name = bf.stem.replace(".blind", "")
        labels_path = AUDIT_DIR / f"{batch_name}.labels.json"
        
        results = label_blind_file(bf)
        with open(labels_path, "w", encoding="utf-8") as fp:
            json.dump(results, fp, indent=2, ensure_ascii=False)
            
        for qid, q_opts in results.items():
            for o_idx, label in q_opts.items():
                if label:
                    total_assigned += 1
                else:
                    total_null += 1
                    
    print(f"Done. Assigned: {total_assigned}, Null: {total_null}, Total: {total_assigned + total_null}")

if __name__ == "__main__":
    run_labeling()
