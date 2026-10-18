"""Shared client for Jev, the TypeSafe System One model that turns application state plus
plain-language questions into typed judgments (probabilities, choices, scores) your code can combine.
It is a small, fast, cheap model meant for routing, ranking, and verification steps inside programs.

Contract (version 0.1.0, stdlib only, Python 3.10 compatible):
    JevKeyMissing(RuntimeError)  raised when no API key is in the environment
    JevError(RuntimeError)       HTTP or transport failure; has .status and .body for HTTP errors
    API_URL, PRICE_PER_MILLION_INPUT, MAX_FIELD_CHARS, DEMO_LABEL
    get_key() -> str             JEV_API_KEY, falling back to TYPESAFE_API_KEY
    minimize(obj)                truncate strings and redact key-shaped substrings, recursively
    LiveClient(model, timeout, key).ask(state, questions) -> (answers, usage)
    RecordedClient(path).ask(state, questions) -> (answers, usage)   replay, no network
    cost_usd(usage) -> float
    band(number, act=0.85, review=0.60) -> "act" | "review" | "escalate"
    certainty(answer) -> float
    client_from_env(demo_path=None, model="jev-latest")
    main()                       python3 jev_client.py --smoke | --version
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import warnings

__version__ = "0.1.0"

API_URL = "https://api.typesafe.ai/v1/systemone"
PRICE_PER_MILLION_INPUT = 0.042
MAX_FIELD_CHARS = 6000
DEMO_LABEL = "DEMO (recorded response)"

_PREFIX_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}"
    r"|ghp_[A-Za-z0-9]{8,}"
    r"|github_pat_[A-Za-z0-9_]{8,}"  # privacy-grep: pattern
    r"|AKIA[A-Z0-9]{8,}"
    r"|pplx-[A-Za-z0-9_-]{8,})"
)
_KEYWORD_RE = re.compile(r"(?i)\b((?:key|token|secret)\W{0,4})[A-Za-z0-9+/=_-]{32,}")


class JevKeyMissing(RuntimeError):
    """No API key found in the environment."""


class JevError(RuntimeError):
    """HTTP failure (status and body set) or transport failure (plain message)."""

    def __init__(self, message, status=None, body=None):
        RuntimeError.__init__(self, message)
        self.status = status
        self.body = body


def get_key():
    for name in ("JEV_API_KEY", "TYPESAFE_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise JevKeyMissing(
        "No Jev API key found. Set JEV_API_KEY or TYPESAFE_API_KEY; "
        "create one at https://console.typesafe.ai/keys"
    )


def minimize(obj):
    """Redact key-shaped substrings, then cap every string at MAX_FIELD_CHARS."""
    if isinstance(obj, str):
        text = _PREFIX_RE.sub("[redacted]", obj)
        text = _KEYWORD_RE.sub(r"\1[redacted]", text)
        return text[:MAX_FIELD_CHARS]
    if isinstance(obj, dict):
        return {k: minimize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [minimize(v) for v in obj]
    return obj


def cost_usd(usage):
    tokens = (usage or {}).get("input_tokens", 0) or 0
    return tokens * PRICE_PER_MILLION_INPUT / 1000000.0


def band(number, act=0.85, review=0.60):
    if number >= act:
        return "act"
    if number >= review:
        return "review"
    return "escalate"


def certainty(answer):
    kind = answer.get("type") if isinstance(answer, dict) else None
    if kind == "noul":
        p = float(answer["noul"])
        return max(p, 1.0 - p)
    if kind in ("choice", "score"):
        return float(answer["confidence"])
    raise ValueError("unknown answer type: {!r}".format(kind))


class _Counters(object):
    def __init__(self):
        self.last_latency_s = 0.0
        self.total_input_tokens = 0
        self.total_calls = 0
        self.total_cost_usd = 0.0

    def _record(self, usage, latency):
        self.last_latency_s = latency
        self.total_calls += 1
        self.total_input_tokens += (usage or {}).get("input_tokens", 0) or 0
        self.total_cost_usd += cost_usd(usage)


class LiveClient(_Counters):
    def __init__(self, model="jev-latest", timeout=30, key=None):
        _Counters.__init__(self)
        self.model = model
        self.timeout = timeout
        self._key = key
        self._warned = False

    def ask(self, state, questions):
        if not self._warned and not any(ch.isdigit() for ch in self.model):
            self._warned = True
            warnings.warn(
                "model {!r} is an alias and can change under you; pin a versioned id "
                "such as jev-1.13.0 for reproducible results".format(self.model),
                stacklevel=2,
            )
        key = self._key or get_key()
        body = {"state": minimize(state), "model": self.model, "questions": questions}
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                text = exc.read().decode("utf-8", "replace")
            except Exception:
                text = ""
            raise JevError("HTTP {} from Jev API".format(exc.code), status=exc.code, body=text)
        except urllib.error.URLError as exc:
            raise JevError("Jev API unreachable: {}".format(exc.reason))
        except OSError as exc:
            raise JevError("Jev API call failed or timed out: {}".format(exc))
        latency = time.time() - started
        try:
            out = json.loads(raw)
            answers = out["answers"]
        except (ValueError, KeyError, TypeError):
            raise JevError("Jev API returned an unexpected response body")
        usage = out.get("usage") or {}
        self._record(usage, latency)
        return answers, usage


class RecordedClient(_Counters):
    def __init__(self, path):
        _Counters.__init__(self)
        with open(path, "r", encoding="utf-8") as fh:
            self.records = json.load(fh)["records"]

    @staticmethod
    def _canon(value):
        return json.dumps(value, sort_keys=True)

    def ask(self, state, questions):
        ids = set(questions)
        matching = [r for r in self.records if set(r.get("questions", {})) == ids]
        if not matching:
            raise KeyError(
                "no recorded response for question ids {}".format(sorted(ids))
            )
        want = self._canon(state)
        chosen = matching[0]
        for rec in matching:
            if self._canon(rec.get("state")) == want:
                chosen = rec
                break
        usage = chosen.get("usage") or {}
        self._record(usage, 0.0)
        return chosen["answers"], usage


def client_from_env(demo_path=None, model="jev-latest"):
    if demo_path:
        return RecordedClient(demo_path)
    key = get_key()
    return LiveClient(model=model, key=key)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jev client utilities")
    parser.add_argument("--smoke", action="store_true", help="one live question on a tiny state")
    parser.add_argument("--version", action="store_true", help="print version")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.smoke:
        state = {"posting": "Product manager, Austin. Candidates must already be authorized to "
                            "work in the US. We do not sponsor visas."}
        questions = {"no_sponsorship": {
            "type": "noul",
            "instructions": "Does this posting refuse to sponsor work visas?"}}
        try:
            client = client_from_env()
            answers, usage = client.ask(state, questions)
        except (JevKeyMissing, JevError) as exc:
            print("smoke failed: {}".format(exc))
            return 1
        print("answer: {}".format(json.dumps(answers)))
        print("latency_s: {:.2f}".format(client.last_latency_s))
        print("input_tokens: {}".format(usage.get("input_tokens")))
        print("cost_usd: {:.8f}".format(client.total_cost_usd))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
