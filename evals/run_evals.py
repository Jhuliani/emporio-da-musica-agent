"""Run the agent against the evaluation scenarios using the real LLM.

Usage:
    python evals/run_evals.py                 # all scenarios
    python evals/run_evals.py --only store_address order_lookup_delayed

Reads the provider config from .env. Writes a markdown report to
evals/results.md. Kept separate from pytest because it is slow, costs API
calls and is non-deterministic.
"""

from __future__ import annotations

import argparse
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from emporio.agent import Agent  # noqa: E402
from emporio.llm import LLMConfig  # noqa: E402
from emporio.tools import StoreTools  # noqa: E402
from emporio.data import load_store  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

REPORT = ROOT / "evals" / "results.md"
PAUSE_SECONDS = 4  # stay under free-tier requests-per-minute limits
RETRIES = 3


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def run_turn(agent: Agent, history: list[dict], message: str):
    for attempt in range(RETRIES):
        reply = agent.reply(history, message)
        if not reply.error:
            return reply
        wait = 15 * (attempt + 1)
        print(f"    provider error ({reply.error}); retrying in {wait}s")
        time.sleep(wait)
    return reply


def check(scenario: dict, reply_text: str, tools_called: list[str]) -> list[str]:
    text = norm(reply_text)
    failures = []
    for tool in scenario.get("tools", []):
        if tool not in tools_called:
            failures.append(f"expected tool `{tool}` not called")
    any_tools = scenario.get("tools_any", [])
    if any_tools and not set(any_tools) & set(tools_called):
        failures.append(f"none of tools {any_tools} called")
    for tool in scenario.get("forbidden_tools", []):
        if tool in tools_called:
            failures.append(f"forbidden tool `{tool}` was called")
    for s in scenario.get("contains_all", []):
        if norm(s) not in text:
            failures.append(f"missing `{s}`")
    any_of = scenario.get("contains_any", [])
    if any_of and not any(norm(s) in text for s in any_of):
        failures.append(f"none of {any_of} found")
    for s in scenario.get("not_contains", []):
        if norm(s) in text:
            failures.append(f"must not contain `{s}`")
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="scenario names to run")
    args = parser.parse_args()

    config = LLMConfig.from_env()
    if not config.api_key:
        sys.exit("Set LLM_API_KEY in .env to run the evals.")
    tools = StoreTools(load_store(), handoff_file=ROOT / "logs" / "eval_handoffs.jsonl")
    agent = Agent(config, tools=tools)

    scenarios = [s for s in SCENARIOS if not args.only or s["name"] in args.only]
    results = []
    for i, scenario in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] {scenario['name']}")
        history, tools_called, reply = [], [], None
        for message in scenario["messages"]:
            reply = run_turn(agent, history, message)
            history.extend(reply.new_messages)
            tools_called.extend(c.name for c in reply.tool_calls)
            time.sleep(PAUSE_SECONDS)

        failures = [f"provider error: {reply.error}"] if reply.error else check(scenario, reply.text, tools_called)
        results.append({**scenario, "reply": reply.text, "tools_called": tools_called, "failures": failures})
        print("    PASS" if not failures else f"    FAIL: {'; '.join(failures)}")

    write_report(results, config)
    passed = sum(not r["failures"] for r in results)
    print(f"\n{passed}/{len(results)} passed. Report: {REPORT.relative_to(ROOT)}")


def write_report(results: list[dict], config: LLMConfig):
    passed = sum(not r["failures"] for r in results)
    lines = [
        "# Evaluation Results",
        "",
        f"- **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **Model:** `{config.model}` via `{config.base_url}`",
        f"- **Passed:** {passed}/{len(results)}",
        "",
        "| Scenario | Result | Tools called | Failures |",
        "|---|---|---|---|",
    ]
    for r in results:
        status = "✅" if not r["failures"] else "❌"
        tools = ", ".join(f"`{t}`" for t in r["tools_called"]) or "—"
        lines.append(f"| `{r['name']}` | {status} | {tools} | {'; '.join(r['failures']) or '—'} |")

    lines += ["", "## Transcripts", ""]
    for r in results:
        lines += [f"### `{r['name']}`", "", f"_{r['description']}_", ""]
        lines += [f"> **Cliente:** {m}" for m in r["messages"]]
        lines += ["", "**Tom:**", "", r["reply"], ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
