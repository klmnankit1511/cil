"""Grade every MCQ easy / medium / hard with gpt-4o-mini.

Works against Azure OpenAI or plain OpenAI — see resolve_endpoint() for the full
list of environment variables.

    # Azure (note: DEPLOYMENT is the name you gave the deployment in the portal,
    # which is often but not always the same as the model name)
    export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
    export AZURE_OPENAI_API_KEY=...
    export AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
    export AZURE_OPENAI_API_VERSION=2024-10-21      # optional

    # plain OpenAI
    export OPENAI_API_KEY=sk-...

    python classify_difficulty.py --limit 40     # cheap trial run, check the output
    python classify_difficulty.py                # the rest

Results cache in difficulty.json keyed by a hash of the question text, so the run
is resumable: re-running only grades questions it has not seen.

Then rebuild the site payloads:  python build_site_data.py
"""

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from build_site_data import SKIP_FILES, usable

ROOT = Path(__file__).parent
IN_DIR = ROOT / "mcqs"
CACHE = ROOT / "difficulty.json"

BATCH = 20          # questions per request
WORKERS = 6
MAX_Q_CHARS = 420
MAX_OPT_CHARS = 90
LEVELS = {"easy", "medium", "hard"}

SYSTEM = """You grade multiple-choice questions for Indian competitive exams \
(Coal India Ltd / GATE / SSC level, graduate engineering and aptitude).

Grade each question's difficulty for a well-prepared candidate:
- "easy": direct recall of a definition or fact, or a single obvious step.
- "medium": needs a concept applied, or two to three steps of work.
- "hard": multi-step derivation, several concepts combined, subtle edge cases, \
or heavy calculation.

Judge the question itself, not how long it is. Some questions arrive with their \
mathematical notation flattened by PDF extraction; grade what you can infer and \
do not penalise garbled formatting.

Reply with JSON only: {"levels":[{"id":<int>,"level":"easy|medium|hard"}]} \
covering every id you were given."""


