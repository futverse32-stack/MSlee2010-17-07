import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, filters
from plugins.game.core import MindScaleGame, active_games, user_active_game, start_round, mention_html
from plugins.game.db import ensure_user_exists, ensure_group_exists, ensure_columns_exist, update_user_after_game
from config import JOIN_TIME_SEC, MIN_PLAYERS, MAX_PLAYERS
from plugins.helpers.leaderboard import get_user_rank
from plugins.utils.decorators import admin_only, mod_or_owner
from plugins.helpers.notify import notify_on_new_game
import logging, time

logger = logging.getLogger(__name__)

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ /startgame can only be used in groups!")
        return
    group_id = update.effective_chat.id
    if group_id in active_games:
        await update.message.reply_text("❌ A game is already running in this group.")
        return

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Solo", callback_data=f"start_solo:{group_id}"),
         InlineKeyboardButton("Team", callback_data=f"start_team:{group_id}")]
    ])
    await update.message.reply_photo(
        photo="https://graph.org/file/79186f4d926011e1fb8e8-a9c682050a7a3539ed.jpg",
        caption="🎲 Mind Scale Game\n\nChoose game mode:",
        reply_markup=buttons
    )

    invite_link = (await context.bot.export_chat_invite_link(group_id))  # if group is private
    await notify_on_new_game(
        context,
        group_id=update.effective_chat.id,
        group_title=update.effective_chat.title,
        group_invite_link=invite_link
    )

async def mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    if len(data) != 2:
        return
    mode, group_id = data[0], int(data[1])

    if mode == "start_solo":
        if group_id in active_games:
            await query.edit_message_caption(caption="❌ A game is already running in this group.")
            return
        game = MindScaleGame(group_id)
        active_games[group_id] = game
        ensure_group_exists(group_id, getattr(update.effective_chat, "title", "Unknown Group"))
        welcome_text = f"""🎲 Mind Scale Game Starting (Solo Mode) 🎲

Use /join to join the current game
Use /leave to leave before the {JOIN_TIME_SEC // 60}-min timer ends

Minimum players: {MIN_PLAYERS}"""
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🛠 Support", url="https://t.me/MindScale17")]])
        await query.edit_message_caption(caption=welcome_text, reply_markup=buttons)
        asyncio.create_task(join_phase_scheduler(context, group_id))

    elif mode == "start_team":
        await query.edit_message_caption(
            caption="🚀 Team Mode is coming soon! Try Solo Mode for now.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Play Solo", callback_data=f"start_solo:{group_id}")]])
        )

