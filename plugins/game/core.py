# plugins/game/core.py
import asyncio
import math
from typing import Dict, Optional
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config import DB_PATH, MIN_PLAYERS, MAX_PLAYERS, PICK_TIME_SEC , VIDEO_ELIMINATION, VIDEO_ROUND_ANNOUNCE, VIDEO_WINNER
from plugins.game.db import ensure_user_exists, update_user_after_game
import logging

logger = logging.getLogger(__name__)


# Active game registries (module-level)
active_games: Dict[int, "MindScaleGame"] = {}   # group_id -> game instance
user_active_game: Dict[int, int] = {}           # user_id -> group_id

class Player:
    def __init__(self, user_id: int, name: str, username: Optional[str] = None):
        self.user_id: int = user_id
        self.name: str = name
        self.username: Optional[str] = username
        self.current_number: Optional[int] = None
        self.score: int = 0
        self.eliminated: bool = False
        self.miss_offenses: int = 0
        self.total_penalties: int = 0
        self.rounds_played: int = 0
        self.timeout_count: int = 0
        self.timeout_penalty_applied: bool = False

    def __repr__(self):
        return f"<Player {self.name} ({self.user_id}) score={self.score} eliminated={self.eliminated}>"

class MindScaleGame:
    def __init__(self, group_id: int):
        self.group_id: int = group_id
        self.players: Dict[int, Player] = {}
        self.join_phase_active: bool = True
        self.round_number: int = 0
        self.current_round_active: bool = False
        self.pick_tasks: Dict[int, asyncio.Task] = {}
        self.pick_30_alerts: Dict[int, asyncio.Task] = {}
        self.score_history: list = []
        self.join_timer_task: Optional[asyncio.Task] = None
        self.round_results_sent: bool = False
        self.duplicate_rule_active: bool = False
        self.next_round_duplicate_active: bool = False
        self.ended: bool = False

    @property
    def active_players(self):
        return [p for p in self.players.values() if not p.eliminated]

    def add_player(self, user):
        if user.id not in self.players:
            p = Player(user.id, user.full_name, getattr(user, "username", None))
            self.players[user.id] = p
            user_active_game[user.id] = self.group_id

    def remove_player(self, user_id: int):
        if user_id in self.players:
            del self.players[user_id]
        user_active_game.pop(user_id, None)

    def reset_round_picks(self):
        for p in self.players.values():
            p.current_number = None

def mention_html(p: Player):
    return f"<a href='tg://user?id={p.user_id}'>{p.name}</a>"