def load_dotenv():
    """Read KEY=VALUE lines from .env so credentials need not be exported each time.

    Real environment variables always win, so an explicit export still overrides.
    """
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def resolve_endpoint(args) -> tuple[str, str, dict]:
    """Work out the URL, model and auth headers for whichever service is configured.

    Plain OpenAI (or any compatible gateway):
        OPENAI_API_KEY=sk-...
        OPENAI_MODEL=gpt-4o-mini                     # optional
        OPENAI_BASE_URL=https://host/v1              # optional, for a proxy

    Azure OpenAI — the URL embeds the *deployment* name, and auth uses api-key:
        AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
        AZURE_OPENAI_API_KEY=...
        AZURE_OPENAI_DEPLOYMENT=<your gpt-4o-mini deployment name>
        AZURE_OPENAI_API_VERSION=2024-10-21          # optional
    """
    env = os.environ
    azure = env.get("AZURE_OPENAI_ENDPOINT")

    if azure:
        deployment = args.model or env.get("AZURE_OPENAI_DEPLOYMENT")
        if not deployment:
            sys.exit("Set AZURE_OPENAI_DEPLOYMENT (or pass --model <deployment>).")
        key = env.get("AZURE_OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
        if not key:
            sys.exit("Set AZURE_OPENAI_API_KEY.")
        version = env.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
        url = (f"{azure.rstrip('/')}/openai/deployments/{deployment}"
               f"/chat/completions?api-version={version}")
        return url, deployment, {"api-key": key, "Content-Type": "application/json"}

    key = env.get("OPENAI_API_KEY")
    if not key:
        sys.exit(
            "No credentials found.\n\n"
            "For Azure OpenAI, create a file called .env next to this script:\n\n"
            "  AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com\n"
            "  AZURE_OPENAI_API_KEY=<your key>\n"
            "  AZURE_OPENAI_DEPLOYMENT=<your deployment name>\n\n"
            "…or export those in your shell. For plain OpenAI, set OPENAI_API_KEY.\n"
            "Portal: your resource -> Deployments lists the deployment name to use."
        )
    base = env.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = args.model or env.get("OPENAI_MODEL", "gpt-4o-mini")
    return f"{base}/chat/completions", model, {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def key_of(question: str) -> str:
    return hashlib.sha1(question.strip().encode()).hexdigest()[:16]


def load_questions() -> list[dict]:
    """Every unique question that actually reaches the site.

    Reuses build_site_data's own filters so no API spend goes on questions the
    site drops anyway — the scanned QUANT book and malformed entries.
    """
    seen, out = set(), []
    for path in sorted(IN_DIR.glob("*.json")):
        if path.stem in SKIP_FILES:
            continue
        for q in json.loads(path.read_text()):
            text = (q.get("question") or "").strip()
            if not text or not usable(q):
                continue
            k = key_of(text)
            if k in seen:
                continue
            seen.add(k)
            out.append({"key": k, "question": text, "options": q.get("options") or {}})
    return out


def render(item: dict, idx: int) -> str:
    opts = "  ".join(
        f"({letter}) {text[:MAX_OPT_CHARS]}"
        for letter, text in sorted(item["options"].items())
    )
    return f"id {idx}: {item['question'][:MAX_Q_CHARS]}\n   {opts}"


def classify(batch: list[dict], cfg: tuple, attempt: int = 0) -> dict[str, str]:
    url, model, headers = cfg
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "\n".join(render(q, i) for i, q in enumerate(batch))},
        ],
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=120)
    except requests.RequestException as e:
        if attempt < 3:
            time.sleep(2 * (attempt + 1))
            return classify(batch, cfg, attempt + 1)
        print(f"  !! network error, batch skipped: {e}", flush=True)
        return {}

    if r.status_code in (401, 403):
        sys.exit(f"Auth rejected ({r.status_code}). Check the key / endpoint.\n{r.text[:200]}")
    if r.status_code == 404:
        sys.exit(
            f"404 from {url}\nOn Azure this almost always means the deployment name "
            "or api-version is wrong — AZURE_OPENAI_DEPLOYMENT must be the name you "
            "gave the deployment, not the base model name."
        )
    if r.status_code in (429, 500, 502, 503) and attempt < 5:
        wait = float(r.headers.get("retry-after", 0)) or 3 * (attempt + 1)
        time.sleep(wait)
        return classify(batch, cfg, attempt + 1)
    if r.status_code != 200:
        print(f"  !! HTTP {r.status_code}: {r.text[:180]}", flush=True)
        return {}

    body = r.json()
    usage = body.get("usage", {})
    try:
        parsed = json.loads(body["choices"][0]["message"]["content"])
        rows = parsed["levels"] if isinstance(parsed, dict) else parsed
    except (KeyError, ValueError, TypeError) as e:
        print(f"  !! unparseable reply: {e}", flush=True)
        return {}

    out = {}
    for row in rows:
        try:
            i, level = int(row["id"]), str(row["level"]).strip().lower()
        except (KeyError, TypeError, ValueError):
            continue
        if level in LEVELS and 0 <= i < len(batch):
            out[batch[i]["key"]] = level
    out["__usage__"] = usage      # carried out for the cost tally, stripped by caller
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="classify at most N new questions")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--model", default="", help="model, or the Azure deployment name")
    args = ap.parse_args()

    load_dotenv()
    cfg = resolve_endpoint(args)
    url, model, _ = cfg
    print(f"endpoint {url.split('?')[0]}\nmodel/deployment {model}")

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    questions = load_questions()
    todo = [q for q in questions if q["key"] not in cache]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(questions)} unique questions · {len(cache)} already graded · "
          f"{len(todo)} to do")
    if not todo:
        print("nothing to classify — run build_site_data.py to publish the levels")
        return

    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    lock = threading.Lock()
    tally = {"in": 0, "out": 0, "done": 0}

    def work(batch):
        got = classify(batch, cfg)
        usage = got.pop("__usage__", {})
        with lock:
            cache.update(got)
            tally["in"] += usage.get("prompt_tokens", 0)
            tally["out"] += usage.get("completion_tokens", 0)
            tally["done"] += len(batch)
            CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True))
            pct = tally["done"] / len(todo) * 100
            cost = tally["in"] / 1e6 * 0.15 + tally["out"] / 1e6 * 0.60
            print(f"  {tally['done']:>5}/{len(todo)} ({pct:>3.0f}%)  "
                  f"graded={len(cache):<6} est. spend=${cost:.3f}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, batches))

    counts = {lv: sum(1 for v in cache.values() if v == lv) for lv in sorted(LEVELS)}
    print(f"\ncached {len(cache)} levels in {CACHE.name}: {counts}")
    print("now run:  python build_site_data.py")


if __name__ == "__main__":
    main()
