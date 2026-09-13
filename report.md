# Multi-Agent Banking Prototype

## Report to the Board, Example National Bank

Prepared by the development team. Built on Google's Agent Development Kit,
served through `adk web --a2a`, tested against the fifteen scenarios the board
supplied. No real customer data was used. Every figure in this report comes
from a synthetic record for a single pre-authenticated customer.

---

## 1. What was built

Three agents, each owning one narrow slice of the bank, running as independent
services that talk to each other over the A2A protocol.

**The manager agent** is the front door. It answers general questions about the
bank from its own instructions, things like branch hours, the telephone banking
number and which products exist. It holds no customer data at all and has no
database tool. Anything touching an account it passes to the agent that owns
that data.

**The deposit agent** owns the `accounts` and `transactions` tables and nothing
else. It can list accounts, return the balance of one named account and return
recent transactions. It also answers one narrow question for the rest of the
bank: does the combined deposit balance reach a given amount, true or false.

**The loan agent** owns the `loans` table. It answers questions about existing
borrowing and runs applications for new loans through a six-stage approval
workflow.

The separation is enforced in three places at once, not just in the prompts.
Each agent lives in its own folder and imports nothing from the others. Each
has its own `tools.yaml`, so the loan agent has no tool that can read a deposit
balance even if it wanted one. And the only channel between the two is a single
A2A call carrying one number out and one word back.

### How they connect

The manager reaches the other two as `RemoteA2aAgent`, resolved through their
published agent cards at `/a2a/deposit` and `/a2a/loan`. It does not import
their code. As far as the manager is concerned they are remote services that
happen to run on the same host today. Moving either one to a different port or
a different machine is a change to two environment variables and the `url`
field in one JSON file.

All three agents publish an agent card with a name, a description, a URL and a
list of skills. The deposit card advertises the minimum balance check as a
skill in its own right, which is how the loan side discovers that the capability
exists.

---

## 2. The loan approval workflow

This is the part worth the board's attention, because it is where one agent has
to reason about data it is not allowed to see.

An application runs through a `SequentialAgent` with five stages. The middle
stage is a `ParallelAgent`. Every stage writes its result into session state,
and every later stage reads from state rather than from the conversation. The
web console shows each write as it happens, which makes the whole decision
auditable after the fact.

### Stage 1, `get_requested_value_agent`

Reads the conversation and extracts two things: what type of loan and how much.
It writes a structured `loan_request` into state with an `output_schema`, so
downstream stages get typed fields rather than prose they have to re-parse.

Loan type is classified by what the money is for, not by the words the customer
used. An off-road 4x4 is a recreational vehicle under bank policy even though
it is a vehicle, and the prompt says so explicitly.

### Stage 2, three lookups at once

`outstanding_balance_agent` queries the loans table and returns the combined
outstanding balance. For the test customer that is 22,183.29 across an auto
loan and a personal loan.

`policy_agent` holds the lending policy memo. The PDF is read from Cloud Storage
when the module loads and appended to the agent's instruction, which keeps the
agent free of tools and therefore able to carry an `output_schema`. It finds
the band that matches the request and returns the debt to equity ratio and the
minimum customer rating for that band.

`user_profile_agent` works the same way with the loan officer's written profile
of the customer. It reduces the file to one rating on the scale Excellent,
Great, Good, Fair, Poor.

These three have no dependency on each other, so they run concurrently.

### Stage 3, `total_value_agent`

A plain `BaseAgent` written in Python, not a language model. It reads the three
values from state, adds the requested amount to the existing debt and divides by
the policy ratio.

For a 10,000 auto loan: 22,183.29 plus 10,000.00 gives 32,183.29 of total debt.
Divided by the ratio of 7 for that band, the customer must hold at least
4,597.61 on deposit.

This stage is deliberately not an LLM. The arithmetic behind a lending decision
has to produce the same answer every time and has to be explainable to a
regulator line by line. A model that is right 99 percent of the time is the
wrong tool for a division.

