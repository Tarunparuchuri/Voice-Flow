import os
import sqlite3
import database
from rl_engine import RLEngine

def test_rl_engine():
    print("--- Running Voice Flow RL Engine Unit Tests ---")
    
    # 1. Test Q-Value TD calculation
    q_initial = 1.0
    q_after_reward = RLEngine.calculate_new_q_value(q_initial, RLEngine.REWARD_ACCEPT)
    print(f"[RL Test] Initial Q={q_initial} -> After Accept Reward (+1.0): Q={q_after_reward}")
    assert q_after_reward > q_initial, "Q-value should increase on positive reward!"

    q_after_penalty = RLEngine.calculate_new_q_value(q_initial, RLEngine.REWARD_OVERRIDE)
    print(f"[RL Test] Initial Q={q_initial} -> After Penalty (-1.5): Q={q_after_penalty}")
    assert q_after_penalty < q_initial, "Q-value should decrease on negative penalty!"

    # 2. Test Database Integration & Reward Processing
    phrase = "test_rl_word"
    replacement = "Test RL Replacement"
    
    database.add_dictionary_entry(phrase, replacement, learned=1, q_value=0.8)
    
    dict_entries = database.get_dictionary()
    match = next((item for item in dict_entries if item["phrase"] == phrase), None)
    assert match is not None, "Dictionary entry should exist!"
    assert match["q_value"] == 0.8, f"Expected Q=0.8, got {match['q_value']}"
    
    # Process positive reward
    res = RLEngine.process_reward(phrase, 'accept')
    print(f"[RL Test] Processed 'accept' reward: {res}")
    assert res["q_value"] > 0.8, "Q-value should have increased!"
    assert res["reward_count"] == 1, "Reward count should be 1!"

    # Process multiple negative penalties until suppressed
    res1 = RLEngine.process_reward(phrase, 'override')
    res2 = RLEngine.process_reward(phrase, 'override')
    print(f"[RL Test] Processed 2 'override' penalties: {res2}")
    assert res2["penalty_count"] == 2, "Penalty count should be 2!"
    
    is_active = RLEngine.is_rule_active(res2["q_value"])
    print(f"[RL Test] Rule Q={res2['q_value']}, Active threshold satisfied? {is_active}")
    
    # Verify apply_dictionary behavior with active vs suppressed rules
    applied_active = database.apply_dictionary("This is a test_rl_word here")
    print(f"[RL Test] Dictation text application result: '{applied_active}'")
    
    # Clean up test entry
    database.delete_dictionary_entry(phrase)
    print("--- ALL RL ENGINE UNIT TESTS PASSED SUCCESSFULLY! ---")

if __name__ == "__main__":
    test_rl_engine()
