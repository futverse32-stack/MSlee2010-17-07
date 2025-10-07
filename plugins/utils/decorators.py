from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from plugins.helpers.moderators import is_owner, is_mod

def admin_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat = update.effective_chat
        user = update.effective_user

        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
        except:
            await update.message.reply_text(" ⚠️ Could not verify admin status.")
            return

        if member.status not in ["administrator", "creator"]:
            await update.message.reply_text(" ‼️ Only group admins can use this command..")
            return


        return await func(update, context, *args, **kwargs)
    return wrapped


def owner_only(func):
    """Allow only the OWNER_ID to execute the command."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or not is_owner(user.id):
            await update.message.reply_text("❌ Sorry Baccha, Ap owner nhi 😓")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

def mod_only(func):
    """Allow only users present in mods table (NOT the owner by default)."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or not is_mod(user.id):
            await update.message.reply_text("❌ You must be a mod to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

def mod_or_owner(func):
    """Allow mods OR owner to execute the command."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or not (is_owner(user.id) or is_mod(user.id)):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped