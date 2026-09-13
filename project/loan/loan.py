"""Loan approval workflow.

This module builds the loan approval sub-agent that the loan root agent hands
an application to. It is deliberately a pipeline of small agents rather than
one large one, so that each step is inspectable in the ADK web console and so
that the arithmetic is done in Python instead of by a language model.

Shape of the pipeline:

    loan_approval_agent (SequentialAgent)
      1. get_requested_value_agent    what type of loan, how much
      2. gather_loan_facts (ParallelAgent)
           outstanding_balance_agent  total debt already with the bank
           policy_agent               criteria from the policy PDF in GCS
           user_profile_agent         customer rating from the profile PDF
      3. total_value_agent            minimum equity, computed in Python
      4. check_equity_agent           asks the deposit agent over A2A
      5. approval_report_agent        the answer the customer sees

Steps two, three and four communicate only through session state. Nothing in
this file imports from the deposit or manager folders. The only contact with
the deposit side is the A2A call in step four, which can ask one question:
does the combined deposit balance reach this number, yes or no.
"""

import logging
import os
import re
from typing import AsyncGenerator, List

from google.adk.agents import SequentialAgent, ParallelAgent, LlmAgent, BaseAgent, InvocationContext
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent, AGENT_CARD_WELL_KNOWN_PATH
from google.adk.events import Event, EventActions
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import Content, Part
from pydantic import BaseModel, Field

from toolbox_core import ToolboxSyncClient

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"


def load_instructions(prompt_file: str):
  script_dir = os.path.dirname(os.path.abspath(__file__))
  instruction_file_path = os.path.join(script_dir, prompt_file)
  with open(instruction_file_path, "r") as f:
    return f.read()


# ---------------------------------------------------------------------------
# Documents held in Google Cloud Storage
#
# The policy memo and the customer profile are read once, when the module is
# imported, and appended to the prompt of the agent that evaluates them. That
# keeps those two agents free of tools, which in turn lets them use
# output_schema to write a structured result into state.
#
# Neither document is ever shown to the customer. Both feed agents whose
# output stays internal to the workflow.
# ---------------------------------------------------------------------------

GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
POLICY_BLOB = os.environ.get("POLICY_BLOB", "loan-policy.pdf")
PROFILE_BLOB = os.environ.get("PROFILE_BLOB", "loan-customer-info.pdf")


def load_pdf_from_gcs(bucket_name: str, blob_name: str) -> str:
  """Downloads a PDF from Cloud Storage and returns its text.

  Any failure is logged and turned into a short marker string rather than an
  exception, so that a missing document degrades one step of the workflow
  instead of stopping the whole agent from loading.
  """
  if not bucket_name:
    logger.error("GCS_BUCKET is not set, cannot load %s", blob_name)
    return "DOCUMENT UNAVAILABLE"

  try:
    from google.cloud import storage
    from pypdf import PdfReader
    import io

    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    data = blob.download_as_bytes()
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    logger.info("Loaded gs://%s/%s (%d characters)", bucket_name, blob_name, len(text))
    return text.strip() or "DOCUMENT UNAVAILABLE"
  except Exception as exc:  # noqa: BLE001 - a bad document must not kill the agent
    logger.error("Could not load gs://%s/%s: %s", bucket_name, blob_name, exc)
    return "DOCUMENT UNAVAILABLE"


POLICY_TEXT = load_pdf_from_gcs(GCS_BUCKET, POLICY_BLOB)
PROFILE_TEXT = load_pdf_from_gcs(GCS_BUCKET, PROFILE_BLOB)


# ---------------------------------------------------------------------------
# Structured results written into session state
# ---------------------------------------------------------------------------

class LoanRequest(BaseModel):
  """What the customer is asking for."""
  loan_type: str = Field(description="One of: auto, recreational, home improvement, personal, unknown")
  amount: float = Field(description="The amount requested in dollars, or 0 if not stated")
  stated_purpose: str = Field(description="What the customer said they want the money for")


class PolicyCriteria(BaseModel):
  """The rule from the policy memo that applies to this request."""
  policy_band: str = Field(description="The heading in the policy that applies, copied exactly")
  debt_to_equity_ratio: float = Field(description="The debt to equity ratio for that band")
  minimum_customer_rating: str = Field(description="One of: Excellent, Great, Good, Fair, Poor")


class CustomerRating(BaseModel):
  """The rating derived from the loan officer's written profile."""
  customer_rating: str = Field(description="One of: Excellent, Great, Good, Fair, Poor")
  reasoning: str = Field(description="Internal justification. Never shown to the customer.")


# ---------------------------------------------------------------------------
# Stage 1: what is being asked for
# ---------------------------------------------------------------------------

get_requested_value_agent = LlmAgent(
  name="get_requested_value_agent",
  model=MODEL,
  description="Works out what type of loan the customer wants and how much.",
  instruction=load_instructions("loan-request-prompt.txt"),
  output_schema=LoanRequest,
  output_key="loan_request",
)


# ---------------------------------------------------------------------------
# Stage 2: three independent lookups, run at the same time
# ---------------------------------------------------------------------------

toolbox_url = os.environ.get("TOOLBOX_URL", "http://127.0.0.1:5000")
db_client = ToolboxSyncClient(toolbox_url)

# This agent needs a database tool, so it cannot also carry an output_schema.
# Its prompt constrains it to emitting a bare number instead, which the
# Python agent in stage 3 parses.
outstanding_balance_agent = LlmAgent(
  name="outstanding_balance_agent",
  model=MODEL,
  description="Totals the outstanding balance across the customer's existing loans.",
  instruction=load_instructions("outstanding-balance-prompt.txt"),
  tools=db_client.load_toolset("loan-approval-toolset"),
  output_key="outstanding_balance",
)

# The policy memo is pasted onto the end of this agent's instruction at import
# time. The agent picks the band that matches the request and returns the two
# numbers that matter.
policy_agent = LlmAgent(
  name="policy_agent",
  model=MODEL,
  description="Reads the lending policy and selects the criteria for this request.",
  instruction=load_instructions("policy-base-prompt.txt") + "\n\nPOLICY DOCUMENT\n\n" + POLICY_TEXT,
  output_schema=PolicyCriteria,
  output_key="policy_criteria",
)

# Same pattern for the customer profile written by the loan officer.
user_profile_agent = LlmAgent(
  name="user_profile_agent",
  model=MODEL,
  description="Reads the loan officer's profile of the customer and assigns a rating.",
  instruction=load_instructions("user-profile-base-prompt.txt") + "\n\nCUSTOMER FILE\n\n" + PROFILE_TEXT,
  output_schema=CustomerRating,
  output_key="customer_rating",
)

gather_loan_facts = ParallelAgent(
  name="gather_loan_facts",
  description="Collects the outstanding balance, the policy criteria and the customer rating at the same time.",
  sub_agents=[
    outstanding_balance_agent,
    policy_agent,
    user_profile_agent,
  ],
)


# ---------------------------------------------------------------------------
# Stage 3: the arithmetic, in Python
#
# A language model is a poor calculator and an auditor will want to see this
# number derived the same way every time, so it is a plain BaseAgent. It reads
# three values out of state, divides, and writes the result back.
# ---------------------------------------------------------------------------

def _to_float(value) -> float:
  """Pulls the first number out of whatever the upstream agent produced."""
  if value is None:
    return 0.0
  if isinstance(value, (int, float)):
    return float(value)
  match = re.search(r"-?\d[\d,]*\.?\d*", str(value))
  if not match:
    return 0.0
  try:
    return float(match.group(0).replace(",", ""))
  except ValueError:
    return 0.0


class TotalValueAgent(BaseAgent):
  """Computes the minimum deposit balance the customer must hold.

  Total debt is the existing outstanding balance plus the amount now being
  requested. The policy defines the debt to equity ratio, and the minimum
  equity is that total debt divided by the ratio.
  """

  def __init__(
    self,
    name: str,
  ):
    super().__init__(
      name=name,
    )

  async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
    state = ctx.session.state

    loan_request = state.get("loan_request") or {}
    policy = state.get("policy_criteria") or {}

    requested_amount = _to_float(loan_request.get("amount") if isinstance(loan_request, dict) else loan_request)
    outstanding = _to_float(state.get("outstanding_balance"))
    ratio = _to_float(policy.get("debt_to_equity_ratio") if isinstance(policy, dict) else policy)

    total_debt = round(outstanding + requested_amount, 2)

    if ratio > 0:
      minimum_equity = round(total_debt / ratio, 2)
      note = (
        f"Existing loan balance {outstanding:,.2f} plus requested {requested_amount:,.2f} "
        f"gives total debt {total_debt:,.2f}. Divided by the policy ratio {ratio:g}, "
        f"the customer must hold at least {minimum_equity:,.2f} on deposit."
      )
    else:
      minimum_equity = 0.0
      note = (
        "No usable debt to equity ratio was found in the policy, so the minimum "
        "equity could not be computed."
      )

    logger.info("total_value_agent: %s", note)

    yield Event(
      author=self.name,
      content=Content(parts=[Part(text=note)]),
      actions=EventActions(
        state_delta={
          "total_debt": total_debt,
          "minimum_equity": minimum_equity,
          "equity_calculation": note,
        }
      ),
    )


total_value_agent = TotalValueAgent(name="total_value_agent")


# ---------------------------------------------------------------------------
# Stage 4: ask the deposit agent, over A2A
#
# The deposit agent is reached through its published agent card. This side of
# the bank cannot read balances and does not try to. It sends one number and
# receives one word back.
# ---------------------------------------------------------------------------

DEPOSIT_AGENT_URL = os.environ.get(
  "DEPOSIT_AGENT_URL", "http://localhost:8000/a2a/deposit"
)

deposit_agent_a2a = RemoteA2aAgent(
  name="deposit_agent_a2a",
  description=(
    "The bank's deposit account agent, reached over A2A. It will confirm "
    "whether combined deposit balances reach a given minimum."
  ),
  agent_card=f"{DEPOSIT_AGENT_URL}{AGENT_CARD_WELL_KNOWN_PATH}",
)

check_equity_agent = LlmAgent(
  name="check_equity_agent",
  model=MODEL,
  description="Asks the deposit agent whether deposits cover the required minimum.",
  instruction=load_instructions("check-equity-prompt.txt"),
  tools=[AgentTool(agent=deposit_agent_a2a)],
  output_key="equity_check",
)


# ---------------------------------------------------------------------------
# Stage 5: the decision the customer actually sees
# ---------------------------------------------------------------------------

approval_report_agent = LlmAgent(
  name="approval_report_agent",
  model=MODEL,
  description="Delivers the lending decision to the customer.",
  instruction=load_instructions("approval-report-prompt.txt"),
  output_key="loan_decision",
)


# ---------------------------------------------------------------------------
# The workflow itself
# ---------------------------------------------------------------------------

loan_approval_agent = SequentialAgent(
  name="loan_approval_agent",
  description=(
    "Handles an application for a new loan from start to finish: reads the "
    "request, gathers the outstanding balance, the lending policy and the "
    "customer's rating, works out the required deposit level, checks it with "
    "the deposit agent over A2A and gives the customer an answer."
  ),
  sub_agents=[
    get_requested_value_agent,
    gather_loan_facts,
    total_value_agent,
    check_equity_agent,
    approval_report_agent,
  ],
)