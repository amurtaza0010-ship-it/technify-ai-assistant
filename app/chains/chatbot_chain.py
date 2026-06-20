"""
TAIA Chatbot Chain — Phase 3
Member 3: Redis Persistent Conversation Memory

Replaces volatile Python dict (_memories = {}) with Redis so that
conversation history survives server restarts.

If Redis is not running, the code automatically falls back to in-memory
storage so the app never crashes.
"""

import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.config import get_settings
from app.prompts.templates import SYSTEM_PERSONA, ATTENDANCE_PROMPT, RESULTS_PROMPT, COURSE_PROMPT



# ── Step 1: Try to connect to Redis. Fall back to in-memory if unavailable. ──

_use_redis = False
_memories = {}  # fallback in-memory store

try:
    import redis
    from langchain_community.chat_message_histories import RedisChatMessageHistory

    _redis_client = redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
        socket_connect_timeout=2   # fail fast if Redis is not reachable
    )
    _redis_client.ping()           # raises ConnectionError if Redis is down
    _use_redis = True
    print("[TAIA] Redis connected. Using persistent session memory.")

except Exception as e:
    print(f"[TAIA] Redis not available ({e}). Using in-memory fallback.")


# ── Step 2: Helper — get history for a session ────────────────────────────────

def _get_history(session_id: str):
    """
    Return (list_of_messages, redis_history_object_or_None) for a session.

    - If Redis is available: loads full conversation history from Redis.
    - If not: uses the in-memory dict as fallback.
    Always prepends the System Persona message so the LLM stays in character.
    """
    if _use_redis:
        history = RedisChatMessageHistory(
            session_id=f"taia:{session_id}",
            url=os.getenv("REDIS_URL", "redis://localhost:6379/0")
        )
        msgs = [SystemMessage(content=SYSTEM_PERSONA)]
        msgs.extend(history.messages)   # previous turns loaded from Redis
        return msgs, history
    else:
        if session_id not in _memories:
            _memories[session_id] = [SystemMessage(content=SYSTEM_PERSONA)]
        return _memories[session_id], None


# ── Step 3: Helper — save exchange to history ─────────────────────────────────

def _save_to_history(session_id: str, human_msg: str, ai_msg: str, redis_history):
    """
    Persist the latest human + AI message pair.

    - Redis mode: appends to the Redis list (survives restarts).
    - Fallback mode: appends to the in-memory dict (lost on restart).
    """
    if _use_redis and redis_history is not None:
        redis_history.add_user_message(human_msg)
        redis_history.add_ai_message(ai_msg)
    else:
        if session_id in _memories:
            _memories[session_id].append(HumanMessage(content=human_msg))
            _memories[session_id].append(AIMessage(content=ai_msg))



# ── Step 4: Build the LLM model ───────────────────────────────────────────────

def get_chatbot_chain(session_id: str):
    """
    Create and return the ChatOpenAI LLM instance using central config.
    """
    settings = get_settings()
    
    api_key = settings.LLM_API_KEY
    base_url = settings.LLM_BASE_URL
    model_name = settings.LLM_MODEL

    # Guard: LangChain requires a non-empty key string
    if not api_key or len(api_key) < 5:
        api_key = "sk-placeholder-key-for-langchain"

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=0.3
    )


# ── Step 5: Main chat entry point ─────────────────────────────────────────────

# --- ISKE NEECHAY WALA CODE (generate_chat_response waghera) WAISE HI REHNE DEIN ---

async def generate_chat_response(session_id: str, user_message: str) -> str:
    """
    Send user_message to the LLM with full conversation history.
    Saves the exchange to Redis (or in-memory fallback) afterwards.
    """
    try:
        llm = get_chatbot_chain(session_id)

        # Load previous messages + system prompt
        messages, redis_history = _get_history(session_id)

        # Append the new user turn
        messages.append(HumanMessage(content=user_message))

        # Call the LLM
        response = await llm.ainvoke(messages)
        ai_text = response.content

        # Persist the exchange
        _save_to_history(session_id, user_message, ai_text, redis_history)

        return ai_text

    except Exception as e:
        print(f"LangChain Error: {e}")
        return f"I'm sorry, I encountered an error connecting to my AI brain. (Error: {e})"


# ── Step 6: Intent classifier ─────────────────────────────────────────────────

async def classify_intent_async(session_id: str, message: str, role: str = 'Student') -> str:
    """
    Use an LLM to classify the user's intent based on the message and conversation history.
    Used by main.py to decide which ERP endpoint to call before LLM.
    """
    try:
        llm = get_chatbot_chain(session_id)
        messages, _ = _get_history(session_id)
        
        # Extract the last 3 user/AI exchanges to provide context
        recent_history = []
        for msg in messages[-6:]:
            if isinstance(msg, HumanMessage):
                recent_history.append(f"User: {msg.content}")
            elif isinstance(msg, AIMessage):
                recent_history.append(f"AI: {msg.content}")
                
        history_text = "\n".join(recent_history)
        
        # Define valid intents based on role
        if role.lower() == 'faculty':
            valid_list = ['faculty_attendance', 'faculty_ungraded', 'faculty_at_risk', 'faculty_stats', 'general']
        elif role.lower() == 'admin':
            valid_list = ['admin_students', 'admin_admissions', 'admin_fees', 'admin_departments', 'general']
        else:
            valid_list = ['attendance', 'results', 'courses', 'timetable', 'fees', 'assignments', 'exams', 'study_plan', 'policy', 'general']
        
        prompt = f"""You are an Intent Classifier for a University ERP AI Assistant.
The user is a {role}.
Your task is to classify the user's latest message into EXACTLY ONE of the following intents:
{valid_list}

Recent Conversation History:
{history_text}

Latest User Message: {message}

Rules:
1. Output ONLY the exact intent string from the list above. Do not output quotes or extra text.
2. If the user asks a follow-up (e.g. "what about Database Systems?"), look at the history. If they were just asking about attendance, the intent is 'attendance'.
3. If no intent matches, output 'general'.

Intent:"""

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        intent = response.content.strip().strip("'\"").lower()
        
        if intent not in valid_list:
            return 'general'
        return intent
    except Exception as e:
        print(f"Intent Classification Error: {e}")
        return 'general'


# ── Step 7: Contextual response with ERP data ─────────────────────────────────

async def generate_contextual_response(sid: str, msg: str, data: str, intent: str) -> str:
    """
    Format a structured prompt using live ERP data and send it to the LLM.
    Called by main.py after fetching data from the Mock ERP API.
    """
    if intent == 'attendance':
        prompt = ATTENDANCE_PROMPT.format(
            student_id=sid, attendance_data=data, question=msg)
    elif intent == 'results':
        prompt = RESULTS_PROMPT.format(
            student_id=sid, results_data=data, question=msg)
    elif intent in ('courses', 'timetable'):
        prompt = COURSE_PROMPT.format(
            student_id=sid, course_data=data, question=msg)
    else:
        prompt = f'Data: {data}\nQuestion: {msg}'
    return await generate_chat_response(sid, prompt)