async def join_phase_scheduler(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    if group_id not in active_games:
        return
    game = active_games[group_id]

    game.join_deadline = time.monotonic() + JOIN_TIME_SEC

    async def schedule_alert(delay, seconds_left):
        await asyncio.sleep(delay)
        if (group_id in active_games and
            active_games[group_id].join_phase_active and
            getattr(active_games[group_id], "join_deadline", 0) == game.join_deadline):
            await context.bot.send_message(
                chat_id=group_id,
                text=f"⏱ Hurry up! Only {seconds_left} seconds left to /join the game!"
            )

    tasks = []
    for sec in [120, 60, 30, 10]:
        delay = max(0, JOIN_TIME_SEC - sec)
        tasks.append(asyncio.create_task(schedule_alert(delay, sec)))
    game.alert_tasks = tasks

    game.join_timer_task = asyncio.create_task(asyncio.sleep(JOIN_TIME_SEC))

    while True:
        try:
            await game.join_timer_task         
            break                                
        except asyncio.CancelledError:
            if not (group_id in active_games and game.join_phase_active):
                return 
            continue

    for t in game.alert_tasks or []:
        if t and not t.done():
            t.cancel()

    if group_id in active_games:
        await end_join_phase(context, group_id)

async def end_join_phase(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    if group_id not in active_games:
        return
    game = active_games[group_id]
    game.join_phase_active = False
    num_joined = len(game.players)

    if num_joined < MIN_PLAYERS:
        await context.bot.send_message(chat_id=group_id, text=f"❌  𝗝𝗼𝗶𝗻 𝗣𝗵𝗮𝘀𝗲 𝗘𝗻𝗱𝗲𝗱』\n\n🚫 Not enough players joined ({num_joined}/{MIN_PLAYERS}).\nThe game has been canceled.", parse_mode="HTML")
        for p in game.players.values():
            user_active_game.pop(p.user_id, None)
        del active_games[group_id]
        return

    if num_joined > MAX_PLAYERS:
        joined_players = list(game.players.values())[:MAX_PLAYERS]
        removed_players = list(game.players.values())[MAX_PLAYERS:]
        game.players = {p.user_id: p for p in joined_players}
        for p in removed_players:
            try:
                await context.bot.send_message(chat_id=p.user_id, text=f"⚠️ Sorry! The match can only have {MAX_PLAYERS} players. You won't be playing this round.")
            except:
                pass

    players_list = "\n".join([f"♦️ <a href='tg://user?id={p.user_id}'>{p.name}</a>" for p in game.players.values()])

    await context.bot.send_message(chat_id=group_id, text=(f"『 𝗠𝗮𝘁𝗰𝗵 𝗦𝗲𝘁𝘁𝗹𝗲𝗱 』\n\n🎲 Players Joined ({len(game.players)}):\n{players_list}\n\n⊱⋅ ─────────── ⋅⊰\n\n✧ Brace yourselves! The game is about to begin! 🚀"), parse_mode="HTML")
    await start_round(context, group_id)

async def extend(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.type not in (filters.ChatType.GROUP, filters.ChatType.SUPERGROUP, 'group', 'supergroup'):
        await update.message.reply_text("❌ /extend can only be used in groups!")
        return

    group_id = update.effective_chat.id

    game = active_games.get(group_id)
    if not game or not getattr(game, "join_phase_active", False):
        await update.message.reply_text("⚠️ No join phase is active right now.")
        return

    try:
        extra = int(context.args[0]) if context.args else 30
    except (ValueError, IndexError):
        extra = 30

    if extra <= 0:
        await update.message.reply_text("⚠️ Please provide a positive number of seconds.")
        return
    if extra > 240:
        await update.message.reply_text("⚠️ Maximum extension is 4 minutes.")
        return

    now = time.monotonic()

    if not hasattr(game, "join_deadline"):
        game.join_deadline = now
    remaining = max(0, int(game.join_deadline - now))

    # New total time from now
    new_total = remaining + extra
    new_deadline = now + new_total

    if getattr(game, "join_timer_task", None) and not game.join_timer_task.done():
        game.join_timer_task.cancel()

    for t in getattr(game, "alert_tasks", []) or []:
        if t and not t.done():
            t.cancel()

    new_alerts = []
    async def schedule_alert(delay, seconds_left):
        await asyncio.sleep(delay)
        if group_id in active_games and active_games[group_id].join_phase_active and active_games[group_id].join_deadline == new_deadline:
            await context.bot.send_message(
                chat_id=group_id,
                text=f"⏱ Hurry up! Only {seconds_left} seconds left to /join the game!"
            )

    for sec in [120, 60, 30, 10]:
        delay = max(0, new_total - sec)
        new_alerts.append(asyncio.create_task(schedule_alert(delay, sec)))
    game.alert_tasks = new_alerts

    game.join_timer_task = asyncio.create_task(asyncio.sleep(new_total))
    game.join_deadline = new_deadline

    def fmt(sec: int) -> str:
        m, s = divmod(sec, 60)
        if m and s:
            return f"{m}m {s}s"
        if m:
            return f"{m}m"
        return f"{s}s"

    await update.message.reply_text(
        f"✅ Join phase extended by {fmt(extra)}.\n"
        f"🕒 Time remaining: {fmt(new_total)}."
    )

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ Use /join in the group where the game is running.")
        return

    group_id = update.effective_chat.id
    user = update.effective_user

    if user.id in user_active_game:
        gid = user_active_game[user.id]
        await update.message.reply_text(f" ⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ You are already playing in another group (`{gid}`). Finish it first!", parse_mode="Markdown")
        return

    if group_id not in active_games:
        await update.message.reply_text(" ⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ No active game. Start one with /startgame")
        return

    game = active_games[group_id]
    if not getattr(game, "join_phase_active", False):
        await update.message.reply_text(" ⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ Join phase is already closed!")
        return

    if len(getattr(game, "players", [])) >= MAX_PLAYERS:
        await update.message.reply_text(f"⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ The game already has {MAX_PLAYERS} players. Cannot join.")
        return

    ensure_user_exists(user)
    game.add_player(user)
    await update.message.reply_text(f" ✅ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n✨ <b>{user.full_name}</b> joined the match!", parse_mode="HTML")

    if len(game.players) == MAX_PLAYERS:
        join_timer = getattr(game, "join_timer_task", None)
        if join_timer and not join_timer.done():
            join_timer.cancel()
            game.join_timer_task = None
        game.join_phase_active = False
        game.game_started = True
        await context.bot.send_message(chat_id=group_id, text=f" 🚀 𝗠𝗮𝘁𝗰𝗵 𝗦𝘁𝗮𝗿𝘁 \n\n✅ {MAX_PLAYERS} players joined! Starting immediately...")
        await start_round(context, group_id)

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(" ⚠️ 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲\n\n❌ Use /leave in the group.")
        return

    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    if group_id not in active_games:
        await update.message.reply_text("⚠️ 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲 \n\n❌ No active game.")
        return

    game = active_games[group_id]
    if not game.join_phase_active:
        await update.message.reply_text("⚠️ 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲 \n\n❌ You cannot leave after the match has started.")
        return

    if user_id not in game.players:
        await update.message.reply_text(" ⚠️ 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲\n\n❌ You are not part of this game.")
        return

    game.remove_player(user_id)
    await update.message.reply_text(f" 👋 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲 \n\n🚪 <b>{update.effective_user.full_name}</b> has left the match.", parse_mode="HTML")

async def players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if group_id not in active_games:
        await update.message.reply_text("『 ⚠️ 𝗣𝗹𝗮𝘆𝗲𝗿𝘀 𝗟𝗶𝘀𝘁 』\n\n❌ No active game found.")
        return
    game = active_games[group_id]
    if not game.players:
        await update.message.reply_text("『 ⚠️ 𝗣𝗹𝗮𝘆𝗲𝗿𝘀 𝗟𝗶𝘀𝘁 』\n\n❌ No players joined yet.")
        return

    text = " 🎲 𝗖𝘂𝗿𝗿𝗲𝗻𝘁 𝗣𝗹𝗮𝘆𝗲𝗿𝘀 🎲 \n\n"
    for i, p in enumerate(game.players.values(), 1):
        text += f"{i}. <a href='tg://user?id={p.user_id}'>{p.name}</a>\n"
    text += "\n⊱⋅ ───────────── ⋅⊰\n✧ Together we play, together we conquer! ⚡\n"

    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("💠 Support", url="https://t.me/MindScale17")]])
    await update.message.reply_photo(photo="https://graph.org/file/79186f4d926011e1fb8e8-a9c682050a7a3539ed.jpg", caption=text, parse_mode="HTML", reply_markup=buttons)

