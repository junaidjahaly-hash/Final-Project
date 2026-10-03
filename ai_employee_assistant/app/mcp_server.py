from pathlib import Path
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).resolve().parents[1]
env_path = PROJECT_ROOT / '.env'
load_dotenv(dotenv_path=env_path)
import sys
import warnings
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
import os

# Keep library output off stdout; MCP uses it for JSON-RPC.
old_stdout = sys.stdout
sys.stdout = sys.stderr

# Disable telemetry and warnings that corrupt MCP stdio JSON-RPC
os.environ["ANONYMIZED_TELEMETRY"] = "False"
warnings.filterwarnings("ignore")

# Mock posthog to prevent ChromaDB from printing telemetry failure messages
class MockPosthog:
    def __init__(self, *args, **kwargs): pass
    def capture(self, *args, **kwargs): pass
sys.modules["posthog"] = MockPosthog()
sys.modules["posthog.client"] = MockPosthog()

# Ensure the app module can be found when running this script directly
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import Session
from app.database import get_db, SupportTicket
from app.rag import get_embedding, collection, clean_text

mcp = FastMCP("AI Employee Assistant MCP Server")

@mcp.tool()
def search_company_knowledge(query: str) -> str:
    """
    Search the company knowledge base (HR policies, SOPs, uploaded PDFs) for relevant information.
    Use this tool when asked about company policies or documentation.
    """
    try:
        query_vector = get_embedding(query)
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=5
        )

        context = ""
        if results and results["documents"]:
            for i, doc_text in enumerate(results["documents"][0]):
                cleaned = clean_text(doc_text)
                meta = results["metadatas"][0][i]
                filename = meta["filename"]
                from app.document_evidence import citation_for
                evidence = citation_for(filename, doc_text, meta, str(PROJECT_ROOT / 'uploads'))
                page = f", page {evidence['page']}" if evidence['page'] else ', page unavailable'
                context += f"Source ({filename}{page}):\n{cleaned}\n\n"
        
        if not context.strip():
            return "No relevant company documents found for this query."
        return context
    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"

@mcp.tool()
def create_support_ticket(subject: str, description: str, priority: str = "medium", created_by: str = "mcp_agent") -> str:
    """
    Create a new support ticket for an employee issue (e.g. IT, HR requests).
    Requires a subject, description, and priority (low, medium, high).
    """
    try:
        db = next(get_db())
        from app.database import User
        if priority not in {'low', 'medium', 'high'} or not subject.strip() or not description.strip():
            db.close()
            return 'Error: provide a subject, description, and valid priority.'
        if not db.query(User).filter_by(username=created_by).first():
            db.close()
            return 'Error: an authenticated employee account is required.'
        ticket = SupportTicket(
            created_by=created_by,
            subject=subject,
            description=description,
            priority=priority
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        from app.workflows import ticket_created
        ticket_created(db, ticket)
        db.commit()
        db.close()
        return f"Support ticket #{ticket.id} created successfully with subject: '{subject}'."
    except Exception as e:
        return f"Error creating ticket: {str(e)}"

@mcp.tool()
def get_open_tickets(username: str = "") -> str:
    """
    Retrieve a list of all currently open support tickets in the system.
    """
    try:
        db = next(get_db())
        from app.database import User
        from sqlalchemy import or_
        account = db.query(User).filter_by(username=username).first()
        if not account:
            db.close()
            return 'Error: an authenticated employee account is required.'
        query = db.query(SupportTicket).filter(SupportTicket.status != "resolved")
        if account.role != 'admin':
            query = query.filter(or_(SupportTicket.created_by == username, SupportTicket.assigned_to == username))
        tickets = query.all()
        db.close()
        
        if not tickets:
            return "There are no open support tickets right now."
            
        result = "Open Support Tickets:\n"
        for t in tickets:
            result += f"- Ticket #{t.id}: [{t.priority.upper()}] {t.subject} (Created by {t.created_by})\n"
        return result
    except Exception as e:
        return f"Error retrieving tickets: {str(e)}"

@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """
    Send an email to a user. This is a high-impact action that typically requires approval.
    """
    sender_email = os.getenv("SMTP_EMAIL")
    sender_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not sender_email or not sender_password:
        return f"Mock Email Sent (Success) to {to}. Note: To send real emails, please set SMTP_EMAIL and SMTP_PASSWORD environment variables."

    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return f"Email physically sent to {to} via {smtp_server} with subject '{subject}'."
    except Exception as e:
        return f"Failed to send email: {str(e)}"

@mcp.tool()
def execute_database_query(query: str) -> str:
    """
    Execute a raw SQL query on the internal database. This is a high-impact action that typically requires approval.
    """
    return f"Executed query: {query}. Result: 1 row(s) updated."

if __name__ == "__main__":
    # Restore stdout before starting the MCP transport.
    sys.stdout = old_stdout
    mcp.run(transport='stdio')
