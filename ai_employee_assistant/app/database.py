import os
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_URL = f"sqlite:///{PROJECT_ROOT / 'app.db'}"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

try:
    if DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL)
        # Test connection immediately
        with engine.connect() as conn:
            pass
except Exception as e:
    print(f"⚠️ Postgres connection failed ({e}). Falling back to local SQLite database ({DEFAULT_SQLITE_URL}).")
    DATABASE_URL = DEFAULT_SQLITE_URL
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="employee")  # "admin" or "employee"
    created_at = Column(DateTime, default=datetime.utcnow)

class DocumentMetadata(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    file_type = Column(String, default="pdf")  # "pdf" or "csv"
    uploaded_by = Column(String, default="system")
    upload_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="processed")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    username = Column(String, index=True)
    action = Column(String)  # "login", "upload", "query", "register", "ticket", "reminder"
    details = Column(Text)
    ip_address = Column(String)

class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, index=True)
    subject = Column(String)
    description = Column(Text)
    status = Column(String, default="open")  # "open", "in_progress", "resolved", "escalated"
    priority = Column(String, default="medium")  # "low", "medium", "high"
    assigned_to = Column(String, nullable=True)

class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    username = Column(String, index=True)
    message = Column(Text)
    due_date = Column(DateTime, nullable=True)
    is_done = Column(Boolean, default=False)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    title = Column(String, default="New Chat")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, index=True)
    role = Column(String)  # "user" or "assistant"
    content = Column(Text)
    is_html = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserMemory(Base):
    __tablename__ = "user_memories"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    fact = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, index=True)
    username = Column(String, index=True)
    tool_name = Column(String)
    tool_arguments = Column(JSON)
    status = Column(String, default="pending")  # pending, approved, rejected
    created_at = Column(DateTime, default=datetime.utcnow)

class RLFeedback(Base):
    __tablename__ = "rl_feedback"
    id = Column(Integer, primary_key=True, index=True)
    query_text = Column(Text)
    mode_selected = Column(String, index=True)
    reward = Column(Integer)  # +1 for positive (thumbs up), -1 for negative (thumbs down)
    user_comment = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class RLPolicyWeight(Base):
    __tablename__ = "rl_policy_weights"
    id = Column(Integer, primary_key=True, index=True)
    mode_name = Column(String, unique=True, index=True)
    q_value = Column(Integer, default=100)  # Q-score representation scaled by 100
    total_uses = Column(Integer, default=0)
    positive_rewards = Column(Integer, default=0)
    negative_rewards = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)
    from datetime import timezone
    from zoneinfo import ZoneInfo
    from config import settings
    with SessionLocal() as db:
        if not db.get(AppMigration, 'reminders-utc-v1'):
            zone = ZoneInfo(settings.MCP_LOCAL_TIMEZONE)
            for reminder in db.query(Reminder).filter(Reminder.due_date.isnot(None)).all():
                reminder.due_date = reminder.due_date.replace(tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None)
            db.add(AppMigration(name='reminders-utc-v1'))
            db.commit()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class TicketReply(Base):
    __tablename__ = 'ticket_replies'
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, index=True, nullable=False)
    username = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PersonalTask(Base):
    __tablename__ = 'personal_tasks'
    id = Column(Integer, primary_key=True)
    username = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    details = Column(Text, default='')
    due_date = Column(DateTime, nullable=True)
    is_done = Column(Boolean, default=False)
    source = Column(String, default='manual')
    created_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    username = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, default='')
    kind = Column(String, nullable=False)
    resource_id = Column(Integer, nullable=True)
    event_key = Column(String, unique=True, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AppMigration(Base):
    __tablename__ = 'app_migrations'
    name = Column(String, primary_key=True)
