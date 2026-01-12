import asyncio
import os
import logging
import whisper
import edge_tts
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- НАСТРОЙКИ ---
API_TOKEN = '8332412698:AAGn8cHlDtTdqxKqG6YFv07S7mfIr0JSiAg'
SUBSCRIBED_CHAT_ID = -4826017294

# Ленты
NEWS_RSS_URL = "https://lenta.ru/rss/top7"
MCHS_RSS_URL = "https://78.mchs.gov.ru/deyatelnost/press-centr/operativnaya-informaciya/shtormovye-i-ekstrennye-preduprezhdeniya/rss"

MODEL_TYPE = "small"
VOICE = "ru-RU-DmitryNeural"
LAT = 59.99853662511413
LON = 30.24746783266525
# -----------------

logging.basicConfig(level=logging.INFO)
print(f"Загружаю модель Whisper ({MODEL_TYPE})...")
model = whisper.load_model(MODEL_TYPE)
print("Модель готова!")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

LAST_NEWS_LINK = None
LAST_MCHS_LINK = None

class SearchState(StatesGroup):
    waiting_for_location = State()

# --- ФУНКЦИЯ: МЧС (Через yandex:full-text) ---
async def check_mchs_warnings(force_send=False):
    global LAST_MCHS_LINK
    if SUBSCRIBED_CHAT_ID == 0: return

    # Функция для скачивания через requests (чтобы притвориться браузером)
    def fetch_feed():
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        # Скачиваем с таймаутом 15 секунд
        response = requests.get(MCHS_RSS_URL, headers=headers, timeout=15)
        response.raise_for_status()
        return feedparser.parse(response.content)

    try:
        loop = asyncio.get_event_loop()
        # Запускаем скачивание в отдельном потоке
        feed = await loop.run_in_executor(None, fetch_feed)

        if not feed.entries: return
        
        top_entry = feed.entries[0]
        current_link = top_entry.link

        if LAST_MCHS_LINK != current_link or force_send:
            if LAST_MCHS_LINK is None and not force_send:
                LAST_MCHS_LINK = current_link
                return

            LAST_MCHS_LINK = current_link
            
            # Извлечение текста
            raw_html = top_entry.get('yandex_full-text')
            if not raw_html:
                raw_html = top_entry.summary

            soup = BeautifulSoup(raw_html, 'html.parser')
            clean_text = soup.get_text(separator="\n\n", strip=True)

            message_text = (
                f"🚨 <b>МЧС ПРЕДУПРЕЖДАЕТ (СПб):</b>\n\n"
                f"<b>{top_entry.title}</b>\n\n"
                f"{clean_text}\n"
            )
            
            if len(message_text) > 4000:
                message_text = message_text[:4000] + "...\n(Читать далее по ссылке)"
            
            message_text += f"\n👉 <a href='{current_link}'>Источник</a>"
            
            await bot.send_message(SUBSCRIBED_CHAT_ID, message_text, parse_mode="HTML")
            print(f"🚨 МЧС отправлено: {top_entry.title}")

    except Exception as e:
        # Теперь ошибка будет появляться быстрее и не подвесит бота
        print(f"Ошибка МЧС: {e}")

# --- ФУНКЦИЯ: НОВОСТИ ---
async def check_news_feed(force_send=False):
    global LAST_NEWS_LINK
    if SUBSCRIBED_CHAT_ID == 0: return

    try:
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, NEWS_RSS_URL)
        if not feed.entries: return
        
        top_entry = feed.entries[0]
        if LAST_NEWS_LINK != top_entry.link or force_send:
            if LAST_NEWS_LINK is None and not force_send:
                LAST_NEWS_LINK = top_entry.link
                return

            LAST_NEWS_LINK = top_entry.link
            text = f"⚡️ <b>Срочно:</b>\n\n<b>{top_entry.title}</b>\n{top_entry.summary[:300]}...\n\n👉 <a href='{top_entry.link}'>Читать</a>"
            await bot.send_message(SUBSCRIBED_CHAT_ID, text, parse_mode="HTML")

    except Exception as e: print(f"Ошибка News: {e}")

# --- ФУНКЦИИ ИНФО ---
def get_weather():
    try:
        r = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current_weather=true&windspeed_unit=ms").json()
        return f"🌡 <b>Погода:</b> {r['current_weather']['temperature']}°C, ветер {r['current_weather']['windspeed']} м/с"
    except: return "🌡 Погода: Нет данных"

def get_currency():
    try:
        data = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        return f"💰 <b>USD:</b> {data['Valute']['USD']['Value']:.2f} ₽"
    except: return "💰 Нет данных"

