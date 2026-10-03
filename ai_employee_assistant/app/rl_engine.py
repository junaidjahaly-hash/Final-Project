import math
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import RLFeedback, RLPolicyWeight, SessionLocal

DEFAULT_MODES = [
    "single_file_priority",
    "multi_file_stack_analysis",
    "general_knowledge",
    "predictive_forecast",
    "fraud_audit"
]

ALPHA = 0.1  # Learning rate
DISCOUNT = 0.95

def init_rl_weights(db: Session):
    """Initialize default Q-weights for routing modes if not present."""
    for mode in DEFAULT_MODES:
        existing = db.query(RLPolicyWeight).filter(RLPolicyWeight.mode_name == mode).first()
        if not existing:
            weight = RLPolicyWeight(
                mode_name=mode,
                q_value=100,  # Base initial Q-value = 1.00 (scaled x100)
                total_uses=0,
                positive_rewards=0,
                negative_rewards=0
            )
            db.add(weight)
    try:
        db.commit()
    except Exception:
        db.rollback()

def record_feedback(db: Session, mode_name: str, reward: int, query_text: str = "", comment: str = None) -> dict:
    """Record feedback (+1 or -1) and update the routing weight for the selected mode."""
    init_rl_weights(db)
    
    fb_entry = RLFeedback(
        query_text=query_text,
        mode_selected=mode_name,
        reward=reward,
        user_comment=comment
    )
    db.add(fb_entry)
    
    weight = db.query(RLPolicyWeight).filter(RLPolicyWeight.mode_name == mode_name).first()
    if not weight:
        weight = RLPolicyWeight(mode_name=mode_name, q_value=100, total_uses=0, positive_rewards=0, negative_rewards=0)
        db.add(weight)
        
    weight.total_uses += 1
    if reward > 0:
        weight.positive_rewards += 1
    else:
        weight.negative_rewards += 1
        
    target = reward * 100
    current_q = weight.q_value or 100
    new_q = int(current_q + ALPHA * (target - current_q))
    weight.q_value = max(10, min(500, new_q))  # Clamp between 10 and 500
    weight.updated_at = datetime.utcnow()
    
    try:
        db.commit()
        db.refresh(weight)
    except Exception:
        db.rollback()
        
    return {
        "status": "reward_applied",
        "mode": mode_name,
        "reward": reward,
        "new_q_value": weight.q_value / 100.0,
        "total_uses": weight.total_uses,
        "pos_count": weight.positive_rewards,
        "neg_count": weight.negative_rewards
    }

def auto_reward_execution(db: Session, mode_name: str, success: bool, query_text: str = "", response_length: int = 100) -> dict:
    """Reward successful executions with responses longer than 30 characters; penalize other results."""
    reward = 1 if (success and response_length > 30) else -1
    return record_feedback(db, mode_name, reward=reward, query_text=query_text, comment="Autonomous Self-Learning Reward Signal")


def get_policy_summary(db: Session) -> dict:
    """Return routing weights and feedback counts for each mode."""
    init_rl_weights(db)
    weights = db.query(RLPolicyWeight).all()
    summary = {}
    for w in weights:
        total = max(1, w.total_uses)
        satisfaction_rate = round((w.positive_rewards / total) * 100, 1)
        summary[w.mode_name] = {
            "q_score": round(w.q_value / 100.0, 2),
            "total_uses": w.total_uses,
            "positive_rewards": w.positive_rewards,
            "negative_rewards": w.negative_rewards,
            "satisfaction_rate_pct": satisfaction_rate
        }
    return summary
