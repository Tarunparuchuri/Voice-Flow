"""
Reinforcement Learning Engine for Voice Flow.
Implements Q-Learning / Contextual Bandit learning for dynamic text correction adaptation.
"""

import math
import database

class RLEngine:
    """
    Q-Learning Engine for Voice Flow Vocabulary & Correction Adaptation.
    
    Q-Value Update Equation:
        Q(s, a) = Q(s, a) + alpha * (R + gamma * Q_max - Q(s, a))
        
    Where:
        - alpha (Learning Rate) = 0.2
        - gamma (Discount Factor) = 0.9
        - R (Reward Signal):
            +1.0 : Positive feedback (user keeps/accepts candidate replacement)
            -1.5 : Negative feedback (user overrides/edits candidate replacement)
            +0.5 : Manual entry added by user in settings
    """

    ALPHA = 0.2       # Learning rate
    GAMMA = 0.9       # Discount factor
    MIN_Q_THRESHOLD = 0.4  # Minimum Q-value required to apply a correction rule
    
    REWARD_ACCEPT = 1.0
    REWARD_OVERRIDE = -1.5
    REWARD_MANUAL = 0.5

    @classmethod
    def calculate_new_q_value(cls, current_q: float, reward: float) -> float:
        """
        Computes updated Q-value using Temporal Difference Q-learning.
        """
        # Q-learning TD update: Q_new = Q_old + alpha * (reward + gamma * max_future_Q - Q_old)
        # For item-level contextual bandit, max_future_Q is current_q
        td_target = reward + cls.GAMMA * current_q
        td_error = td_target - current_q
        new_q = current_q + cls.ALPHA * td_error
        
        # Clamp Q-value between 0.0 and 5.0 for stability
        return round(max(0.0, min(5.0, new_q)), 3)

    @classmethod
    def process_reward(cls, phrase: str, reward_type: str) -> dict:
        """
        Processes a reward event for a phrase rule and updates database RL state.
        reward_type: 'accept', 'override', or 'manual'
        """
        if reward_type == 'accept':
            reward = cls.REWARD_ACCEPT
        elif reward_type == 'override':
            reward = cls.REWARD_OVERRIDE
        elif reward_type == 'manual':
            reward = cls.REWARD_MANUAL
        else:
            reward = float(reward_type)

        return database.update_rl_reward(phrase, reward)

    @classmethod
    def is_rule_active(cls, q_value: float) -> bool:
        """
        Returns True if the rule's Q-value satisfies the exploitation threshold.
        """
        return q_value >= cls.MIN_Q_THRESHOLD

    @classmethod
    def get_confidence_label(cls, q_value: float) -> tuple[str, str]:
        """
        Returns a human-readable badge text and color for Q-values in UI.
        """
        if q_value >= 1.5:
            return f"Q: {q_value:.2f} (High)", "#10B981"  # Emerald
        elif q_value >= 0.8:
            return f"Q: {q_value:.2f} (Good)", "#3B82F6"  # Blue
        elif q_value >= cls.MIN_Q_THRESHOLD:
            return f"Q: {q_value:.2f} (Moderate)", "#F59E0B"  # Amber
        else:
            return f"Q: {q_value:.2f} (Suppressed)", "#EF4444"  # Red
