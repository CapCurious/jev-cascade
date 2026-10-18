# The four questions

One Jev call per ticket, all four answered together. The state is `{"ticket": <text>}`. The full
question texts are in `examples/questions.json`; this note says what each asks and why it is narrow.

## urgent (yes or no)

Yes only when the customer is blocked right now or faces a deadline within a day. Narrow because
it ignores tone: capital letters, "URGENT!!!" and "no rush" do not change the answer. A noul
answer is a probability of yes, and the cascade bands its certainty, the larger of p and 1 minus p.

## needs_human (yes or no)

Yes when the ticket asks for a person, threatens legal action, reports a repeat contact, reports
someone else in the account, or asks for a refund over $500. A manager mentioned in passing does not count.

## category (pick one)

billing, bug, account or other, for the first thing the ticket asks. A second topic later in the
ticket is ignored on purpose. The banded number is the returned confidence.

## sentiment (1 to 5)

Overall tone from very negative to very positive. The score is a probability-weighted 0-based index
into the five criteria; the kit adds 1 for display. It is the question with the lowest confidence
on this fixture, and the reason the default policy escalates 56.7% of tickets.

## Why one call carries all four

Each question reads the same state, so one request costs one set of input tokens. Escalation is per
ticket (any question below act), replacement is per field.
