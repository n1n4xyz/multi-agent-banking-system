"""Deposit account agent.

Owns cash deposit accounts only: checking, savings and similar. It has no
knowledge of loans and imports nothing from the loan or manager folders, which
is what keeps the three agents genuinely independent. When the loan approval
workflow needs to know something about deposits it asks over A2A and receives
only what this agent is willing to disclose.

The security rule this agent enforces is that the combined balance of all
accounts is never revealed. Individual balances are fine. A yes or no answer
about whether the combined balance clears a threshold is fine. The sum itself
is not.
"""

import os

from google.adk.agents import Agent
from google.adk.sessions import InMemorySessionService

from toolbox_core import ToolboxSyncClient

# Configure short-term session to use the in-memory service
session_service = InMemorySessionService()

# Read the instructions from a file in the same
# directory as this agent.py file.
script_dir = os.path.dirname(os.path.abspath(__file__))
instruction_file_path = os.path.join(script_dir, "agent-prompt.txt")
with open(instruction_file_path, "r") as f:
  instruction = f.read()

# Set up the tools that we will be using for the root agent.
# The toolset is defined in tools.yaml and served by the MCP Database Toolbox,
# so the SQL and the database credentials never live inside the agent.
toolbox_url = os.environ.get("TOOLBOX_URL", "http://127.0.0.1:5000")
print(f"Connecting to Toolbox at {toolbox_url}")
db_client = ToolboxSyncClient(toolbox_url)
tools = db_client.load_toolset("deposit-toolset")

# Use the Gemini 2.5 Flash model since it performs quickly
# and handles the processing well.
model = "gemini-2.5-flash"

# Create our agent
root_agent = Agent(
  name="deposit",
  model=model,
  description=(
    "Answers questions about the customer's cash deposit accounts: which "
    "accounts exist, individual balances and recent transactions. Can confirm "
    "whether combined deposits clear a given threshold without revealing the "
    "total."
  ),
  instruction=instruction,
  tools=tools,
)