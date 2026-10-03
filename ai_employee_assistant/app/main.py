import os
from pathlib import Path
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=env_path)
from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.database import init_db
    init_db()
    from app.agent import init_clients, mcp_clients
    await init_clients()
    yield
    for client in mcp_clients.values():
        await client.disconnect()

app = FastAPI(lifespan=lifespan)

from sqlalchemy.orm import Session
from app.database import get_db, DocumentMetadata, User, AuditLog, SupportTicket, Reminder, ChatSession, ChatMessage, init_db
from app.rag import process_and_store_document, smart_answer
from app.data_analysis import analyze_data_file
from app.auth import (
    hash_password, verify_password, create_token,
    get_current_user, require_admin, log_action
)
from app.agent import run_agent, call_tool_on_client, init_clients
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import shutil
from difflib import SequenceMatcher

from scripts.logger import logger

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unexpected error")
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_DIR = str(PROJECT_ROOT / "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
STATIC_DIR = str(Path(__file__).resolve().parent / "static")
_file_manifest_cache = {}  # filename -> (mtime, compact semantic preview)
_file_route_cache = {}     # repeated question + unchanged upload stack -> selected file

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
from app.workflows import router as workflow_router
app.include_router(workflow_router)

# Request models
class QueryRequest(BaseModel):
    question: str
    session_id: Optional[int] = None
    file_scope: Literal["auto", "all", "selected"] = "auto"
    selected_files: list[str] = Field(default_factory=list)

class ApprovalSubmitRequest(BaseModel):
    session_id: int
    approval_id: int
    approved: bool

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "employee"

class TicketRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=10000)
    priority: Literal['low', 'medium', 'high'] = "medium"

class TicketUpdateRequest(BaseModel):
    status: Optional[Literal['open', 'in_progress', 'resolved', 'escalated']] = None
    assigned_to: Optional[str] = None

class ReminderRequest(BaseModel):
    message: str
    due_date: Optional[str] = None

class AnalyzeRequest(BaseModel):
    question: str
    filename: Optional[str] = None

class ChatMessageRequest(BaseModel):
    role: str
    content: str
    is_html: bool = False

# Startup
@app.on_event("startup")
def startup_event():
    init_db()
    db = next(get_db())
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        admin_user = User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin"
        )
        db.add(admin_user)
        db.commit()
    db.close()

