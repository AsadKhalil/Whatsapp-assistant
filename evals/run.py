"""Play evals/cases.yaml against a real model through the real bot (fake Sheet, fake WhatsApp).

Usage: uv run --env-file .env python -m evals.run [--model M] [--base-url URL] [--api-key KEY]
Costs real API credit. Writes evals/reports/<model>-<time>.json for comparing models.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import yaml

from app.bot import Bot
from app.config import Settings
from app.llm import LLM
from app.store import Store
from tests.fakes import FakeMeta, FakeWaha, bakery_sheets, incoming, make_client

HERE = Path(__file__).parent


def check(case: dict, reply: str, sheets) -> list[str]:
    low, failures = reply.lower(), []
    failures += [f"missing {s!r}" for s in case.get("reply_has", []) if s.lower() not in low]
    if case.get("reply_has_any") and not any(s.lower() in low for s in case["reply_has_any"]):
        failures.append(f"none of {case['reply_has_any']!r}")
    failures += [f"should not say {s!r}" for s in case.get("reply_lacks", []) if s.lower() in low]
    if case.get("reply_lacks_regex") and re.search(case["reply_lacks_regex"], reply, re.IGNORECASE):
        failures.append(f"matched {case['reply_lacks_regex']!r}")
    if want := case.get("proposes"):
        if f"add to {want['tab'].lower()}:" not in low or want["has"].lower() not in low:
            failures.append(f"no proposal for {want['tab']} with {want['has']!r}")
    if (tab := case.get("saves_to")) and not any(t == tab for t, _ in sheets.appended):
        failures.append(f"nothing saved to {tab}")
    return failures


def run_case(case: dict, llm) -> dict:
    client, sheets, meta, waha = make_client(), bakery_sheets(), FakeMeta(), FakeWaha()
    bot = Bot(Store(":memory:"), sheets, llm, meta, waha, {client.id: client})
    group = case.get("group")
    start = time.perf_counter()
    for i, text in enumerate(case["say"]):
        bot.handle(incoming(text, msg_id=f"{case['name']}-{i}", group=group, mention=bool(group),
                            phone=case.get("phone", "923001234567")))
    replies = [text for to, text, _ in (waha.sent if group else meta.sent) if not group or to == group]
    reply = replies[-1] if replies else ""
    return {"name": case["name"], "reply": reply, "failures": check(case, reply, sheets),
            "seconds": round(time.perf_counter() - start, 2)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key")
    args = parser.parse_args(argv)
    overrides = {k: v for k, v in {"llm_model": args.model, "llm_base_url": args.base_url,
                                   "llm_api_key": args.api_key}.items() if v}
    settings = Settings.from_env(**overrides)
    llm = LLM(settings)
    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    results = [run_case(case, llm) for case in cases]
    for r in results:
        print(f"{'PASS' if not r['failures'] else 'FAIL'}  {r['name']:<34} {r['seconds']:>6}s  "
              + "; ".join(r["failures"]))
    passed = sum(not r["failures"] for r in results)
    print(f"\n{passed}/{len(results)} passed with {settings.llm_model}")
    out = HERE / "reports" / f"{re.sub(r'[^A-Za-z0-9.-]', '_', settings.llm_model)}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"model": settings.llm_model, "base_url": settings.llm_base_url, "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
