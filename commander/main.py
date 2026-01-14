import os
import json
import logging
import asyncio
import docker
from typing import Callable, Dict, Any, Awaitable, Optional

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, TelegramObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
TOKEN = os.getenv("TG_COMMANDER_TOKEN")

# Настройка пользователей: ID -> {Контейнер, Файл конфига}
USER_MAP = {
    int(os.getenv("TG_MY_ID", 0)): {
        "container": "hft_bot",
        "config_file": "strategy_params.json"
    },
    int(os.getenv("TG_FRIEND_ID", 0)): {
        "container": "hft_bot_friend",
        "config_file": "friend_params.json"
    }
}
# Убираем 0 (если ID не задан в .env)
if 0 in USER_MAP: del USER_MAP[0]

CONFIG_DIR = "/app/config"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("COMMANDER")

if not TOKEN:
    logger.critical("TG_COMMANDER_TOKEN is missing!")
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()
docker_client = docker.from_env()

# --- SECURITY MIDDLEWARE ---
class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        # Проверяем, есть ли пользователь в нашей карте разрешенных
        if user.id not in USER_MAP:
            return # Игнорируем чужаков
            
        # Прокидываем контекст пользователя в хендлер
        data["user_context"] = USER_MAP[user.id]
        return await handler(event, data)

# --- FSM STATES ---
class EditState(StatesGroup):
    waiting_for_value = State()
    key_to_edit = State()

# --- KEYBOARDS ---
def main_menu():
    kb = [
        [InlineKeyboardButton(text="🟢 Status", callback_data="status"),
         InlineKeyboardButton(text="📜 Logs (50)", callback_data="logs")],
        [InlineKeyboardButton(text="⚙️ Config", callback_data="config"),
         InlineKeyboardButton(text="🔄 Restart Bot", callback_data="restart")],
        [InlineKeyboardButton(text="🛑 Stop Bot", callback_data="stop"),
         InlineKeyboardButton(text="▶️ Start Bot", callback_data="start")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def config_menu(data):
    kb = []
    keys = ["investment_usdt", "wall_ratio_threshold", "min_wall_value_usdt", "vol_ema_alpha"]
    for k in keys:
        val = data.get(k, "N/A")
        if isinstance(val, float):
            val_str = f"{val:.4f}"
        else:
            val_str = str(val)
        btn_text = f"{k}: {val_str}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"edit_{k}")])
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- UTILS ---
def get_user_file_path(filename: str):
    return os.path.join(CONFIG_DIR, filename)

def load_user_config(filename: str):
    path = get_user_file_path(filename)
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}

def save_user_config(filename: str, data: dict):
    path = get_user_file_path(filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)

def get_container(name: str):
    try:
        return docker_client.containers.get(name)
    except docker.errors.NotFound:
        return None

# --- HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, user_context: dict):
    target = user_context["container"]
    await message.answer(f"🫡 Welcome, Operator.\nTarget System: <b>{target}</b>", 
                         reply_markup=main_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "status")
async def cb_status(callback: types.CallbackQuery, user_context: dict):
    c = get_container(user_context["container"])
    if c:
        status_emoji = "🟢" if c.status == 'running' else "🔴"
        img_tag = c.image.tags[0] if c.image.tags else "unknown"
        await callback.message.edit_text(f"Target: {user_context['container']}\nStatus: {status_emoji} {c.status}\nImage: {img_tag}", reply_markup=main_menu())
    else:
        await callback.message.edit_text(f"❌ Container {user_context['container']} not found!", reply_markup=main_menu())

@dp.callback_query(F.data == "logs")
async def cb_logs(callback: types.CallbackQuery, user_context: dict):
    c = get_container(user_context["container"])
    if c:
        try:
            logs = c.logs(tail=50).decode("utf-8")
            if len(logs) > 4000: logs = logs[-4000:]
            if not logs: logs = "Logs are empty."
            await callback.message.answer(f"<pre>{logs}</pre>", parse_mode="HTML")
            await callback.answer()
        except Exception as e:
            await callback.answer(f"Error: {e}")
    else:
        await callback.answer("Container not found")

@dp.callback_query(F.data == "restart")
async def cb_restart(callback: types.CallbackQuery, user_context: dict):
    c = get_container(user_context["container"])
    if c:
        await callback.message.edit_text("🔄 Restarting... Please wait.")
        try:
            c.restart()
            await callback.message.edit_text("✅ Bot restarted!", reply_markup=main_menu())
        except Exception as e:
            await callback.message.edit_text(f"❌ Error: {e}", reply_markup=main_menu())
    else:
        await callback.answer("Container not found")

@dp.callback_query(F.data == "stop")
async def cb_stop(callback: types.CallbackQuery, user_context: dict):
    c = get_container(user_context["container"])
    if c:
        await callback.message.edit_text("🛑 Stopping...")
        c.stop()
        await callback.message.edit_text("✅ Bot stopped.", reply_markup=main_menu())

@dp.callback_query(F.data == "start")
async def cb_start(callback: types.CallbackQuery, user_context: dict):
    c = get_container(user_context["container"])
    if c:
        c.start()
        await callback.message.edit_text("✅ Bot started.", reply_markup=main_menu())

@dp.callback_query(F.data == "config")
async def cb_config(callback: types.CallbackQuery, user_context: dict):
    data = load_user_config(user_context["config_file"])
    if "error" in data:
        await callback.answer(f"Config Error: {data['error']}")
        return
    await callback.message.edit_text(f"🔧 Config: {user_context['config_file']}", reply_markup=config_menu(data))

@dp.callback_query(F.data.startswith("edit_"))
async def cb_edit_value(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split("edit_")[1]
    await state.update_data(key_to_edit=key)
    await state.set_state(EditState.waiting_for_value)
    await callback.message.answer(f"✍️ Enter new value for <b>{key}</b>:", parse_mode="HTML")
    await callback.answer()

@dp.message(EditState.waiting_for_value)
async def process_new_value(message: types.Message, state: FSMContext, user_context: dict):
    user_val = message.text
    data = await state.get_data()
    key = data['key_to_edit']
    
    config = load_user_config(user_context["config_file"])
    try:
        if "." in user_val:
            val = float(user_val)
        else:
            val = int(user_val)
            
        config[key] = val
        save_user_config(user_context["config_file"], config)
        await message.answer(f"✅ Saved: {key} = {val}\nTarget: {user_context['container']}\n\n⚠️ <b>Don't forget to RESTART!</b>", parse_mode="HTML", reply_markup=main_menu())
    except ValueError:
        await message.answer("❌ Invalid number format. Try again.")
        return

    await state.clear()

@dp.callback_query(F.data == "back")
async def cb_back(callback: types.CallbackQuery):
    await callback.message.edit_text("Main Menu", reply_markup=main_menu())

async def main():
    if not USER_MAP:
        logger.error("❌ NO USERS CONFIGURED!")
    
    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())