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
    ensure_columns_exist()
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

# ----- Individual Group Stats -----------

def ensure_gstats_tables():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    ensure_columns_exist()
    c = conn.cursor()
    # Per-group, per-user rollups
    c.execute("""
    CREATE TABLE IF NOT EXISTS user_group_stats (
        user_id       INTEGER NOT NULL,
        group_id      INTEGER NOT NULL,
        first_name    TEXT,
        username      TEXT,
        games_played  INTEGER DEFAULT 0,
        wins          INTEGER DEFAULT 0,
        total_score   INTEGER DEFAULT 0,
        eliminations  INTEGER DEFAULT 0,
        penalties     INTEGER DEFAULT 0,
        updated_at    TEXT,
        PRIMARY KEY (user_id, group_id)
    )
    """)
    # Per-group overview
    c.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        group_id     INTEGER PRIMARY KEY,
        title        TEXT,
        games_played INTEGER DEFAULT 0,
        last_game_at TEXT
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ugs_group_updated ON user_group_stats(group_id, updated_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ugs_group_games ON user_group_stats(group_id, games_played)")
    conn.commit()
    conn.close()

from datetime import datetime

def record_group_game_end(group_id: int, group_title: str, players: list[int],
                          winners: list[int] = None,
                          scores: dict[int, int] = None,
                          elim_counts: dict[int, int] = None,
                          penalty_counts: dict[int, int] = None,
                          user_names: dict[int, tuple[str|None, str|None]] = None):
    winners = winners or []
    scores = scores or {}
    elim_counts = elim_counts or {}
    penalty_counts = penalty_counts or {}
    user_names = user_names or {}
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()

    # Upsert group row
    c.execute("""
        INSERT INTO groups (group_id, title, games_played, last_game_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(group_id) DO UPDATE SET
            title=excluded.title,
            games_played=groups.games_played+1,
            last_game_at=excluded.last_game_at
    """, (group_id, group_title, now))

    for uid in players:
        fn, un = user_names.get(uid, (None, None))
        c.execute("""
            INSERT INTO user_group_stats (user_id, group_id, first_name, username, games_played, wins, total_score, eliminations, penalties, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, group_id) DO UPDATE SET
              first_name = COALESCE(excluded.first_name, user_group_stats.first_name),
              username   = COALESCE(excluded.username,   user_group_stats.username),
              games_played = user_group_stats.games_played + 1,
              wins         = user_group_stats.wins + ?,
              total_score  = user_group_stats.total_score + ?,
              eliminations = user_group_stats.eliminations + ?,
              penalties    = user_group_stats.penalties + ?,
              updated_at   = excluded.updated_at
        """, (
            uid, group_id, fn, un,
            1 if uid in winners else 0,
            scores.get(uid, 0),
            elim_counts.get(uid, 0),
            penalty_counts.get(uid, 0),
            now,
            # for DO UPDATE
            1 if uid in winners else 0,
            scores.get(uid, 0),
            elim_counts.get(uid, 0),
            penalty_counts.get(uid, 0),
        ))

    conn.commit()
    conn.close()

# Active Groups Count Table

def ensure_games_table():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    ensure_columns_exist()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            ended_at TEXT    NOT NULL   -- UTC: 'YYYY-MM-DD HH:MM:SS'
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_games_ended_at ON games(ended_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_games_group ON games(group_id, ended_at)")
    conn.commit()
    conn.close()
