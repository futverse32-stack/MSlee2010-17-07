import sqlite3
from typing import Any
from config import DB_PATH
import logging

logger = logging.getLogger(__name__)

def init_user_table():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            rounds_played INTEGER DEFAULT 0,
            eliminations INTEGER DEFAULT 0,
            total_score INTEGER DEFAULT 0,
            last_score INTEGER DEFAULT 0,
            penalties INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

def init_group_table():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            games_played INTEGER DEFAULT 0
        )
        """
    )
    # Ensure games_played column exists (backward compatibility)
    c.execute("PRAGMA table_info(groups)")
    columns = [col[1] for col in c.fetchall()]
    if "games_played" not in columns:
        try:
            c.execute("ALTER TABLE groups ADD COLUMN games_played INTEGER DEFAULT 0")
        except Exception:
            logger.exception("Failed to alter groups table")
    conn.commit()
    conn.close()

def ensure_group_exists(group_id: int, title: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id FROM groups WHERE group_id = ?", (group_id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO groups (group_id, title, games_played) VALUES (?, ?, 0)",
            (group_id, title)
        )
    else:
        try:
            c.execute(
                "UPDATE groups SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE group_id = ?",
                (title, group_id)
            )
        except Exception:
            # Some older DBs may not have updated_at column; ignore gracefully
            pass
    conn.commit()
    conn.close()

def ensure_user_exists(user: Any):
    """`user` is an object with attributes id, first_name, username"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?)",
            (user.id, getattr(user, "first_name", ""), getattr(user, "username", ""))
        )
    else:
        try:
            c.execute(
                "UPDATE users SET first_name = ?, username = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (getattr(user, "first_name", ""), getattr(user, "username", ""), user.id),
            )
        except Exception:
            # ignore if updated_at missing
            pass
    conn.commit()
    conn.close()

def update_user_after_game(user_id: int, score_delta: int, won: bool, rounds_played: int, eliminated: bool, penalties: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?)", (user_id, "", ""))
    try:
        c.execute(
            """
            UPDATE users
            SET games_played = COALESCE(games_played,0) + 1,
                wins = COALESCE(wins,0) + ?,
                losses = COALESCE(losses,0) + ?,
                rounds_played = COALESCE(rounds_played,0) + ?,
                eliminations = COALESCE(eliminations,0) + ?,
                total_score = COALESCE(total_score,0) + ?,
                penalties = COALESCE(penalties,0) + ?,
                last_score = ?
            WHERE user_id = ?
            """,
            (1 if won else 0, 0 if won else 1, rounds_played, 1 if eliminated else 0, score_delta, penalties, score_delta, user_id)
        )
    except Exception:
        logger.exception("Failed to update user after game")
    conn.commit()
    conn.close()

def ensure_columns_exist():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    required_columns = {
        "games_played": "INTEGER DEFAULT 0",
        "wins": "INTEGER DEFAULT 0",
        "losses": "INTEGER DEFAULT 0",
        "rounds_played": "INTEGER DEFAULT 0",
        "eliminations": "INTEGER DEFAULT 0",
        "total_score": "INTEGER DEFAULT 0",
        "last_score": "INTEGER DEFAULT 0",
        "penalties": "INTEGER DEFAULT 0"
    }
    c.execute("PRAGMA table_info(users)")
    existing_columns = [col[1] for col in c.fetchall()]
    for col, col_type in required_columns.items():
        if col not in existing_columns:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            except Exception:
                logger.exception("Failed to add column %s", col)
    conn.commit()
    conn.close()