@admin_only
async def endmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm End Match", callback_data=f"confirm_endmatch:{chat.id}")]])
    await update.message.reply_text(" ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵 \n\n⚠️ Are you sure you want to end the current game?", reply_markup=buttons)

async def confirm_endmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    if len(data) != 2:
        return
    group_id = int(data[1])
    user = query.from_user
    try:
        member = await context.bot.get_chat_member(group_id, user.id)
    except:
        await query.edit_message_text(" ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵 \n\n❌ Could not verify admin.")
        return
    if member.status not in ["administrator", "creator"]:
        await query.edit_message_text(" ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵』\n\n❌ Only admins can confirm this action.")
        return
    if group_id not in active_games:
        await query.edit_message_text(" ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵 \n\n❌ No active game to end.")
        return
    game = active_games[group_id]
    for task in list(game.pick_tasks.values()) + list(game.pick_30_alerts.values()):
        if not task.done():
            task.cancel()
    game.pick_tasks.clear()
    game.pick_30_alerts.clear()

    for p in game.players.values():
        class UserObj:
            def __init__(self, user_id, name, username):
                self.id = user_id
                self.first_name = name
                self.username = username
        u = UserObj(p.user_id, p.name, p.username)
        ensure_user_exists(u)
        update_user_after_game(
            user_id=p.user_id,
            score_delta=getattr(p, "total_score", p.score),
            rounds_played=getattr(p, "rounds_played", 0),
            eliminated=getattr(p, "eliminated", False),
            penalties=getattr(p, "total_penalties", 0),
            won=False
        )

    for p in game.players.values():
        user_active_game.pop(p.user_id, None)

    del active_games[group_id]
    await query.edit_message_text(f" ✅ 𝗚𝗮𝗺𝗲 𝗘𝗻𝗱𝗲𝗱 \n\n☑️ Game ended by admin {user.first_name}.\n⏳ All timers cleared.")

@admin_only
async def forcestart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    group_id = chat.id

    # Check if a game exists
    if group_id not in active_games:
        await update.message.reply_text(
            "⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ No active game to start."
        )
        return

    game = active_games[group_id]

    # Check if join phase is active
    if not game.join_phase_active:
        await update.message.reply_text(
            "⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ Join phase is already closed!"
        )
        return

    # Check minimum players
    if len(game.players) < MIN_PLAYERS:
        await update.message.reply_text(
            f"⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ Not enough players joined ({len(game.players)}/{MIN_PLAYERS})."
        )
        return

    # Cancel join phase timer
    if game.join_timer_task and not game.join_timer_task.done():
        game.join_timer_task.cancel()
        game.join_timer_task = None

    # End join phase and start game
    game.join_phase_active = False
    await context.bot.send_message(
        chat_id=group_id,
        text=f"🚀 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n✅ Admin - {user.first_name} has started the game early!"
    )
    await end_join_phase(context, group_id)

