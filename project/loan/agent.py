"""Loan account agent.

Owns loan data only. It can answer straightforward questions about the loans
the customer already holds, and it can run a new application through the
approval workflow in loan.py.

It has no tool that can read a deposit account. When the approval workflow
needs to know whether the customer holds enough on deposit, it asks the
deposit agent over A2A and gets back a single true or false. That is the only
channel between the two sides, and it is deliberately narrow.
"""

import os

from google.adk.agents import Agent
from google.adk.sessions import InMemorySessionService

from toolbox_core import ToolboxSyncClient

# The approval workflow lives in its own module in this same folder.
from .loan import loan_approval_agent

# Configure short-term session to use the in-memory service
session_service = InMemorySessionService()

# Read the instructions from a file in the same
# directory as this agent.py file.
script_dir = os.path.dirname(os.path.abspath(__file__))
instruction_file_path = os.path.join(script_dir, "agent-prompt.txt")
with open(instruction_file_path, "r") as f:
  instruction = f.read()

# Set up the tools that we will be using for the root agent. These read the
# loans table through the MCP Database Toolbox and nothing else.
toolbox_url = os.environ.get("TOOLBOX_URL", "http://127.0.0.1:5000")
print(f"Connecting to Toolbox at {toolbox_url}")
db_client = ToolboxSyncClient(toolbox_url)
tools = db_client.load_toolset("loan-toolset")

sub_agents = [
  loan_approval_agent,
]

# Use the Gemini 2.5 Flash model since it performs quickly
# and handles the processing well.
model = "gemini-2.5-flash"

# Create our agent
root_agent = Agent(
  name="loan",
  model=model,
  description=(
    "Answers questions about the customer's existing loans and assesses "
    "applications for new ones."
  ),
  instruction=instruction,
  tools=tools,
  sub_agents=sub_agents,
)