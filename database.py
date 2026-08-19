import sqlite3
import os
import datetime
import difflib
import re
from config import DB_PATH

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            corrected_text TEXT NOT NULL
        )
    """)
    
    # Create dictionary table
    # learned: 1 if automatically learned via reinforcement learning, 0 if manually added
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dictionary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phrase TEXT UNIQUE NOT NULL,
            replacement TEXT NOT NULL,
            learned INTEGER DEFAULT 0,
            q_value REAL DEFAULT 1.0,
            reward_count INTEGER DEFAULT 0,
            penalty_count INTEGER DEFAULT 0,
            last_reward REAL DEFAULT 0.0
        )
    """)
    
    # Ensure RL columns exist for existing databases
    cursor.execute("PRAGMA table_info(dictionary)")
    existing_cols = [col[1] for col in cursor.fetchall()]
    if "q_value" not in existing_cols:
        cursor.execute("ALTER TABLE dictionary ADD COLUMN q_value REAL DEFAULT 1.0")
    if "reward_count" not in existing_cols:
        cursor.execute("ALTER TABLE dictionary ADD COLUMN reward_count INTEGER DEFAULT 0")
    if "penalty_count" not in existing_cols:
        cursor.execute("ALTER TABLE dictionary ADD COLUMN penalty_count INTEGER DEFAULT 0")
    if "last_reward" not in existing_cols:
        cursor.execute("ALTER TABLE dictionary ADD COLUMN last_reward REAL DEFAULT 0.0")
    
    # Create settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

def save_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value))
    )
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        val = row[0]
        # Try to parse boolean or integer
        if val.lower() == "true":
            return True
        if val.lower() == "false":
            return False
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                return val
    return default

def add_history_entry(raw_text, corrected_text):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO history (timestamp, raw_text, corrected_text) VALUES (?, ?, ?)",
        (timestamp, raw_text, corrected_text)
    )
    entry_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return entry_id

def update_history_entry(entry_id, new_corrected_text):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get the raw text to trigger learning
    cursor.execute("SELECT raw_text, corrected_text FROM history WHERE id = ?", (entry_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
        
    raw_text, old_corrected_text = row
    
    cursor.execute(
        "UPDATE history SET corrected_text = ? WHERE id = ?",
        (new_corrected_text, entry_id)
    )
    conn.commit()
    conn.close()
    
    # Learn from the correction!
    learn_corrections(raw_text, new_corrected_text)
            
            
    return True

def get_history(limit=50):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, timestamp, raw_text, corrected_text FROM history ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "timestamp": r[1], "raw_text": r[2], "corrected_text": r[3]} for r in rows]

def clear_history():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM history")
    conn.commit()
    conn.close()