# Frontend
@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# Auth
@app.post("/auth/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_token(user.username, user.role)
    log_action(db, user.username, "login", "User logged in")

    return {"token": token, "username": user.username, "role": user.role}

@app.post("/auth/register")
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == request.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    new_user = User(
        username=request.username,
        password_hash=hash_password(request.password),
        role=request.role
    )
    db.add(new_user)
    db.commit()

    token = create_token(new_user.username, new_user.role)
    log_action(db, new_user.username, "register", f"New {request.role} account created")

    return {"token": token, "username": new_user.username, "role": new_user.role}

# Documents
@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    if not file.filename.endswith((".pdf", ".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only PDF, CSV, and Excel files are supported.")

    upload_dir = UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    if file.filename.endswith(".csv"):
        file_type = "csv"
    elif file.filename.endswith((".xlsx", ".xls")):
        file_type = "excel"
    else:
        file_type = "pdf"

    if file_type == "pdf":
        try:
            chunks_processed = process_and_store_document(file_path, file.filename)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")
    else:
        chunks_processed = 0  # CSV/Excel files are analyzed on-demand

    db_doc = DocumentMetadata(
        filename=file.filename,
        file_type=file_type,
        uploaded_by=user["username"]
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    # PDF, CSV, and Excel files stay in ./uploads for stack tracking and priority ranking
    log_action(db, user["username"], "upload", f"Uploaded {file.filename} ({file_type})")

    return {"message": "File processed successfully", "chunks": chunks_processed, "file_type": file_type, "document_id": db_doc.id}

# Query (smart mode with auto data detection)
def _get_uploaded_data_files() -> list:
    """List uploaded CSV, Excel, and PDF files, newest first."""
    upload_dir = UPLOAD_DIR
    if not os.path.exists(upload_dir):
        return []
    files = [
        f for f in os.listdir(upload_dir)
        if f.endswith((".csv", ".xlsx", ".xls", ".pdf"))
    ]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(upload_dir, f)), reverse=True)
    return files

def _find_best_file(question: str, available_files: list, context: str = "") -> str:
    """Choose the file most relevant to the question and move it to the top of the stack."""
    if not available_files:
        return None
        
    if len(available_files) == 1:
        _auto_touch_file(available_files[0])
        return available_files[0]

    route_signature = tuple(
        (filename, os.path.getmtime(os.path.join(UPLOAD_DIR, filename)))
        for filename in available_files
        if os.path.exists(os.path.join(UPLOAD_DIR, filename))
    )
    route_key = (question.strip().lower(), route_signature)
    if route_key in _file_route_cache:
        return _file_route_cache[route_key]

    upload_dir = UPLOAD_DIR
    manifest = []
    for f in available_files:
        f_path = os.path.join(upload_dir, f)
        try:
            mtime = os.path.getmtime(f_path)
            cached = _file_manifest_cache.get(f)
            if cached and cached[0] == mtime:
                manifest.append(cached[1])
                continue
        except OSError:
            mtime = None
        if f.endswith((".csv", ".xlsx", ".xls")):
            try:
                import pandas as pd
                df = pd.read_csv(f_path, nrows=3) if f.endswith('.csv') else pd.read_excel(f_path, nrows=3)
                cols = list(df.columns)
                manifest.append(f"• Dataset [{f}]: Columns={cols[:8]}")
            except Exception:
                manifest.append(f"• Dataset [{f}]")
        elif f.endswith(".pdf"):
            try:
                from app.rag import _extract_text_from_pdf
                txt = _extract_text_from_pdf(f_path)[:350].replace('\n', ' ')
                manifest.append(f"• PDF Document [{f}]: Content Preview='{txt}'")
            except Exception:
                manifest.append(f"• PDF Document [{f}]")

        if mtime is not None:
            _file_manifest_cache[f] = (mtime, manifest[-1])

    from scripts.llm_router import ask_llm
    prompt = f"""You are an autonomous AI File Intelligence Router.
Read the user's inquiry, analyze the uploaded stack files and their content previews below, and comprehend the underlying semantic meaning.

Uploaded Stack Files & Semantic Content Previews:
{chr(10).join(manifest)}

Recent Conversation Context:
{context}

User Inquiry: "{question}"

Instructions:
- If the inquiry is a general knowledge question, world fact, news, country leader, math, coding question, or general query NOT related to any uploaded stack file, respond with ONLY: "GENERAL_KNOWLEDGE".
- Otherwise, respond with ONLY the exact filename of the most relevant file from the list above, and nothing else."""

    try:
        # File selection is a short classification task. Do not let a large
        # manifest accidentally route it to the slow heavy-analysis model.
        decision = ask_llm(prompt, max_tokens=60, tier="fast").strip()
        if "GENERAL_KNOWLEDGE" in decision:
            selected = "GENERAL_KNOWLEDGE"
        else:
            selected = next((f for f in available_files if f in decision), available_files[0])
        if len(_file_route_cache) >= 256:
            _file_route_cache.clear()
        _file_route_cache[route_key] = selected
        return selected
    except Exception:
        pass

    return available_files[0]

def _auto_touch_file(filename: str):
    """Move a file to the top of the stack when the user references it."""
    if not filename:
        return
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        import time
        try:
            os.utime(file_path, (time.time(), time.time()))
        except Exception:
            pass

import re

def _markdown_to_clean_html(text: str) -> str:
    """Convert Markdown to HTML and remove leftover asterisks."""
    if not text:
        return ""
    
    text = re.sub(r'^###\s+(.*)$', r'<h4 style="color:var(--accent-cyan); margin-top:14px; margin-bottom:6px; font-size:14px; font-weight:600;">\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.*)$', r'<h3 style="color:#ffffff; margin-top:16px; margin-bottom:8px; font-size:15px; font-weight:700;">\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.*)$', r'<h2 style="color:#ffffff; margin-top:18px; margin-bottom:10px; font-size:16px; font-weight:700;">\1</h2>', text, flags=re.MULTILINE)
    
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong style="color:#ffffff; font-weight:600;">\1</strong>', text)
    text = re.sub(r'__(.*?)__', r'<strong style="color:#ffffff; font-weight:600;">\1</strong>', text)
    
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    
    text = text.replace('*', '')
    
    lines = text.split('\n')
    formatted_lines = []
    in_list = False
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(('- ', '• ')):
            content = stripped[2:].strip()
            if not in_list:
                formatted_lines.append('<ul style="margin:8px 0; padding-left:18px; line-height:1.6;">')
                in_list = True
            formatted_lines.append(f'<li style="margin-bottom:4px; color:var(--text-main);">{content}</li>')
        else:
            if in_list:
                formatted_lines.append('</ul>')
                in_list = False
            if stripped:
                if not stripped.startswith('<h') and not stripped.startswith('<ul') and not stripped.startswith('<div'):
                    formatted_lines.append(f'<p style="margin:6px 0; line-height:1.6;">{stripped}</p>')
                else:
                    formatted_lines.append(stripped)
                    
    if in_list:
        formatted_lines.append('</ul>')
        
    return '\n'.join(formatted_lines)

def approval_payload(row):
    import json
    args = json.loads(row.tool_arguments) if isinstance(row.tool_arguments, str) else row.tool_arguments
    if isinstance(args, dict) and args.get('_approval_version') == 2:
        args = args['arguments']
    return {"mode": "pending_approval", "approval_id": row.id, "session_id": row.session_id,
            "tool_name": row.tool_name, "tool_arguments": args,
            "answer": "Review this action, then choose Approve & send or Reject below."}


def save_approval(db, username, session_id, tool_name, tool_arguments, status='pending'):
    from app.database import ApprovalRequest
    if tool_name.endswith('send_email') and status == 'pending':
        import re
        if not all(isinstance(tool_arguments.get(key), str) and tool_arguments[key].strip() for key in ('to', 'subject', 'body')) or not re.fullmatch(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', tool_arguments['to']):
            raise HTTPException(status_code=400, detail='A complete recipient, subject and body are required before email approval.')
    row = ApprovalRequest(username=username, session_id=session_id, tool_name=tool_name, tool_arguments={'_approval_version': 2, 'arguments': tool_arguments}, status=status)
    db.add(row)
    db.commit()
    db.refresh(row)
    return approval_payload(row)


@app.get("/query/pending-approvals")
def pending_approvals(session_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    from app.database import ApprovalRequest
    rows = db.query(ApprovalRequest).filter_by(username=user['username'], session_id=session_id, status='pending').order_by(ApprovalRequest.id).all()
    # Older versions never updated approval statuses after sending, so their
    # pending rows cannot safely be treated as currently awaiting approval.
    import json
    return [approval_payload(row) for row in rows if isinstance((args := json.loads(row.tool_arguments) if isinstance(row.tool_arguments, str) else row.tool_arguments), dict) and args.get('_approval_version') == 2]


@app.post("/query/image")
async def query_image(
    image: UploadFile = File(...),
    question: str = Form("Help me understand and fix the problem shown in this image."),
    session_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    import asyncio
    from app.image_support import MAX_IMAGE_BYTES, prepare_image
    from scripts.llm_router import ask_image

    if len(question) > 8000:
        raise HTTPException(status_code=400, detail="Please shorten your question to 8,000 characters.")
    context = ''
    if session_id is not None:
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id, ChatSession.username == user['username'],
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.desc()).limit(4).all()
        context = '\n'.join(f'{message.role}: {message.content[:2000]}' for message in reversed(messages))
    try:
        content = await image.read(MAX_IMAGE_BYTES + 1)
        encoded = await asyncio.to_thread(prepare_image, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await image.close()
    try:
        answer = await asyncio.to_thread(ask_image, question.strip() or 'Explain the problem in this image.', encoded, context)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    log_action(db, user['username'], 'image_query', 'Analyzed a chat image attachment')
    return {'answer': answer, 'mode': 'image_troubleshooting'}


@app.post("/query")
async def query_assistant(
    request: QueryRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    from html import escape
    import re
    if re.search(r'\b(?:create|add|make|set)\s+(?:me\s+)?(?:a\s+)?(?:personal\s+)?tasks?\b|\b(?:add|put)\b.*\b(?:my task list|my to-do list)\b', request.question, re.I):
        from app.workflows import plan_notes
        return {'mode': 'task_plan', 'answer': 'Review the suggested tasks below. They are saved only when you click Add task.', **await plan_notes(request.question, meeting=False)}
    if re.search(r'\b(?:meeting notes|meeting minutes)\b', request.question, re.I) and re.search(r'\b(?:summarize|summary|extract|action items)\b', request.question, re.I):
        from app.workflows import analyze_meeting, MeetingRequest
        filename = next((f for f in request.selected_files if f.lower().endswith('.pdf')), None)
        result = await analyze_meeting(MeetingRequest(notes=request.question, filename=filename), user)
        return {'answer': result['summary'], **result}
    # A conversational approval is never a document question and never sends
    # silently. Re-display the persisted action for an explicit button click.
    if re.fullmatch(r"(?:yes|yeah|ok|okay)?[ ,]*(?:i )?(?:approve(?: it)?|approved|confirm(?: it)?)[.! ]*", request.question.strip(), re.I):
        rows = pending_approvals(request.session_id, db, user) if request.session_id else []
        return rows[-1] if rows else {"answer": "There is no pending action in this conversation. Please ask me to prepare the email again; I will show a review card before sending."}

    # Reuse the actual prior draft rather than asking a model to reconstruct it.
    recipient = re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', request.question)
    if request.session_id and re.search(r'\b(send|forward|email)\b', request.question, re.I) and re.search(r'\b(also|again|same|too|it)\b', request.question, re.I) and not re.search(r"\b(draft|compose|write|change|add|remove|update|instead)\b|\b(don't|do not|never)\s+(send|email|forward)\b", request.question, re.I):
        from app.database import ApprovalRequest
        import json
        prior = db.query(ApprovalRequest).filter(
            ApprovalRequest.username == user['username'], ApprovalRequest.session_id == request.session_id,
            ApprovalRequest.tool_name.like('%send_email'), ApprovalRequest.status != 'rejected',
        ).order_by(ApprovalRequest.id.desc()).first()
        if prior:
            args = dict(approval_payload(prior)['tool_arguments'])
            if args.get('subject') and args.get('body'):
                if recipient:
                    args['to'] = recipient.group(0)
                if not args.get('to'):
                    return {'answer': 'Who should receive this draft? Please provide the email address.'}
                return save_approval(db, user['username'], request.session_id, prior.tool_name, args)
    email_request = bool(
        re.search(r'\b(draft|compose|write|send|email|mail|forward)\b', request.question, re.I)
        and (re.search(r'\b(e-?mail|smtp)\b', request.question, re.I)
             or re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', request.question))
    )
    available_files = _get_uploaded_data_files()
    support_request = bool(re.search(r'\b(?:create|open|raise|submit|log|show|list|view|check)\b.*\b(?:support\s+)?tickets?\b', request.question, re.I))
    if support_request:
        available_files = []
    explicit_scope = request.file_scope != "auto"
    if support_request:
        explicit_scope = False
    if request.file_scope == "selected" and not support_request:
        selected = list(dict.fromkeys(request.selected_files))
        if not selected:
            raise HTTPException(status_code=400, detail="Select at least one file or switch to All files / Auto.")
        if any(filename not in available_files for filename in selected):
            raise HTTPException(status_code=400, detail="A selected file is no longer available. Refresh the file list and select again.")
        available_files = selected
    if explicit_scope and not available_files:
        raise HTTPException(status_code=400, detail="Upload a file before using this file scope.")
    
    context_str = ""
    if request.session_id and not explicit_scope:
        from app.database import ChatMessage
        history = db.query(ChatMessage).filter(
            ChatMessage.session_id == request.session_id
        ).order_by(ChatMessage.created_at.desc()).limit(3).all()
        history.reverse()
        if history:
            context_str = "\nRecent Conversation History:\n" + "\n".join([f"{msg.role}: {msg.content}" for msg in history])

    if available_files and not email_request:
        upload_dir = UPLOAD_DIR
        q_lower = request.question.lower()
        
        is_explicit_plural = any(phrase in q_lower for phrase in [
            "what are the files about", "summarize all files", "summarize all documents",
            "compare files", "all uploaded files", "entire stack", "across all files",
            "compare datasets", "synthesize stack", "all documents", "all files"
        ])

        is_generic_singular = any(phrase in q_lower for phrase in [
            "what is the file about", "summarize the file", "tell me about the file",
            "what is the document about", "summarize the document", "what is this file",
            "what is this document", "about the file", "about this file", "about the pdf", "about the csv"
        ])
        # Explicit scope wins over natural-language routing, even if a prompt
        # mentions "all files" or a filename outside the selected subset.
        if explicit_scope:
            is_explicit_plural = len(available_files) > 1
            is_generic_singular = True
        
        # Keep simple greetings local and deterministic. This avoids a needless
        # model round-trip and guarantees that an empty model response cannot
        # reach the UI as its generic "Completed action." fallback.
        simple_greetings = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
        if q_lower.strip() in simple_greetings:
            ans = "Hello! How can I help you today?"
            from app.rl_engine import auto_reward_execution
            auto_reward_execution(db, "conversational", success=True, query_text=request.question, response_length=len(ans))
            return {"answer": ans, "mode": "conversational"}

        conversational_prompts = {"how are you", "who are you", "what can you do", "thanks", "thank you"}
        if q_lower.strip() in conversational_prompts:
            from scripts.llm_router import ask_llm
            gen_prompt = f"""You are an intelligent, friendly, and professional AI Employee Assistant.
Respond warmly and concisely to the user.

User: {request.question}"""
            try:
                raw_ans = ask_llm(gen_prompt, max_tokens=180, tier="fast").strip()
                if raw_ans:
                    ans = _markdown_to_clean_html(raw_ans)
                    from app.rl_engine import auto_reward_execution
                    auto_reward_execution(db, "conversational", success=True, query_text=request.question, response_length=len(ans))
                    return {"answer": ans, "mode": "conversational"}
            except Exception:
                pass

        if not is_explicit_plural:
            target_file = available_files[0] if is_generic_singular else _find_best_file(request.question, available_files, context_str)
            if not target_file:
                target_file = available_files[0]

            if target_file == "GENERAL_KNOWLEDGE":
                from scripts.llm_router import ask_llm
                gen_prompt = f"""You are an intelligent AI Enterprise Assistant equipped with comprehensive world knowledge.
Answer the user's inquiry directly, accurately, and professionally using your full general knowledge.

User Inquiry: "{request.question}"
"""
                try:
                    raw_ans = ask_llm(gen_prompt, max_tokens=350, tier="main").strip()
                    ans = _markdown_to_clean_html(raw_ans)
                    ans += f'''
                    <div style="font-size:11px; color:var(--text-muted); margin-top:12px; display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); padding:8px 12px; border-radius:6px; border:1px solid rgba(255,255,255,0.05);">
                        <span>🌐 <b>General Knowledge</b></span>
                        <span style="color:var(--accent-cyan); font-family:\'JetBrains Mono\',monospace; font-size:10px;">Model response</span>
                    </div>'''
                    from app.rl_engine import auto_reward_execution
                    auto_reward_execution(db, "general_knowledge", success=True, query_text=request.question, response_length=len(ans))
                    return {"answer": ans, "mode": "general_knowledge"}
                except Exception as e:
                    target_file = available_files[0]

            target_file_path = os.path.join(upload_dir, target_file)
            is_top = (target_file == available_files[0])
            badge_rank = "Selected file" if explicit_scope else "Automatically matched file"
            
            if target_file.endswith(".pdf"):
                from app.rag import generate_answer
                rag_res = generate_answer(request.question, filenames=[target_file])
                ans = _markdown_to_clean_html(rag_res.get("answer", "Document analysis complete."))
                from app.document_evidence import citations_html
                ans += citations_html(rag_res.get('citations', []))
                ans += f'''
                <div style="font-size:11px; color:var(--text-muted); margin-top:12px; display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); padding:8px 12px; border-radius:6px; border:1px solid rgba(255,255,255,0.05);">
                    <span>📄 <b>{escape(target_file)}</b> ({badge_rank})</span>
                    <span style="color:var(--accent-cyan); font-family:\'JetBrains Mono\',monospace; font-size:10px;">Selected document</span>
                </div>'''
                from app.rl_engine import auto_reward_execution
                auto_reward_execution(db, "single_file_priority", success=True, query_text=request.question, response_length=len(ans))
                return {"answer": ans, "mode": "single_file_priority", "file_used": target_file}
            else:
                analysis_q = request.question
                if len(request.question.split()) <= 8 and context_str:
                    analysis_q = f"{request.question} (Context: {context_str.strip()})"
                res = analyze_data_file(target_file_path, analysis_q)
                ans = _markdown_to_clean_html(res.get("analysis", "Data analysis complete."))
                from app.analysis_evidence import analysis_details_html
                ans += analysis_details_html(res.get('explanation'))
                if res.get("chart"):
                    ans += f'<img src="data:image/png;base64,{res["chart"]}" style="width:100%; border-radius:10px; margin-top:12px;">'
                summary = res.get("summary")
                rows_cnt = f"{summary.get('rows', 0):,} records" if summary else "Dataset"
                ans += f'''
                <div style="font-size:11px; color:var(--text-muted); margin-top:12px; display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); padding:8px 12px; border-radius:6px; border:1px solid rgba(255,255,255,0.05);">
                    <span>📊 <b>{escape(target_file)}</b> ({badge_rank} | {rows_cnt})</span>
                    <span style="color:var(--accent-cyan); font-family:\'JetBrains Mono\',monospace; font-size:10px;">Selected dataset</span>
                </div>'''
                from app.rl_engine import auto_reward_execution
                auto_reward_execution(db, "single_file_priority", success=True, query_text=request.question, response_length=len(ans))
                return {"answer": ans, "mode": "single_file_priority", "file_used": target_file}
        else:
            csv_files = [f for f in available_files if f.endswith((".csv", ".xlsx", ".xls"))]
            pdf_files = [f for f in available_files if f.endswith(".pdf")]
            
            stack_contexts = []
            chart_base64 = None
            used_files = []
            retrieved_citations = []
            
            for csv_f in csv_files:
                try:
                    f_p = os.path.join(upload_dir, csv_f)
                    analysis_question = request.question
                    if len(request.question.split()) <= 8 and context_str:
                        analysis_question = f"{request.question} (Context: {context_str.strip()})"
                    res = analyze_data_file(f_p, analysis_question)
                    if res.get("analysis"):
                        stack_contexts.append(f"DATASET [{csv_f}] ANALYTIC INSIGHTS:\n{res['analysis']}")
                        used_files.append(csv_f)
                    if res.get("chart") and not chart_base64:
                        chart_base64 = res["chart"]
                except Exception:
                    pass
                    
            for pdf_f in pdf_files:
                try:
                    from app.rag import generate_answer
                    rag_res = generate_answer(request.question, filenames=[pdf_f])
                    retrieved_citations.extend(rag_res.get('citations', []))
                    if rag_res.get("answer") and rag_res.get("source_documents"):
                        stack_contexts.append(f"DOCUMENT [{pdf_f}] KNOWLEDGE:\n{rag_res['answer']}")
                        used_files.append(pdf_f)
                except Exception:
                    pass

            if stack_contexts:
                from scripts.llm_router import ask_llm
                fusion_prompt = f"""You are an Enterprise Forensic BI Analysis Engine.
The user has uploaded a Priority Stack containing multiple knowledge and data assets.
Synthesize an analysis using ONLY the file evidence below. These are the files in the user's active scope, not necessarily all uploaded files. Never invent cross-file totals or combine incompatible units, periods, or overlapping categories.

MULTI-FILE STACK INTELLIGENCE:
{chr(10).join(stack_contexts)}

USER INQUIRY: "{request.question}"

INSTRUCTIONS:
- Directly answer the inquiry incorporating information from ALL relevant uploaded files.
- Use clear formatting with headers and bullet points.
- Do NOT output any raw asterisks (*), markdown symbols, or file paths in the text.
- Explicitly attribute facts to their respective dataset or document."""

                try:
                    synthesized_analysis = ask_llm(fusion_prompt, max_tokens=700, tier="heavy").strip()
                    
                    answer_html = _markdown_to_clean_html(synthesized_analysis)
                    if chart_base64:
                        answer_html += f'<img src="data:image/png;base64,{chart_base64}" style="width:100%; border-radius:10px; margin-top:12px;">'
                    
                    badges_html = '<div style="font-size:11px; color:var(--text-muted); margin-top:12px; display:flex; flex-wrap:wrap; gap:8px; align-items:center; background:rgba(255,255,255,0.03); padding:8px 12px; border-radius:6px; border:1px solid rgba(255,255,255,0.05);">'
                    for idx, f in enumerate(used_files, start=1):
                        icon = "📄" if f.endswith(".pdf") else "📊"
                        p_label = "In scope"
                        badges_html += f'<span>{icon} <b>{escape(f)}</b> ({p_label})</span>'
                    badges_html += '<span style="color:var(--accent-cyan); font-family:\'JetBrains Mono\',monospace; font-size:10px; margin-left:auto;">Multi-file analysis</span></div>'
                    
                    answer_html += badges_html
                    from app.document_evidence import citations_html
                    answer_html += citations_html(retrieved_citations)
                    missing = [f for f in available_files if f not in used_files]
                    if missing:
                        from html import escape
                        answer_html += '<p>Could not retrieve evidence from: ' + ', '.join(escape(f) for f in missing) + '. This answer is incomplete for the requested scope.</p>'
                    
                    log_action(db, user["username"], "multi_stack_analyze", f"Cross-analyzed stack files {used_files}: {request.question[:80]}")
                    from app.rl_engine import auto_reward_execution
                    auto_reward_execution(db, "multi_file_stack_analysis", success=True, query_text=request.question, response_length=len(answer_html))
                    return {
                        "answer": answer_html,
                        "mode": "multi_file_stack_analysis",
                        "files_used": used_files
                    }
                except Exception as e:
                    pass

    if explicit_scope and not email_request:
        raise HTTPException(status_code=503, detail="Could not analyze the selected files. No other files were used. Please retry or narrow the selection.")

    try:
        if email_request:
            # Email is an action, not a PDF question. Gather scoped evidence,
            # then let the agent prepare the existing approval-gated SMTP call.
            evidence_files = available_files if explicit_scope else []
            if not explicit_scope and available_files and re.search(r'\b(this|that|it|information|document|documents|file|files|policy|report)\b', request.question, re.I):
                target = _find_best_file(request.question, available_files, context_str)
                if target in available_files:
                    evidence_files = [target]
            evidence = []
            for filename in evidence_files:
                question = f"Extract only the factual information needed for this email request. Do not send or discuss sending email: {request.question}"
                if filename.endswith('.pdf'):
                    from app.rag import generate_answer
                    content = generate_answer(question, filenames=[filename]).get('answer', '')
                else:
                    content = analyze_data_file(os.path.join(UPLOAD_DIR, filename), question).get('analysis', '')
                evidence.append(f"SOURCE: {filename}\n{content[:5000]}")
            result = await run_agent(
                request.question, user["username"], request.session_id, context_str,
                file_context='\n\n'.join(evidence) or 'No file evidence was requested or retrieved. Ask for clarification if the email content is unclear.',
            )
        else:
            result = await run_agent(request.question, user["username"], request.session_id, context_str)
        
        if result.get('mode') == 'email_draft':
            args = result['tool_arguments']
            save_approval(db, user['username'], request.session_id, 'send_email', args, status='draft')
            result = {'mode': 'email_draft', 'answer': '<p><strong>Email draft — not sent</strong></p><p>To: ' + escape(args.get('to') or 'Please specify a recipient') + '</p><p>Subject: ' + escape(args['subject']) + '</p><pre style="white-space:pre-wrap">' + escape(args['body']) + '</pre><p>Ask me to send it when you are ready. I will show an approval card.</p>'}
        if result.get("mode") == "pending_approval":
            result = save_approval(db, user['username'], request.session_id, result['tool_name'], result['tool_arguments'])

        log_action(
            db, user["username"], "query",
            f"[agent] Q: {request.question[:80]}"
        )
        return result
    except Exception as e:
        err_msg = str(e) if str(e).strip() else repr(e)
        raise HTTPException(status_code=500, detail=f"Agent error: {err_msg}")

@app.post("/query/approve")
async def approve_tool_call(
    request: ApprovalSubmitRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    from app.database import ApprovalRequest
    
    row = db.query(ApprovalRequest).filter_by(id=request.approval_id, username=user['username'], session_id=request.session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found in this conversation.")
    claimed = db.query(ApprovalRequest).filter_by(id=row.id, status='pending').update({'status': 'executing' if request.approved else 'rejected'}, synchronize_session=False)
    db.commit()
    if not claimed:
        raise HTTPException(status_code=409, detail="This action has already been handled. It was not executed again.")
    if not request.approved:
        return {"answer": "Tool execution was rejected.", "status": "rejected"}
    try:
        await init_clients()
        payload = approval_payload(row)
        if row.tool_name.split('.')[-1] == 'create_support_ticket':
            payload['tool_arguments']['created_by'] = user['username']
        result = await call_tool_on_client(row.tool_name, payload['tool_arguments'])
        result_text = result.content[0].text if result.content else str(result)
        if getattr(result, 'isError', False) or result_text.lower().startswith(('failed', 'error', 'mock email')):
            raise RuntimeError(result_text)
        row.status = 'approved'
        db.commit()
        log_action(db, user["username"], "tool_approved", f"Executed {row.tool_name}")
        return {"answer": f"Action executed successfully. Result: {result_text}", "status": "approved"}
    except Exception as e:
        row.status = 'failed'
        db.commit()
        raise HTTPException(status_code=502, detail=f"Could not confirm execution: {e}. Check delivery before requesting a new send.")

# Data analysis (direct endpoint, still available)
@app.post("/analyze")
async def analyze_data(
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    if not request.filename:
        available = _get_uploaded_data_files()
        if not available:
            raise HTTPException(status_code=404, detail="No data files uploaded yet.")
        request.filename = _find_best_file(request.question, available)
    
    file_path = os.path.join(UPLOAD_DIR, request.filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Data file not found. Please upload it first.")

    result = analyze_data_file(file_path, request.question)

    log_action(db, user["username"], "analyze", f"Analyzed {request.filename}: {request.question[:80]}")

    return result

@app.get("/data/files")
def list_data_files(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """List uploaded datasets and documents in priority order, newest first."""
    upload_dir = UPLOAD_DIR
    result = []
    seen = set()
    
    if os.path.exists(upload_dir):
        for f in os.listdir(upload_dir):
            if f.endswith((".csv", ".xlsx", ".xls", ".pdf")):
                f_path = os.path.join(upload_dir, f)
                try:
                    mtime = os.path.getmtime(f_path)
                    size = round(os.path.getsize(f_path) / 1024, 1)
                except OSError:
                    mtime = 0
                    size = 0
                file_type = "pdf" if f.endswith(".pdf") else ("excel" if f.endswith((".xlsx", ".xls")) else "csv")
                result.append({
                    "filename": f,
                    "size_kb": size,
                    "type": file_type,
                    "mtime": mtime
                })
                seen.add(f)
                
    pdfs = db.query(DocumentMetadata).filter(DocumentMetadata.file_type == "pdf").all()
    for pdf in pdfs:
        if pdf.filename not in seen:
            dt = getattr(pdf, 'upload_date', None) or getattr(pdf, 'created_at', None)
            mtime = dt.timestamp() if dt else 0
            result.append({
                "filename": pdf.filename,
                "size_kb": "Indexed",
                "type": "pdf",
                "mtime": mtime
            })
            seen.add(pdf.filename)
            
    result.sort(key=lambda x: x["mtime"], reverse=True)
    
    for idx, item in enumerate(result):
        item["priority"] = idx + 1
        item["is_top_priority"] = (idx == 0)
        
    return result

@app.delete("/data/files/{filename}")
def delete_data_file(filename: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a file from the server (filesystem and/or database/ChromaDB)."""
    deleted = False
    
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            deleted = True
        except Exception:
            pass
            
    db_docs = db.query(DocumentMetadata).filter(DocumentMetadata.filename == filename).all()
    if db_docs:
        from app.rag import delete_document
        delete_document(filename)
        for doc in db_docs:
            db.delete(doc)
        db.commit()
        deleted = True
        
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")

    from app.data_analysis import clear_file_cache
    clear_file_cache(file_path)
        
    log_action(db, user["username"], "delete", f"Deleted file: {filename}")
    return {"message": "File deleted successfully"}

@app.post("/data/files/{filename}/promote")
def promote_file_priority(filename: str, user: dict = Depends(get_current_user)):
    """Move a file to the top of the knowledge stack."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        import time
        now = time.time()
        os.utime(file_path, (now, now))
    return {"message": f"{filename} set as active priority", "filename": filename}

@app.get("/data/summary/{filename}")
def get_file_summary(filename: str, user: dict = Depends(get_current_user)):
    """Calculate revenue, record counts, audit risk, and outliers for the BI dashboard."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        return {"filename": filename, "records": "0 Records", "revenue": "$0.00M", "risk_status": "N/A", "risk_color": "#94a3b8", "outliers": 0}
    
    if filename.endswith((".csv", ".xlsx", ".xls")):
        try:
            import pandas as pd
            df = pd.read_csv(file_path) if filename.endswith('.csv') else pd.read_excel(file_path)
            rows = len(df)
            
            from app.analysis_evidence import explain_dataset
            try:
                explanation = explain_dataset(df, filename)
                total_sum = explanation['result']
                rev_str = f"{total_sum:,.2f}" if total_sum is not None else 'Mixed units — total withheld'
            except ValueError:
                explanation = {'warnings': ['No numeric measure found.'], 'columns': list(df.columns)}
                rev_str = 'No numeric measure'

            from app.data_analysis import detect_dataset_outliers
            outlier_res = detect_dataset_outliers(df)
            num_outliers = outlier_res.get("total_outliers", 0)
            pct_outliers = outlier_res.get("outlier_percentage", 0.0)

            if num_outliers > 0:
                risk_status = f"⚠️ {num_outliers} Outliers ({pct_outliers}%)"
                risk_color = "#ef4444" if pct_outliers > 5.0 else "#f59e0b"
            else:
                risk_status = "No statistical outliers detected"
                risk_color = "#10b981"

            return {
                "filename": filename,
                "records": f"{rows:,} Records",
                "revenue": rev_str,
                "risk_status": risk_status,
                "risk_color": risk_color,
                "outliers": num_outliers,
                "outlier_pct": pct_outliers,
                "solutions": outlier_res.get("solutions", []),
                "explanation": explanation
            }
        except Exception:
            return {"filename": filename, "records": "Data Available", "revenue": "N/A", "risk_status": "Analysis unavailable", "risk_color": "#94a3b8", "outliers": 0}
    elif filename.endswith(".pdf"):
        try:
            from app.rag import _extract_text_from_pdf
            txt = _extract_text_from_pdf(file_path)
            words = len(txt.split())
            return {
                "filename": filename,
                "records": f"{words:,} Words",
                "revenue": "Document Asset",
                "risk_status": "Indexed & Secure",
                "risk_color": "#06b6d4"
            }
        except Exception:
            return {"filename": filename, "records": "PDF Document", "revenue": "Knowledge Base", "risk_status": "Indexed", "risk_color": "#06b6d4"}
            
    return {"filename": filename, "records": "Active Asset", "revenue": "N/A", "risk_status": "Ready for analysis", "risk_color": "#06b6d4"}

@app.post("/data/clean/{filename}")
def clean_file_outliers(filename: str, user: dict = Depends(get_current_user)):
    """Cap extreme values and save a cleaned copy of the dataset."""
    try:
        file_path = os.path.join(UPLOAD_DIR, filename)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found in server uploads directory.")
        
        import time
        import pandas as pd
        from app.data_analysis import clean_dataset_outliers
        df = pd.read_csv(file_path) if filename.endswith('.csv') else pd.read_excel(file_path)

        df_clean, stats = clean_dataset_outliers(df, percentile_cap=95.0)
        cleaned_filename = f"cleaned_{filename}"
        if not cleaned_filename.endswith('.csv'):
            cleaned_filename += '.csv'
        cleaned_path = os.path.join(UPLOAD_DIR, cleaned_filename)

        df_clean.to_csv(cleaned_path, index=False)

        now = time.time()
        os.utime(cleaned_path, (now, now))

        return {
            "message": f"Successfully Winsorized {stats.get('records_capped', 0)} extreme records in {filename}.",
            "cleaned_filename": cleaned_filename,
            "stats": stats
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error cleaning dataset outliers")
        raise HTTPException(status_code=500, detail=f"Failed to clean dataset: {str(e)}")

@app.get("/data/compare")
def compare_datasets(file1: str, file2: str, user: dict = Depends(get_current_user)):
    """Calculate comparison metrics for two datasets."""
    s1 = get_file_summary(file1, user)
    s2 = get_file_summary(file2, user)
    return {
        "file1": s1,
        "file2": s2
    }

@app.get("/rl/stats")
def get_rl_stats(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """Return routing policy weights and feedback statistics."""
    from app.rl_engine import RLEngine
    rl = RLEngine(db)
    policy = rl.get_policy_summary()
    return policy

# Support tickets
@app.post("/tickets")
def create_ticket(
    request: TicketRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    ticket = SupportTicket(
        created_by=user["username"],
        subject=request.subject,
        description=request.description,
        priority=request.priority
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    from app.workflows import ticket_created
    ticket_created(db, ticket)
    db.commit()
    log_action(db, user["username"], "ticket", f"Created ticket: {request.subject}")

    return {"message": "Ticket created", "ticket_id": ticket.id}

@app.get("/tickets")
def get_tickets(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    if user["role"] == "admin":
        tickets = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).all()
    else:
        from sqlalchemy import or_
        tickets = db.query(SupportTicket).filter(
            or_(SupportTicket.created_by == user["username"], SupportTicket.assigned_to == user["username"])
        ).order_by(SupportTicket.created_at.desc()).all()

    return [
        {
            "id": t.id,
            "created_at": t.created_at.isoformat(),
            "created_by": t.created_by,
            "subject": t.subject,
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "assigned_to": t.assigned_to
        }
        for t in tickets
    ]

@app.put("/tickets/{ticket_id}")
def update_ticket(
    ticket_id: int,
    request: TicketUpdateRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin)
):
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    from app.workflows import update_ticket_record
    update_ticket_record(db, ticket, request, user)

    log_action(db, user["username"], "ticket_update", f"Updated ticket #{ticket_id}")

    return {"message": "Ticket updated"}

# Reminders
@app.post("/reminders")
def create_reminder(
    request: ReminderRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    from app.workflows import utc_date
    due = utc_date(request.due_date)

    reminder = Reminder(
        username=user["username"],
        message=request.message,
        due_date=due
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)

    log_action(db, user["username"], "reminder", f"Set reminder: {request.message[:50]}")

    return {"message": "Reminder created", "reminder_id": reminder.id}

@app.get("/reminders")
def get_reminders(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    reminders = db.query(Reminder).filter(
        Reminder.username == user["username"],
        Reminder.is_done == False
    ).order_by(Reminder.created_at.desc()).all()

    return [
        {
            "id": r.id,
            "message": r.message,
            "due_date": r.due_date.isoformat() + 'Z' if r.due_date else None,
            "created_at": r.created_at.isoformat()
        }
        for r in reminders
    ]

@app.put("/reminders/{reminder_id}/done")
def complete_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.username == user["username"]
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    reminder.is_done = True
    db.commit()
    return {"message": "Reminder completed"}

# Audit logs
@app.get("/audit-logs")
@app.get("/audit")
def get_audit_logs(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(100).all()
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "username": log.username,
            "user": log.username,
            "action": log.action,
            "details": log.details
        }
        for log in logs
    ]

# Executive deck & fraud watchdog
from fastapi.responses import Response

class PPTExportRequest(BaseModel):
    title: str = "Executive Data Briefing"
    summary_text: str
    chart_base64: str = None

@app.post("/export-ppt")
def export_ppt_deck(req: PPTExportRequest, user: dict = Depends(get_current_user)):
    from app.ppt_generator import create_executive_deck
    ppt_bytes = create_executive_deck(req.title, req.summary_text, req.chart_base64)
    return Response(
        content=ppt_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": "attachment; filename=Executive_Briefing_Deck.pptx"}
    )

class FraudAuditRequest(BaseModel):
    file_name: str = None

@app.post("/run-fraud-audit")
def run_fraud_audit(req: FraudAuditRequest = None, user: dict = Depends(get_current_user)):
    from app.fraud_watchdog import run_benford_fraud_audit
    files = _get_uploaded_data_files()
    if not files:
        raise HTTPException(status_code=400, detail="No dataset uploaded yet.")
    requested_file = req.file_name if req else None
    target_file = requested_file if (requested_file and requested_file in files) else files[0]
    file_path = os.path.join(UPLOAD_DIR, target_file)
    result = run_benford_fraud_audit(file_path)
    result["file_audited"] = target_file
    return result

class RLFeedbackRequest(BaseModel):
    mode_name: str
    reward: int  # +1 or -1
    query_text: str = ""
    user_comment: str = None

@app.post("/rl/feedback")
def submit_rl_feedback(
    req: RLFeedbackRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    from app.rl_engine import record_feedback
    res = record_feedback(db, req.mode_name, req.reward, req.query_text, req.user_comment)
    log_action(db, user["username"], "rl_feedback", f"Reward {req.reward} applied to mode {req.mode_name}")
    return res

@app.get("/rl/policy")
def get_rl_policy_summary(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    from app.rl_engine import get_policy_summary
    return get_policy_summary(db)

class ForecastRequest(BaseModel):
    filename: str
    value_column: str
    periods: int = 3

@app.post("/data/forecast")
def get_predictive_forecast(
    req: ForecastRequest,
    user: dict = Depends(get_current_user)
):
    from app.data_analysis import _get_cached_df, predict_trend_forecast, detect_dataset_outliers
    file_path = os.path.join(UPLOAD_DIR, req.filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested dataset file not found.")
        
    df = _get_cached_df(file_path)
    forecast_res = predict_trend_forecast(df, req.value_column, req.periods)
    outliers_res = detect_dataset_outliers(df, req.value_column)
    
    return {
        "filename": req.filename,
        "forecast": forecast_res,
        "anomalies": outliers_res
    }

class PDFExportRequest(BaseModel):
    title: str = "Executive Data & Financial Audit Briefing"
    summary_text: str
    chart_base64: str = None
    dataset_name: str = "Financial Ledger"

@app.post("/export-pdf")
def export_pdf_report(req: PDFExportRequest, user: dict = Depends(get_current_user)):
    from app.pdf_generator import generate_pdf_report
    pdf_bytes = generate_pdf_report(req.title, req.summary_text, req.chart_base64, req.dataset_name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Executive_Audit_Briefing.pdf"}
    )

class VarianceRequest(BaseModel):
    file_name: Optional[str] = None
    prev_year: Optional[str] = None
    curr_year: Optional[str] = None

@app.post("/run-variance-analysis")
def run_variance_endpoint(req: VarianceRequest = None, user: dict = Depends(get_current_user)):
    from app.variance_analyzer import run_variance_analysis
    files = _get_uploaded_data_files()
    if not files:
        raise HTTPException(status_code=400, detail="No dataset uploaded yet.")
    
    file_name = req.file_name if req and req.file_name else None
    prev_year = req.prev_year if req else None
    curr_year = req.curr_year if req else None
    
    target_file = file_name if file_name in files else files[0]
    file_path = os.path.join(UPLOAD_DIR, target_file)
    result = run_variance_analysis(file_path, prev_year=prev_year, curr_year=curr_year)
    result["file_audited"] = target_file
    return result

def _generate_smart_session_title(text: str) -> str:
    """Generate a short title for a chat session."""
    t_lower = text.lower().strip()
    if "leave" in t_lower or "expense" in t_lower or "policy" in t_lower:
        return "🏢 Policy & HR Review"
    elif "sales" in t_lower or "revenue" in t_lower or "chart" in t_lower or "plot" in t_lower:
        return "📊 Sales Revenue Analytics"
    elif "file" in t_lower or "about" in t_lower or "summary" in t_lower or "dataset" in t_lower:
        return "📄 File Analysis Audit"
    elif "prime minister" in t_lower or "mauritius" in t_lower or "1+1" in t_lower or "who is" in t_lower:
        return "🌐 General Intelligence QA"
    else:
        clean = re.sub(r'[^a-zA-Z0-9\s]', '', text).strip()
        words = clean.split()
        if len(words) > 5:
            return "💬 " + " ".join(words[:5]).title() + "..."
        elif words:
            return "💬 " + " ".join(words).title()
        return "💬 General Inquiry"

# Chat sessions
@app.post("/chat/sessions")
def create_chat_session(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    session = ChatSession(username=user["username"], title="New Chat")
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "session_id": session.id, "title": session.title, "created_at": session.created_at.isoformat()}

@app.get("/chat/sessions")
def list_chat_sessions(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    from sqlalchemy import select
    subq = select(ChatMessage.session_id).distinct()
    empty_sessions = db.query(ChatSession).filter(
        ChatSession.username == user["username"],
        ChatSession.id.notin_(subq)
    ).all()
    if empty_sessions:
        for es in empty_sessions:
            db.delete(es)
        db.commit()

    sessions = db.query(ChatSession).filter(
        ChatSession.username == user["username"]
    ).order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc()).limit(50).all()
    return [
        {
            "id": s.id,
            "session_id": s.id,
            "title": s.title,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat() if s.updated_at else s.created_at.isoformat()
        }
        for s in sessions
    ]

@app.get("/chat/sessions/{session_id}/messages")
def get_chat_messages(session_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.username == user["username"]
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.asc()).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "is_html": m.is_html,
            "created_at": m.created_at.isoformat()
        }
        for m in messages
    ]

@app.post("/chat/sessions/{session_id}/messages")
def add_chat_message(
    session_id: int,
    request: ChatMessageRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.username == user["username"]
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    msg = ChatMessage(
        session_id=session_id,
        role=request.role,
        content=request.content,
        is_html=request.is_html
    )
    db.add(msg)
    
    if (session.title == "New Chat" or session.title.startswith("what") or session.title.startswith("Analyze")) and request.role == "user":
        session.title = _generate_smart_session_title(request.content)
    
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)
    
    return {"id": msg.id, "session_title": session.title}

@app.delete("/chat/sessions/{session_id}")
def delete_chat_session(session_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.username == user["username"]
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"message": "Session deleted"}

# Health
@app.get("/health")
def health_check():
    return {"status": "healthy"}
