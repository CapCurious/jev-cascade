#!/usr/bin/env python3
"""Seeded generator for the synthetic support tickets used by jev-cascade.

Every label is true by construction: a ticket is built from parts, and each part
carries the label it contributes. No model writes or checks a label.

    category    the main request, which is always the first thing the ticket asks
    urgent      the customer is blocked right now or faces a deadline within a day,
                whatever tone they use ("URGENT!!!" on a pricing question is not urgent;
                "no rush" in front of a real outage is still urgent)
    needs_human the ticket asks for a person, threatens legal action, reports a
                repeat contact, reports someone else in the account, or asks for a
                refund over $500 (the word "manager" in passing does not count)
    sentiment   overall tone, 1 very negative to 5 very positive; mixed-tone
                phrases carry the label their template defines

About a quarter of the tickets are ambiguous on purpose: they mix signals so the
cascade has something to escalate.

    python3 examples/make_fixtures.py [--seed 7] [--out examples]
"""
import argparse
import json
import os
import random

ASKS = {
    "billing": [
        "I was charged twice for the {plan} plan this month.",
        "Please send me an invoice for {month} that includes our VAT number.",
        "My card was declined but the payment page said it went through.",
        "Can I move from monthly to annual billing and keep my {plan} discount?",
        "I was billed for {month} after I cancelled the {plan} plan.",
        "The receipt for {month} shows the wrong company name.",
    ],
    "bug": [
        "The export button shows an error and the file never downloads.",
        "The dashboard is a blank page after I sign in on {browser}.",
        "Search returns nothing for items I can see in the list.",
        "The mobile app crashes when I open the {screen} screen.",
        "Every comment sends two notification emails instead of one.",
        "The {screen} page loads forever on {browser}.",
    ],
    "account": [
        "I need to change the email address on my account.",
        "How do I add a teammate to our workspace on the {plan} plan?",
        "I forgot my password and the reset email never arrives.",
        "Please delete my account and the data tied to it.",
        "I want to rename our company on the account.",
        "Can you remove a former colleague from our workspace?",
    ],
    "other": [
        "Do you offer a student discount?",
        "Where can I find your API rate limit documentation?",
        "Are you planning to add a dark mode?",
        "I have feedback about your onboarding emails.",
        "Does your product work with {tool}?",
        "Do you have a status page I can subscribe to?",
    ],
}
FILL = {
    "plan": ["Starter", "Team", "Business", "Pro"],
    "month": ["March", "May", "August", "October"],
    "browser": ["Firefox", "Safari", "Chrome", "Edge"],
    "screen": ["settings", "reports", "profile", "billing history"],
    "tool": ["Slack", "Zapier", "Jira", "Google Sheets"],
}
URGENT_YES = [
    "Our whole team is blocked and our launch is today.",
    "Production is down for all of our users right now.",
    "I am locked out and my client presentation starts in an hour.",
    "This has to be fixed today or we miss payroll.",
]
URGENT_NO = ["No rush on this.", "Whenever you get a chance.", "Just curious.", "", "", ""]
# (text, urgent): shouted urgency without a blocker, and a calm tone over a real blocker.
URGENT_MIXED = [
    ("URGENT!!! Quick question, no deadline on my side.", False),
    ("Not urgent, but our whole team has been locked out since this morning and the demo is today.", True),
    ("Please read ASAP when you can, it can wait until next week.", False),
    ("No rush, although the site has been down for all our users for an hour.", True),
]
HUMAN_YES = [
    "I want to speak to a manager.",
    "If this is not resolved I will take legal action.",
    "This is the third time I am contacting you about this and nobody has helped.",
    "Please have a real person call me.",
]
HUMAN_BY_CATEGORY = {
    "billing": ["Please refund the full $1,200 annual fee."],
    "account": ["Someone I do not know logged in to my account and changed my settings."],
}
HUMAN_NO_MIXED = ["As a manager myself I know how busy you are.", "Our legal team already approved the purchase.",
                  "I spoke to a colleague who uses the product and she liked it."]
SENTIMENT = {
    1: ["This is unacceptable and I am furious.", "Worst service I have ever had."],
    2: ["I am quite disappointed.", "This is really frustrating."],
    3: ["Please advise.", "Thanks in advance.", ""],
    4: ["Thanks, I appreciate the help so far.", "Happy with the product overall."],
    5: ["I love the product and your support team is fantastic.", "Thank you, you have been wonderful."],
}
SENTIMENT_MIXED = [
    ("I normally love the product, but this has been very frustrating.", 2),
    ("Your agent was lovely last time, though this delay has annoyed me.", 3),
    ("I am angry about the outage, but I still think the product is great.", 2),
    ("This is a small thing, and I am happy overall.", 4),
]
OPENERS = ["Hello,", "Hi team,", "Good morning,", "Hi,", ""]


def fill(template, rng):
    out = template
    for key, values in FILL.items():
        token = "{" + key + "}"
        if token in out:
            out = out.replace(token, rng.choice(values))
    return out