### Stage 4, `check_equity_agent`

Takes the minimum from state and asks the deposit agent, over A2A, whether the
combined balance reaches it. The deposit agent answers true or false. It does
not answer with a total, and the loan side never asks for one.

This is the design point the board was nervous about, solved. The loan agent
makes a lending decision that depends on the customer's deposits without ever
learning what those deposits are.

### Stage 5, `approval_report_agent`

Approves only when both conditions hold: the deposit check came back true, and
the customer's rating meets or beats what the policy band requires.

On approval it names the loan type and amount and says a loan officer will be in
touch. On a decline it is brief and final and explains nothing. It never
mentions the rating, the ratio, the threshold, the existence of a policy
document or which of the two checks failed. Telling a customer their deposits
were too low would leak the threshold. Telling them their rating fell short
would leak the contents of their file.

### Worked example, declined

A 20,000 personal loan. Policy band "Personal Loans $5000 and up", ratio 100,
minimum rating Great. Total debt 42,183.29 divided by 100 gives a minimum
deposit requirement of 421.83, which the customer clears comfortably. The
deposit check returns true. The rating comes back Good, below the Great the band
requires, so the application is declined.

The customer sees: the bank is not able to approve the application at this time,
and an invitation to speak to a loan officer. Nothing else.

---

## 3. Test results

Eighteen prompts across fifteen threads, sent to the manager endpoint. The
servers were restarted first so that no session state carried over.

Thirteen threads produced the behaviour we wanted.

### What worked

Routing was reliable. Every deposit question reached the deposit agent and every
loan question reached the loan agent, including the vague ones. "My main account"
resolved to the primary account. "How much did I pay the hotel on vacation"
resolved to a transaction lookup on the vacation account and returned 200.00.

The security guardrail held every time it was tested. Thread 003 asked outright
how much was on deposit and got a refusal with an offer of individual balances
instead. Thread 015 asked for the total across all accounts and got the same
refusal. At no point did any agent produce the figure 6,730.50 or anything from
which it could be derived.

Write attempts were refused. Thread 006 asked to add 1,000 to an account and was
pointed to the app, the telephone line or a branch.

The clarification behaviour worked. Thread 002 asked for "my current balance"
with no account named and got one short question back rather than a guess.
Thread 008 asked for a 700 loan with no purpose, was asked what it was for, then
correctly classified an off-road 4x4 as recreational rather than automotive and
approved the application. Thread 009 asked about a 500,000 house purchase, which
falls outside every band in the policy, and asked for more detail instead of
inventing a mortgage product the bank does not offer.

Both approval paths produced correct decisions against the policy. Thread 010
approved a 10,000 auto loan. The separate rejection test on a 20,000 personal
loan declined without leaking anything.

### What did not work

**Multi-domain questions return only one half.** Threads 014 and 015 asked for a
summary spanning both deposits and loans. In both cases the manager transferred
to the deposit agent, and the answer came back from the deposit agent's
perspective, covering deposits and deflecting the loan half to "the loan
department".

The cause is structural. In ADK, `transfer_to_agent` hands the conversation over
rather than calling out and returning. Once the manager transfers, it is no
longer the one replying, so it cannot ask the second agent and combine the two
answers. The manager's prompt instructs it to ask one agent then the other, and
that instruction has no mechanism behind it.

The fix is to wrap both agents in `AgentTool` instead of registering them as
sub-agents, which is the pattern the loan workflow already uses successfully for
its deposit check. The manager would then call each agent, get a reply and stay
in control of the final response. This is a half-day change and it is the first
thing we would do next.

**A small borrowing request was read as a cash withdrawal.** Thread 007 asked
"Can I get $100 for bubble gum?" and was told the bank cannot hand over cash
here. The follow-up asking for 10,000 got the same answer. Under the policy this
should have been treated as a personal loan under 100, a band that exists
specifically for amounts this small and accepts a rating of Poor or better.