async def start_round(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    if group_id not in active_games:
        return
    game = active_games[group_id]
    if game.current_round_active:
        return

    game.current_round_active = True
    game.round_number += 1
    game.reset_round_picks()
    game.round_results_sent = False

    # Cancel old tasks
    for t in list(game.pick_tasks.values()) + list(game.pick_30_alerts.values()):
        try:
            t.cancel()
        except:
            pass
    game.pick_tasks.clear()
    game.pick_30_alerts.clear()

    # Duplicate rule notice
    if getattr(game, "duplicate_rule_active", False):
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text="⚠️ Duplicate penalty rule is active this round! Picking the same number as 3 or more other players will result in a -1 point penalty.",
                parse_mode="HTML"
            )
        except:
            pass

    # announce round (video or text)
    bot_username = (await context.bot.get_me()).username or ""
    dm_url = f"https://t.me/{bot_username}"
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Send number in DM", url=dm_url)]])

    try:
        if VIDEO_ROUND_ANNOUNCE:
            await context.bot.send_video(
                chat_id=group_id,
                video=VIDEO_ROUND_ANNOUNCE,
                caption=f"𝗥𝗼𝘂𝗻𝗱 {game.round_number} \n🎲 Starting now! Send your number in DM!",
                reply_markup=buttons
            )
        else:
            await context.bot.send_message(chat_id=group_id, text=f"𝗥𝗼𝘂𝗻𝗱 {game.round_number} \n🎲 Starting now! Send your number in DM!", reply_markup=buttons)
    except:
        try:
            await context.bot.send_message(chat_id=group_id, text=f"𝗥𝗼𝘂𝗻𝗱 {game.round_number} \n🎲 Starting now! Send your number in DM!", reply_markup=buttons)
        except:
            pass

    players = game.active_players
    if not players:
        try:
            await context.bot.send_message(chat_id=group_id, text="❌ No active players. Ending game.")
        except:
            pass
        await end_game(context, group_id)
        return

    async def handle_miss(user_id: int):
        if group_id not in active_games or user_id not in game.players:
            return
        p = game.players.get(user_id)
        if not p or p.eliminated or p.current_number is not None:
            return

        if getattr(p, "timeout_count", 0) == 0:
            p.score -= 1
            p.total_penalties += 1
            p.timeout_count = 1
            p.current_number = "Skipped"
            try:
                await context.bot.send_message(chat_id=group_id, text=f"⚠️ {mention_html(p)} did not respond in time! -2 penalty.", parse_mode="HTML")
            except:
                pass
        else:
            p.eliminated = True
            try:
                await context.bot.send_message(chat_id=group_id, text=f"☠️ {mention_html(p)} failed again and is eliminated!", parse_mode="HTML")
            except:
                pass

        game.pick_tasks.pop(user_id, None)
        game.pick_30_alerts.pop(user_id, None)

        if group_id in active_games and all(pl.current_number is not None or pl.eliminated for pl in game.active_players):
            game.current_round_active = False
            await process_round_results(context, group_id)

    async def send_30_alert(user_id: int):
        if group_id not in active_games or user_id not in game.players:
            return
        p = game.players.get(user_id)
        if not p or p.eliminated or p.current_number is not None:
            return
        try:
            await context.bot.send_message(chat_id=group_id, text=f"⏳ {mention_html(p)} — 30 seconds left to send your number in DM!", parse_mode="HTML")
        except:
            pass

    for p in players:
        if p.eliminated: continue
        # DM instruction
        try:
            await context.bot.send_message(chat_id=p.user_id, text=f"🎯 𝗥𝗼𝘂𝗻𝗱 {game.round_number} \nSend a number between 0–100 .")
        except:
            try:
                await context.bot.send_message(chat_id=group_id, text=f"⚠️ Could not DM {mention_html(p)}. Please open your DM with the bot.", parse_mode="HTML")
            except:
                pass

        async def _alert(uid=p.user_id):
            await asyncio.sleep(PICK_TIME_SEC - 30)
            await send_30_alert(uid)
        t30 = asyncio.create_task(_alert())
        game.pick_30_alerts[p.user_id] = t30

        async def _timeout(uid=p.user_id):
            await asyncio.sleep(PICK_TIME_SEC)
            await handle_miss(uid)
        t_timeout = asyncio.create_task(_timeout())
        game.pick_tasks[p.user_id] = t_timeout