def ticket(rng, category, ambiguous):
    """Return one ticket dict; ambiguous tickets carry mixed signals."""
    parts = [rng.choice(OPENERS), fill(rng.choice(ASKS[category]), rng)]
    urgent = rng.random() < 0.35
    human = rng.random() < 0.25
    sentiment = rng.choices([1, 2, 3, 4, 5], weights=[2, 3, 4, 3, 2])[0]
    urgent_text = rng.choice(URGENT_YES) if urgent else rng.choice(URGENT_NO)
    human_text = ""
    if human:
        human_text = rng.choice(HUMAN_YES + HUMAN_BY_CATEGORY.get(category, []))
    sentiment_text = rng.choice(SENTIMENT[sentiment])
    if ambiguous:
        kind = rng.choice(["category", "urgent", "human", "sentiment"])
        if kind == "category":
            other = rng.choice([c for c in ASKS if c != category])
            extra = fill(rng.choice(ASKS[other]), rng)
            parts.append("Also, " + (extra if extra.startswith("I ") else extra[0].lower() + extra[1:]))
        elif kind == "urgent":
            urgent_text, urgent = rng.choice(URGENT_MIXED)
        elif kind == "human":
            human_text, human = rng.choice(HUMAN_NO_MIXED), False
        else:
            sentiment_text, sentiment = rng.choice(SENTIMENT_MIXED)
    tail = [urgent_text, human_text, sentiment_text]
    if rng.random() < 0.5:
        parts = [parts[0], sentiment_text] + parts[1:] + [urgent_text, human_text]
    else:
        parts = parts + tail
    text = " ".join(p for p in parts if p).strip()
    return {"text": text, "labels": {"urgent": urgent, "needs_human": human,
                                     "category": category, "sentiment": sentiment}}


def build(seed=7, n=120):
    rng = random.Random(seed)
    cats = sorted(ASKS)
    order = [cats[i % len(cats)] for i in range(n)]
    rng.shuffle(order)
    ambiguous = set(rng.sample(range(n), n // 4))
    items, seen = [], set()
    for i, category in enumerate(order):
        for _ in range(50):
            item = ticket(rng, category, i in ambiguous)
            if item["text"] not in seen:
                break
        seen.add(item["text"])
        items.append({"id": "t{:03d}".format(i + 1), "text": item["text"], "labels": item["labels"]})
    return items


QUESTIONS = {
    "urgent": {
        "type": "noul",
        "instructions": "Is this support ticket urgent? Answer yes only when the customer is blocked right now "
                        "or faces a hard deadline within a day, such as an outage, a lockout or a payment due "
                        "today. Ignore how urgent the customer says it is: capital letters, exclamation marks "
                        "and the word urgent do not count, and 'no rush' does not cancel a real outage."},
    "needs_human": {
        "type": "noul",
        "instructions": "Does this ticket need a human agent instead of an automated reply? Answer yes when the "
                        "customer asks for a manager or a person, threatens legal action, says this is a repeat "
                        "contact that nobody has resolved, reports that someone else logged in to their account, "
                        "or asks for a refund of more than $500. Mentioning a manager or a legal team in "
                        "passing does not count."},
    "category": {
        "type": "choice",
        "instructions": "Which category is the main request of this ticket, meaning the first thing the "
                        "customer asks for? If the ticket mentions a second topic, ignore it.",
        "criteria": {
            "billing": "charges, invoices, receipts, refunds, payment methods or plan changes",
            "bug": "something in the product is broken or does not work as designed",
            "account": "login, password, profile, workspace members or account deletion",
            "other": "anything else, including pricing questions, feature requests, integrations and feedback"}},
    "sentiment": {
        "type": "score",
        "instructions": "How does the customer feel overall? Judge the overall tone of the ticket.",
        "criteria": [
            "very negative: angry, furious or abusive",
            "negative: disappointed or frustrated",
            "neutral: matter of fact, no strong feeling",
            "positive: polite and appreciative",
            "very positive: enthusiastic or delighted"]},
}
POLICY = {
    "model": "jev-1.13.0",
    "fitted_on": {"n": 0, "date": "2026-10-18",
                  "source": "default policy, not fitted; jev-threshold-lab fits one on your labeled data"},
    "questions": {qid: {"type": q["type"], "act": 0.85, "review": 0.60,
                        "metrics": {"precision_at_act": 0.0, "recall_at_act": 0.0, "ece": 0.0}}
                  for qid, q in QUESTIONS.items()},
    "note": "thresholds do not transfer; refit on your data",
}


def write(out_dir, seed=7):
    os.makedirs(out_dir, exist_ok=True)
    items = build(seed)
    with open(os.path.join(out_dir, "tickets.jsonl"), "w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, sort_keys=True) + "\n")
    for name, data in (("questions.json", QUESTIONS), ("policy.json", POLICY)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    args = parser.parse_args(argv)
    items = write(args.out, args.seed)
    print("wrote {} tickets to {}".format(len(items), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
