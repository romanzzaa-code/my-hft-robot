import os
import json
import logging
import asyncio
from aiodocker import Docker, DockerError
from typing import Callable, Dict, Any, Awaitable

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    TelegramObject
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

load_dotenv()

# --- CONFIG ---
TOKEN = os.getenv("TG_COMMANDER_TOKEN")
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
if 0 in USER_MAP: del USER_MAP[0]

CONFIG_DIR = "/app/config"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("COMMANDER")

if not TOKEN:
    logger.critical("TG_COMMANDER_TOKEN is missing!")
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()
docker_client = None

# --- SECURITY MIDDLEWARE ---
class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id not in USER_MAP:
            return 
        
        data["user_context"] = USER_MAP[user.id]
        return await handler(event, data)

# --- FSM STATES ---
class EditState(StatesGroup):
    waiting_for_value = State()
    key_to_edit = State()

# --- KEYBOARDS (UPDATED) ---

# 1. Main Menu -> Persistent Reply Keyboard
def main_menu():
    kb = [
        [KeyboardButton(text="🟢 Status"), KeyboardButton(text="📜 Logs")],
        [KeyboardButton(text="⚙️ Config"), KeyboardButton(text="🔄 Restart")],
        [KeyboardButton(text="🛑 Stop"), KeyboardButton(text="▶️ Start")]
    ]
    # resize_keyboard=True делает кнопки компактными
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)

# 2. Config Menu -> Inline (Contextual)
def config_inline_kb(data):
    kb = []
    keys = ["investment_usdt", "wall_ratio_threshold", "min_wall_value_usdt", "vol_ema_alpha"]
    for k in keys:
        val = data.get(k, "N/A")
        val_str = f"{val:.4f}" if isinstance(val, float) else str(val)
        btn_text = f"{k}: {val_str}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"edit_{k}")])
    
    # Кнопка Close убирает инлайн сообщение, но оставляет Reply меню
    kb.append([InlineKeyboardButton(text="❌ Close Config", callback_data="close_config")])
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

async def get_container_data(name: str):
    if not docker_client: return None, None
    try:
        container = await docker_client.containers.get(name)
        data = await container.show() 
        return container, data
    except DockerError:
        return None, None

# --- HANDLERS (REFACTORED FOR REPLY KEYBOARD) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, user_context: dict):
    target = user_context["container"]
    await message.answer(
        f"🫡 <b>Operator Ready.</b>\nTarget: {target}\n\n<i>Menu is pinned below</i> 👇", 
        reply_markup=main_menu(), 
        parse_mode="HTML"
    )

@dp.message(F.text == "🟢 Status")
async def msg_status(message: types.Message, user_context: dict):
    c, data = await get_container_data(user_context["container"])
    if c and data:
        state = data['State']['Status']
        status_emoji = "🟢" if state == 'running' else "🔴"
        img_tag = data['Config']['Image']
        text = f"Target: {user_context['container']}\nStatus: {status_emoji} {state}\nImage: {img_tag}"
        await message.answer(text)
    else:
        await message.answer(f"❌ Container {user_context['container']} not found!")

@dp.message(F.text == "📜 Logs")
async def msg_logs(message: types.Message, user_context: dict):
    c, data = await get_container_data(user_context["container"])
    if c:
        try:
            status_msg = await message.answer("⏳ Fetching logs...")
            logs_list = await c.log(stdout=True, stderr=True, tail=50)
            logs = "".join(logs_list) if isinstance(logs_list, list) else str(logs_list)
            
            if len(logs) > 4000: logs = logs[-4000:]
            if not logs: logs = "Logs are empty."
            
            await status_msg.edit_text(f"<pre>{logs}</pre>", parse_mode="HTML")
        except Exception as e:
            await message.answer(f"Error: {e}")
    else:
        await message.answer("Container not found")

@dp.message(F.text == "🔄 Restart")
async def msg_restart(message: types.Message, user_context: dict):
    c, _ = await get_container_data(user_context["container"])
    if c:
        msg = await message.answer("🔄 Restarting...")
        try:
            await c.restart()
            await msg.edit_text("✅ Bot restarted!")
        except Exception as e:
            await msg.edit_text(f"❌ Error: {e}")
    else:
        await message.answer("Container not found")

@dp.message(F.text == "🛑 Stop")
async def msg_stop(message: types.Message, user_context: dict):
    c, _ = await get_container_data(user_context["container"])
    if c:
        msg = await message.answer("🛑 Stopping...")
        try:
            await c.stop()
            await msg.edit_text("✅ Bot stopped.")
        except Exception as e:
            await msg.edit_text(f"❌ Error: {e}")
    else:
        await message.answer("Container not found")

@dp.message(F.text == "▶️ Start")
async def msg_start(message: types.Message, user_context: dict):
    c, _ = await get_container_data(user_context["container"])
    if c:
        try:
            await c.start()
            await message.answer("✅ Bot started.")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")
    else:
        await message.answer("Container not found")

# --- CONFIGURATION (HYBRID: Text Trigger -> Inline Menu) ---

@dp.message(F.text == "⚙️ Config")
async def msg_config(message: types.Message, user_context: dict):
    data = load_user_config(user_context["config_file"])
    if "error" in data:
        await message.answer(f"Config Error: {data['error']}")
        return
    await message.answer(
        f"🔧 <b>Configuration</b>\nFile: {user_context['config_file']}", 
        reply_markup=config_inline_kb(data),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("edit_"))
async def cb_edit_value(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split("edit_")[1]
    await state.update_data(key_to_edit=key)
    await state.set_state(EditState.waiting_for_value)
    # Используем ForceReply, чтобы пользователю было удобно вводить значение
    await callback.message.answer(
        f"✍️ Enter new value for <b>{key}</b>:", 
        parse_mode="HTML",
        reply_markup=types.ForceReply(selective=True)
    )
    await callback.answer()

@dp.callback_query(F.data == "close_config")
async def cb_close_config(callback: types.CallbackQuery):
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.answer()

@dp.message(EditState.waiting_for_value)
async def process_new_value(message: types.Message, state: FSMContext, user_context: dict):
    user_val = message.text
    data = await state.get_data()
    key = data['key_to_edit']
    
    config = load_user_config(user_context["config_file"])
    try:
        # Валидация типов (Domain Logic leak inside Controller - допустимо для MVP, но лучше вынести)
        if "." in user_val:
            val = float(user_val)
        else:
            val = int(user_val)
            
        config[key] = val
        save_user_config(user_context["config_file"], config)
        
        # [FIX] ВОССТАНАВЛИВАЕМ МЕНЮ ЗДЕСЬ
        await message.answer(
            f"✅ Saved: {key} = {val}\n⚠️ <b>Restart bot to apply!</b>", 
            parse_mode="HTML",
            reply_markup=main_menu()  # <--- КРИТИЧЕСКИ ВАЖНОЕ ИЗМЕНЕНИЕ
        )
    except ValueError:
        await message.answer(
            "❌ Invalid number format.",
            reply_markup=main_menu() # Здесь тоже стоит вернуть меню, если мы выходим из состояния
        )

    await state.clear()

# --- LIFECYCLE ---
async def on_startup():
    global docker_client
    docker_client = Docker()
    logger.info("Docker client attached.")

async def on_shutdown():
    if docker_client:
        await docker_client.close()
        logger.info("Docker client closed.")

async def main():
    if not USER_MAP:
        logger.error("❌ NO USERS CONFIGURED!")
    
    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())