async def process_round_results(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    if group_id not in active_games:
        return
    game = active_games[group_id]
    if getattr(game, "round_results_sent", False):
        return
    game.round_results_sent = True

    picks = [(p.user_id, p.current_number) for p in game.active_players if isinstance(p.current_number, (int, float))]
    if not picks:
        try:
            await context.bot.send_message(chat_id=group_id, text="❌ No valid picks received this round.")
        except:
            pass
        await end_game(context, group_id)
        return

    nums = [n for _, n in picks]
    average = sum(nums) / len(nums)
    target = average * 0.8

    alive_players = [p for p in game.players.values() if not p.eliminated]

    # Reveal picks
    reveal_text = "𝗥𝗼𝘂𝗻𝗱 𝗣𝗶𝗰𝗸𝘀 \n\n"
    for p in game.active_players:
        pick_val = p.current_number if p.current_number is not None else "⏳ Skipped"
        reveal_text += f"♦️ {mention_html(p)} → {pick_val}\n"
    reveal_text += "▭▭▭▭▭▭▭▭▭▭▭▭▭▭"
    try:
        await context.bot.send_message(chat_id=group_id, text=reveal_text, parse_mode="HTML")
    except:
        pass

    # Duplicate detection & next-round scheduling
    num_alive = len(alive_players)
    counts = {}
    for uid, num in picks:
        counts[num] = counts.get(num, 0) + 1
    if any(count >= 4 for count in counts.values()):
        game.next_round_duplicate_active = True

    duplicate_players = set()
    duplicates_exist = False
    rule_applied = False
    if num_alive > 2 and getattr(game, "duplicate_rule_active", False):
        duplicate_nums = {num for num, count in counts.items() if count >= 4}
        if duplicate_nums:
            duplicates_exist = True
            rule_applied = True
        for p in game.active_players:
            if p.current_number in duplicate_nums:
                duplicate_players.add(p)
                p.score -= 1
                p.total_penalties += 1
                try:
                    await context.bot.send_message(chat_id=group_id, text=f"⚠️ {mention_html(p)} picked a duplicate number! -1 point penalty.", parse_mode="HTML")
                except:
                    pass

    # Closest number logic
    winner_players = []
    diffs = [(p, abs(p.current_number - target)) for p in alive_players if isinstance(p.current_number, (int, float))]
    if diffs:
        min_diff = min(d for _, d in diffs)
        winner_players = [p for p, d in diffs if d == min_diff and not p.eliminated]

    # 0 vs 100 special
    alive_now = [p for p in game.players.values() if not p.eliminated]
    zero_vs_hundred_case = False
    if len(alive_now) == 2:
        vals = [p.current_number for p in alive_now if isinstance(p.current_number, (int, float))]
        if 0 in vals and 100 in vals:
            p100 = next(p for p in alive_now if p.current_number == 100)
            winner_players = [p100]
            zero_vs_hundred_case = True
            for p in alive_now:
                if p != p100 and p not in duplicate_players:
                    p.score -= 1
                    p.total_penalties += 1

    # second elimination special
    special_penalty_applied = False
    num_eliminated = len([p for p in game.players.values() if p.eliminated])
    if num_eliminated >= 2 and not zero_vs_hundred_case and not duplicates_exist:
        exact_target_players = [p for p in alive_players if p.current_number == round(target)]
        if exact_target_players:
            winner_players = exact_target_players
            special_penalty_applied = True
            for p in alive_players:
                if p not in winner_players and p not in duplicate_players:
                    p.score -= 2
                    p.total_penalties += 2

    # non-winner penalties
    if not zero_vs_hundred_case:
        for p in alive_players:
            if p in duplicate_players:
                continue
            if p not in winner_players:
                if getattr(p, "timeout_penalty_applied", False):
                    continue
                if duplicates_exist:
                    continue
                if special_penalty_applied:
                    continue
                else:
                    p.score -= 1
                    p.total_penalties += 1

    # elimination check
    eliminated_now = []
    for p in list(game.players.values()):
        if not p.eliminated and p.score <= -10:
            p.eliminated = True
            eliminated_now.append(p)
    if eliminated_now and num_eliminated == 0:
        game.next_round_duplicate_active = True

    # Round results message
    res = f"𝗥𝗼𝘂𝗻𝗱 {game.round_number} 𝗥𝗲𝘀𝘂𝗹𝘁𝘀 \n\n"
    res += f"🎯 Target: {target:.2f}\n\n"
    if winner_players:
        winner_names = ", ".join([mention_html(p) for p in winner_players if not p.eliminated])
        if winner_names:
            res += f"👑 Winner{'s' if len(winner_players) > 1 else ''}: {winner_names}\n\n"
    res += "📊 Scores:\n"
    for p in sorted(game.players.values(), key=lambda x: -x.score):
        status = " (Eliminated)" if p.eliminated else ""
        res += f"♦️ {mention_html(p)} — {p.score}{status}\n"
    res += " Keep pushing, the next round awaits! 🚀"
    try:
        await context.bot.send_message(chat_id=group_id, text=res, parse_mode="HTML")
    except:
        pass

    # play elimination video(s)
    for p in eliminated_now:
        try:
            if VIDEO_ELIMINATION:
                await context.bot.send_video(chat_id=group_id, video=VIDEO_ELIMINATION, caption=f"☠️ {mention_html(p)} you are Eliminated!", parse_mode="HTML")
        except:
            pass

    # if game ended
    alive_now = [p for p in game.players.values() if not p.eliminated]
    if len(alive_now) <= 1:
        await end_game(context, group_id)
        return

    # reset for next round
    game.current_round_active = False
    game.round_results_sent = False
    game.reset_round_picks()
    for task in list(game.pick_tasks.values()) + list(game.pick_30_alerts.values()):
        try:
            task.cancel()
        except:
            pass
    game.pick_tasks.clear()
    game.pick_30_alerts.clear()

    game.duplicate_rule_active = getattr(game, "next_round_duplicate_active", False)
    game.next_round_duplicate_active = False

    asyncio.create_task(start_round(context, group_id))

async def dm_pick_handler(update, context):
    user = update.effective_user
    if not user:
        return

    if user.id not in user_active_game:
        await update.message.reply_text("♦ You are not currently participating in any active game.")
        return

    group_id = user_active_game[user.id]
    if group_id not in active_games:
        await update.message.reply_text("⚠️ The game you were in no longer exists.")
        user_active_game.pop(user.id, None)
        return

    game = active_games[group_id]
    if not getattr(game, "current_round_active", False):
        await update.message.reply_text("⏳ There is no active round at the moment. Please wait for the next round to start.")
        return

    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("♦ Invalid input. Please send a **plain number between 0 and 100** ")
        return
    num = int(text)
    if not 0 <= num <= 100:
        await update.message.reply_text("⚠️ Your number must be between 0 and 100. Please try again.")
        return

    if user.id not in game.players:
        await update.message.reply_text("♦ You are not listed as a player in this game.")
        return

    player = game.players[user.id]
    if getattr(player, "eliminated", False):
        await update.message.reply_text("☠️ You have been eliminated and cannot participate in this round.")
        return

    if getattr(player, "current_number", None) is not None:
        await update.message.reply_text("♦ You have already submitted a number for this round.")
        return

    player.current_number = num

    # try to create group link
    group_link = None
    try:
        chat = await context.bot.get_chat(group_id)
        if getattr(chat, "username", None):
            group_link = f"https://t.me/{chat.username}"
        else:
            chat_id_str = str(group_id)
            if chat_id_str.startswith("-100"):
                group_link = f"https://t.me/c/{chat_id_str[4:]}"
    except:
        pass

    if group_link:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Game", url=group_link)]])
        await update.message.reply_text(f"♦ Number received: <b>{num}</b>\n🎯 Get ready for the next round!", parse_mode="HTML", reply_markup=keyboard)
    else:
        await update.message.reply_text(f"♦ Number received: <b>{num}</b>\n🎯 Get ready for the next round!", parse_mode="HTML")

    task = game.pick_tasks.pop(user.id, None)
    if task and not task.done():
        task.cancel()
    task30 = game.pick_30_alerts.pop(user.id, None)
    if task30 and not task30.done():
        task30.cancel()

    if all((pl.current_number is not None or getattr(pl, "eliminated", False)) for pl in game.players.values()):
        for t in list(game.pick_tasks.values()):
            if t and not t.done():
                t.cancel()
        for t in list(game.pick_30_alerts.values()):
            if t and not t.done():
                t.cancel()
        game.pick_tasks.clear()
        game.pick_30_alerts.clear()
        await process_round_results(context, group_id)

async def end_game(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    if group_id not in active_games:
        logger.debug("No active game for group %s", group_id)
        return
    game = active_games[group_id]
    if getattr(game, "ended", False):
        logger.debug("Game already ended for group %s", group_id)
        return
    game.ended = True

    # increment games_played in DB (best-effort)
    try:
        conn = __import__("sqlite3").connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT group_id FROM groups WHERE group_id = ?", (group_id,))
        if not c.fetchone():
            c.execute("INSERT INTO groups (group_id, title, games_played) VALUES (?, ?, 0)", (group_id, "Unknown Group"))
        c.execute("UPDATE groups SET games_played = COALESCE(games_played,0) + 1 WHERE group_id = ?", (group_id,))
        conn.commit()
    except Exception:
        logger.exception("Failed to update games_played")
    finally:
        try:
            conn.close()
        except:
            pass

    players_sorted = sorted(game.players.values(), key=lambda p: -getattr(p, "score", 0)) if hasattr(game, "players") else []

    text = "『 𝗙𝗶𝗻𝗮𝗹 𝗦𝗰𝗼𝗿𝗲𝗰𝗮𝗿𝗱 』\n"
    text += "🎖️ Top Scorers:\n"
    if not players_sorted:
        text += "No players participated.\n"
    else:
        for p in players_sorted:
            name = getattr(p, "name", "Unknown")
            user_id = getattr(p, "user_id", None)
            score = getattr(p, "score", 0)
            status = " (Out)" if getattr(p, "eliminated", False) else ""
            text += f"♦️  <a href='tg://user?id={user_id}'>{name}</a> — {score}  {status}\n"
    text += "\n⊱⋅ ──────────────── ⋅⊰\n\n"

    winners = [p for p in players_sorted if not getattr(p, "eliminated", False)]
    winner = winners[0] if winners else (players_sorted[0] if players_sorted else None)

    if winner:
        winner_name = getattr(winner, "name", "Unknown")
        winner_id = getattr(winner, "user_id", None)
        text += f"🎉 Champion: <a href='tg://user?id={winner_id}'>{winner_name}</a> 🏆\n"

    async def send_scorecard():
        try:
            await context.bot.send_message(chat_id=group_id, text=text, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to send scorecard")

    async def send_winner_announcement():
        if winner and VIDEO_WINNER:
            try:
                await context.bot.send_video(chat_id=group_id, video=VIDEO_WINNER, caption=f"🎉 Champion: <a href='tg://user?id={winner_id}'>{winner_name}</a> 🏆", parse_mode="HTML")
            except:
                try:
                    await context.bot.send_message(chat_id=group_id, text=f"🎉 Champion: <a href='tg://user?id={winner_id}'>{winner_name}</a> 🏆", parse_mode="HTML")
                except:
                    pass
        elif winner:
            try:
                await context.bot.send_message(chat_id=group_id, text=f"🎉 Champion: <a href='tg://user?id={winner_id}'>{winner_name}</a> 🏆", parse_mode="HTML")
            except:
                pass

    async def send_new_game_notification():
        try:
            await context.bot.send_message(chat_id=group_id, text="The game has ended. You can start a new game anytime with /startgame.", parse_mode="HTML")
        except:
            pass

    loop = asyncio.get_event_loop()
    loop.call_later(0, lambda: asyncio.create_task(send_scorecard()))
    loop.call_later(1, lambda: asyncio.create_task(send_winner_announcement()))
    loop.call_later(2, lambda: asyncio.create_task(send_new_game_notification()))

    # Save user stats
    for p in players_sorted:
        try:
            user_obj = type("U", (), {
                "id": getattr(p, "user_id", None),
                "first_name": getattr(p, "name", "Unknown"),
                "username": getattr(p, "username", None)
            })
            ensure_user_exists(user_obj)
            update_user_after_game(
                user_id=getattr(p, "user_id", None),
                score_delta=getattr(p, "score", 0),
                won=(winner is not None and getattr(p, "user_id", None) == getattr(winner, "user_id", None)),
                eliminated=getattr(p, "eliminated", False),
                rounds_played=getattr(p, "rounds_played", 0),
                penalties=getattr(p, "total_penalties", 0)
            )
        except Exception:
            logger.exception("Failed to update stats for user %s", getattr(p, "user_id", None))

    for p in players_sorted:
        user_active_game.pop(getattr(p, "user_id", None), None)

    # cancel tasks
    for t in list(getattr(game, "pick_tasks", {}).values()):
        try:
            if t and not t.done(): t.cancel()
        except:
            pass
    for t in list(getattr(game, "pick_30_alerts", {}).values()):
        try:
            if t and not t.done(): t.cancel()
        except:
            pass

    getattr(game, "pick_tasks", {}).clear()
    getattr(game, "pick_30_alerts", {}).clear()

    active_games.pop(group_id, None)
    logger.debug("Game ended and cleaned up for group %s", group_id)
