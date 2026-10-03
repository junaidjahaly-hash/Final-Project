import os
import sys

# Keep library output off stdout; MCP uses it for JSON-RPC.
old_stdout = sys.stdout
sys.stdout = sys.stderr

os.environ["ANONYMIZED_TELEMETRY"] = "False"

# Ensure the app module can be found
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import Session
from app.database import get_db, SupportTicket
from app.rag import get_embedding, collection, clean_text

mcp = FastMCP("AI Employee Assistant MCP Server")

@mcp.tool()
def search_company_knowledge(query: str) -> str:
    """Search company knowledge base."""
    return "Test response"

@mcp.tool()
def get_open_tickets() -> str:
    """Get tickets."""
    return "Test tickets"

@mcp.tool()
def create_support_ticket(subject: str, description: str, priority: str = "medium") -> str:
    """Create a ticket."""
    return "Test created"

if __name__ == "__main__":
    # Restore stdout before starting the MCP transport.
    sys.stdout = old_stdout
    mcp.run(transport='stdio')
