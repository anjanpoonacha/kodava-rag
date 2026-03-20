#!/usr/bin/env python3
"""Fill the empty `kannada` field in corpus JSONL files using Claude.

Sends entries in batches to Claude, asking for Kannada script renderings of
romanized Kodava takk. Results are written back to data/corpus/*.jsonl and
the updated files are pushed to thakk/corpus/ in the GitHub repo.

Usage:
    python scripts/fill_kannada.py [--dry-run]
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import anthropic
from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, MODEL, DATA
from core.github_sync import append_corpus_entry  # noqa — ensure config loaded

CORPUS = DATA / "corpus"
BATCH_SIZE = 20

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)

SYSTEM = """You are a Kodava takk linguistic assistant. Your task is to render
romanized Kodava takk words and phrases into Kannada script (ಕನ್ನಡ ಲಿಪಿ).

Kodava takk is a Dravidian language of Coorg (Kodagu), Karnataka. It is closely
related to Kannada and shares most phonemes. Use standard Kannada script characters.

CRITICAL phoneme rules — these differ from standard Kannada romanization:

  d  → ಡ  (retroflex D — NOT ದ dental, NOT ಧ aspirated)
  dh → ದ  (dental d     — NOT ಧ aspirated)
  DD → ಡ್ಡ (double retroflex D)
  nd → ಂಡ (nasal + retroflex D)
  ndh→ ಂದ (nasal + dental d)
  th → ತ  (dental t)
  t  → ಟ  (retroflex T — NOT ತ dental)
  tt → ಟ್ಟ (double retroflex T)
  nth→ ಂತ (nasal + dental t)
  nt → ಂಟ (nasal + retroflex T)

Examples:
  padikana  → ಪಡಿಕನ   (d=ಡ)
  dhumba    → ದುಂಬ    (dh=ದ, NOT ಧ)
  dhaar     → ದಾರ್    (dh=ದ)
  maDDichi  → ಮಡ್ಡಿಚಿ (DD=ಡ್ಡ)
  bandhiye  → ಬಂದಿಯೆ  (ndh=ಂದ)
  thakk     → ತಕ್ಕ್   (th=ತ)

For phoneme entries (single sounds like 'a', 'th', 'd'), render the phoneme itself.
For suffix rules (like "'k", "'nda"), render the suffix.
For words and phrases, render the full form.

Return a JSON object mapping each entry id to its Kannada script rendering.
Return ONLY valid JSON — no explanation, no markdown fences."""


def batch_fill(entries: list[dict]) -> dict[str, str]:
    """Call Claude with a batch of entries, return {id: kannada_text}."""
    payload = [
        {"id": e["id"], "kodava": e["kodava"], "english": e.get("english", "")}
        for e in entries
    ]
    prompt = (
        "Fill in Kannada script for each Kodava romanization below.\n"
        "Input:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + '\n\nReturn a JSON object: {"<id>": "<kannada script>", ...}'
    )
    for attempt in range(3):
        r = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = r.content[0].text.strip()
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        # Extract first {...} block if surrounded by prose
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 2:
                raise
            time.sleep(1)
    return {}


def fill_collection(name: str, dry_run: bool = False) -> int:
    path = CORPUS / f"{name}.jsonl"
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    to_fill = [e for e in entries if not e.get("kannada")]
    if not to_fill:
        print(f"  {name}: already complete")
        return 0

    print(f"  {name}: filling {len(to_fill)} / {len(entries)} entries...")
    kannada_map: dict[str, str] = {}

    for i in range(0, len(to_fill), BATCH_SIZE):
        batch = to_fill[i : i + BATCH_SIZE]
        print(
            f"    batch {i // BATCH_SIZE + 1} ({len(batch)} entries)...",
            end=" ",
            flush=True,
        )
        result = batch_fill(batch)
        kannada_map.update(result)
        print(f"got {len(result)}")
        if i + BATCH_SIZE < len(to_fill):
            time.sleep(0.5)  # gentle rate limiting

    # Merge results back
    filled = 0
    updated = []
    for entry in entries:
        if not entry.get("kannada") and entry["id"] in kannada_map:
            entry["kannada"] = kannada_map[entry["id"]]
            filled += 1
        updated.append(entry)

    if dry_run:
        print(f"  {name}: dry-run, would write {filled} kannada values")
        for e in updated[:3]:
            print(f"    {e['id']}: {e['kodava']} → {e.get('kannada', '')}")
        return filled

    with open(path, "w", encoding="utf-8") as f:
        for entry in updated:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"  {name}: wrote {filled} kannada values → {path.name}")
    return filled


def push_to_github(name: str) -> None:
    """Push updated corpus file to thakk/corpus/ via GitHub Contents API."""
    import base64
    import urllib.request
    import config

    path = CORPUS / f"{name}.jsonl"
    repo_path = f"corpus/{name}.jsonl"
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/{repo_path}"

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
    }

    # GET current SHA (file may not exist yet)
    sha = None
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            sha = json.loads(resp.read())["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    content = base64.b64encode(path.read_bytes()).decode("ascii")
    payload_data: dict = {
        "message": f"corpus: fill kannada script for {name}.jsonl",
        "content": content,
        "branch": config.GITHUB_BRANCH,
    }
    if sha:
        payload_data["sha"] = sha

    put_req = urllib.request.Request(
        url,
        data=json.dumps(payload_data).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(put_req):
        pass
    print(f"  pushed {name}.jsonl → thakk/corpus/")


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no files will be written\n")

    print("Filling kannada script fields...")
    total = 0
    for collection in ("vocabulary", "grammar_rules", "phonemes"):
        total += fill_collection(collection, dry_run=dry_run)

    if dry_run or total == 0:
        return

    print("\nPushing to thakk/corpus/...")
    for collection in ("vocabulary", "grammar_rules", "phonemes"):
        push_to_github(collection)

    print(f"\nDone. Filled {total} kannada values.")


if __name__ == "__main__":
    main()
