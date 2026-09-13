# Multi-Agent Banking Prototype

Three independent banking agents built on Google's Agent Development Kit,
communicating over the A2A protocol. Built as a prototype to show that agents
with genuinely separate data access can collaborate on a lending decision
without any one of them seeing the whole customer picture.

## The agents

`project/manager` answers general questions about the bank and routes account
questions to the other two. Holds no customer data.

`project/deposit` owns deposit accounts. Lists accounts, returns individual
balances and transactions, and confirms whether combined balances clear a
threshold without ever disclosing the total.

`project/loan` owns loans. Answers questions about existing borrowing and runs
new applications through a six-stage approval workflow that reads a policy PDF
and a customer profile PDF from Cloud Storage, computes the required deposit
level in Python and checks it with the deposit agent over A2A.

## Running it

See `runbook.md` for setup: Cloud SQL, the Cloud Storage bucket, the MCP
Database Toolbox and the agents themselves.

## Deliverables

`report.md` is the analysis written for the bank's board, covering the
architecture, the approval orchestration, the test results, the risks and what
would come next. `project/architecture.png` is the system diagram.
`project/test_results.*` are the results of the fifteen board scenarios.
`project/screenshots` shows the approval and rejection flows with final state.