def get_full_horoscope():
    full_text = "🔮 <b>Гороскоп:</b>\n\n"
    signs = {"aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋", "leo": "♌", "virgo": "♍", "libra": "♎", "scorpio": "♏", "sagittarius": "♐", "capricorn": "♑", "aquarius": "♒", "pisces": "♓"}
    try:
        for slug, icon in signs.items():
            r = requests.get(f"https://1001goroskop.ru/?znak={slug}", headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(r.content, 'lxml')
            text = soup.find('div', itemprop='description').get_text(strip=True)[:150].rsplit('.', 1)[0] + "."
            full_text += f"{icon} {text}\n"
        return full_text
    except: return "Звезды молчат."

async def send_morning_news():
    if SUBSCRIBED_CHAT_ID == 0: return
    loop = asyncio.get_event_loop()
    weather = await loop.run_in_executor(None, get_weather)
    currency = await loop.run_in_executor(None, get_currency)
    horo = await loop.run_in_executor(None, get_full_horoscope)
    text = f"☀️ <b>Доброе утро!</b>\n\n{weather}\n{currency}\n\n{horo}"
    if len(text) > 4096:
        for x in range(0, len(text), 4096): await bot.send_message(SUBSCRIBED_CHAT_ID, text[x:x+4096], parse_mode="HTML")
    else: await bot.send_message(SUBSCRIBED_CHAT_ID, text, parse_mode="HTML")

# --- ХЕНДЛЕРЫ ---
@dp.message(F.text.lower().startswith(("найди", "где")))
async def start_search(message: Message, state: FSMContext):
    await state.update_data(q=" ".join(message.text.split()[1:]))
    await state.set_state(SearchState.waiting_for_location)
    if message.chat.type == "private":
        await message.answer("Кнопка 👇", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Поделиться", request_location=True)]], resize_keyboard=True))
    else: await message.answer("Скрепка -> Геопозиция")

@dp.message(F.location)
async def handle_loc(message: Message, state: FSMContext):
    if await state.get_state() == SearchState.waiting_for_location:
        data = await state.get_data()
        await message.reply(f"🔎 <a href='https://www.google.com/maps/search/{data.get('q')}/@{message.location.latitude},{message.location.longitude},15z'>Карта</a>", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        await state.clear()

@dp.message(Command("say"))
async def cmd_say(message: Message):
    try: await message.delete()
    except: pass
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return
    fname = f"tts_{message.message_id}.mp3"
    try:
        await edge_tts.Communicate(args[1], VOICE).save(fname)
        await message.answer_voice(FSInputFile(fname))
    except: pass
    finally:
        if os.path.exists(fname): os.remove(fname)

@dp.message(Command("test_news"))
async def cmd_test_news(message: Message):
    global SUBSCRIBED_CHAT_ID
    SUBSCRIBED_CHAT_ID = message.chat.id
    await message.answer("Проверяю СМИ...")
    await check_news_feed(force_send=True)

@dp.message(Command("test_mchs"))
async def cmd_test_mchs(message: Message):
    global SUBSCRIBED_CHAT_ID
    SUBSCRIBED_CHAT_ID = message.chat.id
    await message.answer("Читаем МЧС (тест)...")
    await check_mchs_warnings(force_send=True)

@dp.message(Command("test_morning"))
async def cmd_test_morning(message: Message):
    global SUBSCRIBED_CHAT_ID
    SUBSCRIBED_CHAT_ID = message.chat.id
    await message.answer("Собираю дайджест...")
    await send_morning_news()

@dp.message(F.voice | F.video_note)
async def handle_voice(message: Message):
    fname = f"voice_{message.voice.file_id if message.voice else message.video_note.file_id}.ogg"
    msg = await message.reply("⏳")
    try:
        file = await bot.get_file(message.voice.file_id if message.voice else message.video_note.file_id)
        await bot.download_file(file.file_path, fname)
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: model.transcribe(fname, language="ru", fp16=False, beam_size=5, temperature=0))
        text = res['text']
        await msg.edit_text(f"🗣 <b>Текст:</b>\n{text}" if text.strip() else "🤷‍♂️", parse_mode="HTML")
    except: await msg.edit_text("❌")
    finally:
        if os.path.exists(fname): os.remove(fname)

async def main():
    print("Бот запущен!")
    scheduler.add_job(send_morning_news, trigger="cron", hour=7, minute=0)
    scheduler.add_job(check_news_feed, trigger="interval", minutes=15)
    scheduler.add_job(check_mchs_warnings, trigger="interval", minutes=10)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try: asyncio.run(main())
    except KeyboardInterrupt: print("Stop")
