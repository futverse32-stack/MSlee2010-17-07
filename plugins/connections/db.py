# plugins/connections/db.py
import sqlite3
from telegram import Chat
from config import DB_PATH

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Users table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            eliminations INTEGER DEFAULT 0,
            total_score REAL DEFAULT 0,
            last_score REAL DEFAULT 0,
            penalties INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Groups table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            title TEXT,
            invite_link TEXT,
            added_by TEXT,
            games_played INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    conn.commit()
    conn.close()


def save_user(user) -> bool:
    """
    Save user to DB. Return True if it was a new user.
    `user` is telegram.User.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user.id,))
    existing = c.fetchone()
    is_new = False
    if not existing:
        c.execute(
            "INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?)",
            (user.id, user.first_name, user.username),
        )
        is_new = True
    else:
        c.execute(
            "UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (user.id,)
        )
    conn.commit()
    conn.close()
    return is_new


def save_group(chat: Chat, added_by: str):
    """
    Save group info to DB. `added_by` should be a string (username or name).
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM groups WHERE group_id = ?", (chat.id,))
    existing = c.fetchone()
    if not existing:
        invite_link = chat.invite_link if hasattr(chat, "invite_link") and chat.invite_link else "N/A"
        c.execute(
            "INSERT INTO groups (group_id, title, invite_link, added_by) VALUES (?, ?, ?, ?)",
            (chat.id, chat.title or "Private/Unknown", invite_link, added_by),
        )
    conn.commit()
    conn.close()