The phrasing is genuinely ambiguous and a human teller might well read it the
same way. But the manager decided on its own rather than asking, and a routing
rule that quietly reclassifies a borrowing request as a withdrawal will
occasionally lose the bank business. The manager's prompt needs an explicit
instruction that "can I get" plus an amount is a borrowing request unless the
customer says otherwise, and that ambiguity between borrowing and withdrawing is
resolved by asking.

---

## 4. Risks

**Non-deterministic decisions.** A language model asked the same question twice
can answer differently. Applied to lending, that means two identical applications
could receive different outcomes, which is a fair lending problem before it is a
technical one.

Our mitigation is already partly in place. The arithmetic that sets the deposit
threshold runs in Python, so the number is identical every time. The remaining
judgement calls are the policy band selection and the customer rating, and both
are constrained by `output_schema` to a fixed set of values rather than free
text. Going further, we would log every decision with its full state, run a
scheduled replay of a fixed application set and alert on any drift.

**Hallucinated figures.** A model that cannot find a number will sometimes
produce a plausible one. A fabricated balance or payment date in a banking
context is a serious matter.

Every prompt in this system instructs the agent to look the answer up with a tool
and never to rely on memory, and every figure in the test run traced back to a
real database row. That is a prompt-level control, which is not the same as a
guarantee. The stronger version is to validate numeric claims in the response
against the tool results that produced them and to block any reply containing a
figure the tools did not return.

**No human in the lending loop.** In this prototype the approval workflow
reaches a decision and tells the customer directly. For a real product that is
not acceptable, and probably not lawful, for anything beyond a token amount.

The wording we chose leaves room for this. An approval says a loan officer will
be in touch, which means the agent is recommending rather than committing. The
production version should write the application and the recommendation to a
queue for a loan officer to approve, with the agent's decision treated as a first
pass. Below some small threshold, automatic approval may be reasonable. The board
should set that number, not the system.

**A guardrail that lives in a prompt can be argued with.** The rule about never
disclosing combined balances held through every test, but it is written in
English in an instruction file, and instructions can be talked around by a
determined user.

The structural defence matters more than the wording. The deposit agent has no
tool that returns a sum. `deposit-check-minimum-balance` computes the total
inside the database and returns only the word true or false, so the figure never
enters the model's context. An agent cannot leak a number it was never given.
Extending that principle, the account listing tool deliberately returns names
without balances. We would add adversarial prompts to the regression suite and
treat any leak as a release blocker.

---

## 5. What we would build next

**Persist applications and decisions.** Right now a decision is delivered to the
customer and then gone. A tool that writes the application, the state the
workflow gathered and the recommendation into a table would give the bank an
audit trail, a queue for loan officers and a dataset for measuring how often the
agent's recommendation matches what a human decides.

**A loan officer agent.** The natural companion to the above. An internal agent
that reads the application queue, summarises each case and lets an officer
approve, decline or ask for more information. That closes the human-in-the-loop
gap and gives the officers something faster than the current process rather than
something imposed on them.

**Wider test coverage.** The current suite exercises one customer profile and a
handful of amounts. It never tests home improvement loans, never tests a customer
whose deposits fall short and never tests a Poor rating. We would add profiles
covering each rating band, amounts sitting exactly on band boundaries such as
9,999 and 10,000, and adversarial prompts aimed at the balance guardrail.

**Fix the routing pattern.** Covered in section 3. Moving the manager from
sub-agent transfers to `AgentTool` calls fixes the multi-domain summary and gives
the manager control of the final wording, which matters for tone consistency.

---

## 6. Recommendation

The concept holds up. Three agents with genuinely separate data access can
collaborate on a decision that none of them could make alone, and the one place
they touch is narrow enough to describe in a sentence. The security property the
board asked about is enforced in the database and the tool definitions, not only
in the prompts.

Two things should be settled before this goes near a real customer: a human
approval step for lending decisions, and the audit trail that makes those
decisions reviewable. Both are covered above and neither is difficult. What
they need is a decision from the board about where the automatic approval
threshold sits.