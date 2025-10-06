from PIL import Image, ImageDraw
from pathlib import Path
from telegram import User
from telegram.error import TelegramError
import io
import os

TEMPLATES = {
    "leaderboard": {
        "path": "assets/leaderboard.png",
        "circle": {"x": 722, "y": 130, "size": 443}
    },
    "userinfo": {
        "path": "assets/userinfo.png",
        "circle": {"x": 713, "y": 116, "size": 494}
    },
}

TEMP_DIR = Path("temp")

async def download_user_photo_by_id(user_id: int, bot):
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if not photos or not photos.total_count:
            return None

        file_id = photos.photos[0][-1].file_id
        tg_file = await bot.get_file(file_id)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        path = str(TEMP_DIR / f"{user_id}.jpg")
        return await tg_file.download_to_drive(path)
    except TelegramError:
        return None

def generate_card(template_name, user_pfp=None):
    config = TEMPLATES[template_name]

    # Load template
    base = Image.open(config["path"]).convert("RGBA")

    # Profile picture
    if user_pfp and os.path.exists(user_pfp):
        pfp = Image.open(user_pfp).convert("RGBA")
    else:
        return config

    # Circle values
    x, y, size = config["circle"]["x"], config["circle"]["y"], config["circle"]["size"]

    # Resize + make circular
    pfp = pfp.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    pfp.putalpha(mask)

    base.paste(pfp, (x, y), pfp)

    bio = io.BytesIO()
    bio.name = "card.png"
    base.save(bio, "PNG")
    bio.seek(0)
    return bio
