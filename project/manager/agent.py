"""Manager agent.

The front door. Everything a customer says arrives here first. General
questions about the bank it answers itself. Anything about a deposit account
or a loan it passes to the agent that owns that data.

Both of those agents are reached as RemoteA2aAgent, by their published agent
cards, not by importing their code. As far as this module is concerned they
are remote services that happen to be running on the same host today and could
be running anywhere tomorrow.
"""

import logging
import os

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent, AGENT_CARD_WELL_KNOWN_PATH
from google.adk.sessions import InMemorySessionService

logger = logging.getLogger(__name__)

# Configure short-term session to use the in-memory service
session_service = InMemorySessionService()

# Read the instructions from a file in the same
# directory as this agent.py file.
script_dir = os.path.dirname(os.path.abspath(__file__))
instruction_file_path = os.path.join(script_dir, "agent-prompt.txt")
with open(instruction_file_path, "r") as f:
  instruction = f.read()

# Set up the tools that we will be using for the root agent.
# The manager holds no customer data of its own and so needs no tools.
tools = []

# Where the other two agents live. Overriding these in .env is all it takes to
# move them onto different ports or different machines.
DEPOSIT_AGENT_URL = os.environ.get(
  "DEPOSIT_AGENT_URL", "http://localhost:8000/a2a/deposit"
)
LOAN_AGENT_URL = os.environ.get(
  "LOAN_AGENT_URL", "http://localhost:8000/a2a/loan"
)

# Set up other agents that we can delegate to
sub_agents = [
  RemoteA2aAgent(
    name="deposit_agent",
    description=(
      "Handles cash deposit accounts: which accounts the customer holds, the "
      "balance of a named account and its recent transactions. Will not "
      "disclose combined balances across accounts."
    ),
    agent_card=f"{DEPOSIT_AGENT_URL}{AGENT_CARD_WELL_KNOWN_PATH}",
  ),
  RemoteA2aAgent(
    name="loan_agent",
    description=(
      "Handles loans: outstanding balances, terms, payment dates and "
      "applications for new borrowing."
    ),
    agent_card=f"{LOAN_AGENT_URL}{AGENT_CARD_WELL_KNOWN_PATH}",
  ),
]

# Use the Gemini 2.5 Flash model since it performs quickly
# and handles the processing well.
model = "gemini-2.5-flash"

# Create our agent
root_agent = Agent(
  name="manager",
  model=model,
  description=(
    "Customer-facing agent for Example National Bank. Answers general "
    "questions about the bank and routes account questions to the deposit "
    "and loan agents."
  ),
  instruction=instruction,
  tools=tools,
  sub_agents=sub_agents,
)