def delete_history_entry(entry_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM history WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return True

def add_dictionary_entry(phrase, replacement, learned=0, q_value=None):
    phrase_clean = phrase.strip().lower()
    replacement_clean = replacement.strip()
    if not phrase_clean or not replacement_clean:
        return False
        
    if q_value is None:
        q_value = 0.8 if learned else 1.2

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Check if entry already exists to preserve existing RL Q-value if updated
        cursor.execute("SELECT q_value, reward_count, penalty_count FROM dictionary WHERE phrase = ?", (phrase_clean,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                "UPDATE dictionary SET replacement = ?, learned = ? WHERE phrase = ?",
                (replacement_clean, learned, phrase_clean)
            )
        else:
            cursor.execute(
                "INSERT INTO dictionary (phrase, replacement, learned, q_value, reward_count, penalty_count, last_reward) VALUES (?, ?, ?, ?, 0, 0, 0.0)",
                (phrase_clean, replacement_clean, learned, q_value)
            )
        conn.commit()
        success = True
    except sqlite3.Error:
        success = False
    finally:
        conn.close()
    return success

def update_rl_reward(phrase, reward):
    phrase_clean = phrase.strip().lower()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT q_value, reward_count, penalty_count FROM dictionary WHERE phrase = ?", (phrase_clean,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
        
    current_q = row[0] if row[0] is not None else 1.0
    reward_count = row[1] or 0
    penalty_count = row[2] or 0
    
    from rl_engine import RLEngine
    new_q = RLEngine.calculate_new_q_value(current_q, reward)
    
    if reward > 0:
        reward_count += 1
    else:
        penalty_count += 1
        
    cursor.execute(
        "UPDATE dictionary SET q_value = ?, reward_count = ?, penalty_count = ?, last_reward = ? WHERE phrase = ?",
        (new_q, reward_count, penalty_count, reward, phrase_clean)
    )
    conn.commit()
    conn.close()
    return {"phrase": phrase_clean, "q_value": new_q, "reward_count": reward_count, "penalty_count": penalty_count}

def delete_dictionary_entry(phrase):
    phrase = phrase.strip().lower()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM dictionary WHERE phrase = ?", (phrase,))
    conn.commit()
    conn.close()

def get_dictionary():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT phrase, replacement, learned, q_value, reward_count, penalty_count, last_reward FROM dictionary ORDER BY q_value DESC, phrase ASC")
    rows = cursor.fetchall()
    conn.close()
    return [{
        "phrase": r[0],
        "replacement": r[1],
        "learned": bool(r[2]),
        "q_value": r[3] if r[3] is not None else 1.0,
        "reward_count": r[4] or 0,
        "penalty_count": r[5] or 0,
        "last_reward": r[6] or 0.0,
    } for r in rows]

COMMON_WORDS = {
    # Numbers & Math
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "plus", "minus", "times", "divided", "equals", "percent", "dollar", "dollars",
    # Pronouns & Articles
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "their", "our", "mine", "yours", "hers", "theirs", "ours",
    "a", "an", "the", "this", "that", "these", "those",
    # Prepositions & Conjunctions
    "in", "on", "at", "to", "from", "by", "with", "about", "against", "between",
    "into", "through", "during", "before", "after", "above", "below", "of", "for",
    "and", "but", "or", "nor", "for", "yet", "so", "if", "because", "as", "until",
    # Common verbs & auxiliaries
    "is", "are", "am", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "go", "goes", "went", "gone",
    "get", "gets", "got", "getting", "make", "makes", "made", "making",
    "can", "could", "will", "would", "shall", "should", "may", "might", "must",
    # Question words
    "what", "why", "how", "who", "where", "when", "which",
    # Conversational & formatting words
    "yes", "no", "okay", "ok", "hello", "hi", "sorry", "thanks", "thank",
    # 200 Most common English nouns/adjectives/adverbs
    "sound", "take", "only", "little", "work", "know", "place", "year", "live", "back",
    "give", "most", "very", "thing", "just", "name", "good", "sentence", "man", "think",
    "say", "great", "help", "through", "much", "line", "right", "too", "mean", "old",
    "any", "same", "tell", "boy", "follow", "came", "want", "show", "also", "around",
    "farm", "small", "set", "home", "read", "hand", "port", "large", "spell", "add",
    "even", "land", "here", "big", "high", "such", "act", "ask", "men", "went",
    "light", "kind", "off", "need", "house", "picture", "try", "again", "animal", "point",
    "mother", "world", "near", "build", "self", "earth", "father", "head", "stand", "own",
    "page", "country", "found", "answer", "school", "grow", "study", "still", "learn",
    "plant", "cover", "food", "sun", "keep", "eye", "never", "last", "let", "thought",
    "city", "tree", "cross", "start", "story", "saw", "far", "sea", "draw", "left",
    "late", "run", "while", "press", "close", "night", "real", "life", "few", "north",
    "open", "seem", "together", "next", "white", "children", "begin", "got", "walk",
    "example", "ease", "paper", "group", "always", "music", "both", "mark", "often",
    "letter", "mile", "river", "car", "feet", "care", "book", "carry", "took",
    "science", "eat", "room", "friend", "began", "idea", "fish", "mountain", "stop",
    "once", "base", "hear", "horse", "cut", "sure", "watch", "color", "face", "wood",
    "main", "enough", "plain", "girl", "usual", "young", "ready", "ever", "red", "list",
    "though", "feel", "talk", "bird", "soon", "body", "dog", "family", "direct", "pose",
    "leave", "song", "measure", "door", "product", "black", "short", "numeral", "class",
    "wind", "question", "happen", "complete", "ship", "area", "half", "rock", "order",
    "fire", "south", "problem", "piece", "told", "knew", "pass", "since", "top",
    "whole", "king", "space", "heard", "best", "hour", "better", "true"
}

def strip_punctuation(text):
    if not text:
        return text
    punctuation = '.,?!;:"()[]{}\'`'
    return text.strip(punctuation)

def learn_corrections(raw_text, corrected_text):
    """
    Reinforcement learning: Diffs the raw transcription against the corrected text
    to extract mappings, and adds them to the dictionary.
    Only learns genuine word replacements — never capitalization-only changes.
    """
    # Clean double spaces and normalize
    raw_text = " ".join(raw_text.split())
    corrected_text = " ".join(corrected_text.split())
    
    raw_words = raw_text.split()
    corrected_words = corrected_text.split()
    
    matcher = difflib.SequenceMatcher(None, raw_words, corrected_words)
    opcodes = matcher.get_opcodes()
    
    learned_mappings = []
    
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'replace':
            raw_phrase = " ".join(raw_words[i1:i2])
            corrected_phrase = " ".join(corrected_words[j1:j2])
            
            clean_raw = strip_punctuation(raw_phrase).strip().lower()
            clean_raw = " ".join(clean_raw.split())
            
            clean_corr = strip_punctuation(corrected_phrase).strip()
            clean_corr = " ".join(clean_corr.split())
            
            # Skip if only difference is capitalization
            if clean_raw == clean_corr.lower():
                continue
            
            # Skip if raw phrase words are all common English words
            raw_tokens = clean_raw.split()
            if all(t in COMMON_WORDS for t in raw_tokens):
                continue
            
            # Learn only if both contain letters and are genuinely different
            if clean_raw and clean_corr and clean_raw != clean_corr:
                if any(c.isalpha() for c in clean_raw) and any(c.isalpha() for c in clean_corr):
                    if clean_raw not in COMMON_WORDS:
                        if add_dictionary_entry(clean_raw, clean_corr, learned=1):
                            learned_mappings.append((clean_raw, clean_corr))
            
            # Word-by-word learning if lengths match
            if (i2 - i1) > 1 and (i2 - i1) == (j2 - j1):
                for k in range(i2 - i1):
                    raw_w = raw_words[i1 + k]
                    corr_w = corrected_words[j1 + k]
                    
                    clean_rw = strip_punctuation(raw_w).strip().lower()
                    clean_cw = strip_punctuation(corr_w).strip()
                    
                    # Skip capitalization-only changes
                    if clean_rw == clean_cw.lower():
                        continue
                    
                    if clean_rw and clean_cw and clean_rw != clean_cw:
                        if any(c.isalpha() for c in clean_rw) and any(c.isalpha() for c in clean_cw):
                            if clean_rw not in COMMON_WORDS:
                                add_dictionary_entry(clean_rw, clean_cw, learned=1)
                        
    return learned_mappings

def apply_dictionary(text):
    """
    Applies learned and manual corrections to the input text, filtered by RL Q-values.
    """
    if not text:
        return text
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Filter rules by RL threshold (Q-value >= 0.4)
    cursor.execute("SELECT phrase, replacement, q_value FROM dictionary WHERE q_value IS NULL OR q_value >= 0.4")
    rows = cursor.fetchall()
    conn.close()
    
    # 1. Sort rules by Q-value (highest confidence first), then phrase length
    rules = sorted(rows, key=lambda x: (x[2] if x[2] is not None else 1.0, len(x[0])), reverse=True)
    
    corrected_text = text
    for phrase, replacement, q_val in rules:
        pattern = rf'\b{re.escape(phrase)}\b'
        
        def replace_match(match):
            matched_text = match.group(0)
            if matched_text.isupper():
                return replacement.upper()
            if matched_text[0].isupper():
                return replacement[0].upper() + replacement[1:] if len(replacement) > 1 else replacement.upper()
            return replacement
            
        corrected_text = re.sub(pattern, replace_match, corrected_text, flags=re.IGNORECASE)
        
    # 2. Fuzzy Auto-Correction:
    # Use known correct dictionary words to fix phonetic or minor spelling typos in new words
    known_replacements = list(set([r[1] for r in rules if r[1] and len(r[1]) > 3]))
    if known_replacements:
        words = corrected_text.split()
        new_words = []
        for w in words:
            clean_w = strip_punctuation(w)
            # Only apply fuzzy correction if word > 3 chars and NOT in common English words
            if clean_w and any(c.isalpha() for c in clean_w) and len(clean_w) > 3 and clean_w.lower() not in COMMON_WORDS:
                lower_repls = [r.lower() for r in known_replacements]
                if clean_w.lower() in lower_repls:
                    new_words.append(w)
                    continue
                    
                # Find close matches from the user's vocabulary with strict cutoff
                matches = difflib.get_close_matches(clean_w.lower(), lower_repls, n=1, cutoff=0.90)
                if matches:
                    matched_lower = matches[0]
                    original_cased = next(r for r in known_replacements if r.lower() == matched_lower)
                    corrected_word = w.replace(clean_w, original_cased)
                    new_words.append(corrected_word)
                else:
                    new_words.append(w)
            else:
                new_words.append(w)
        corrected_text = " ".join(new_words)
        
    return corrected_text

# Initialize DB on import
init_db()
