"""RUDN Student Bot MVP. Python 3.11+."""
import asyncio
import os
from datetime import date, timedelta
from html import escape

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN', '')
DB = os.getenv('DB_PATH', 'bot.db')
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()}
router = Router()
MENU = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='📅 Сегодня'), KeyboardButton(text='📆 Неделя')],
    [KeyboardButton(text='📚 Домашнее задание'), KeyboardButton(text='👤 Моя группа')],
], resize_keyboard=True)

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript('''
        CREATE TABLE IF NOT EXISTS users (tg_id INTEGER PRIMARY KEY, group_code TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS editors (tg_id INTEGER NOT NULL, group_code TEXT NOT NULL,
            PRIMARY KEY(tg_id, group_code));
        CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_code TEXT NOT NULL, day TEXT NOT NULL, start_time TEXT NOT NULL,
            subject TEXT NOT NULL, room TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual',
            UNIQUE(group_code, day, start_time, subject));
        CREATE TABLE IF NOT EXISTS homework (id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_code TEXT NOT NULL, subject TEXT NOT NULL, due_date TEXT NOT NULL,
            content TEXT NOT NULL, author_id INTEGER NOT NULL);
        ''')
        await db.execute('''CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER NOT NULL,
            group_code TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL,
            action TEXT NOT NULL, group_code TEXT NOT NULL,
            target_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        await db.commit()

async def group_for(uid):
    async with aiosqlite.connect(DB) as db:
        async with db.execute('SELECT group_code FROM users WHERE tg_id=?', (uid,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def can_edit(uid, group):
    if uid in ADMIN_IDS:
        return True
    async with aiosqlite.connect(DB) as db:
        async with db.execute('SELECT 1 FROM editors WHERE tg_id=? AND group_code=?', (uid, group)) as cur:
            return await cur.fetchone() is not None

@router.message(CommandStart())
async def start(message: Message):
    await message.answer('🎓 RUDN Student Bot\n\nУкажи свою группу: /group ЭЭКбд-04-26\n'
                         'После этого будут доступны расписание и ДЗ.\n/help — команды.', reply_markup=MENU)

@router.message(Command('help'))
async def help_cmd(message: Message):
    await message.answer('Команды:\n/group КОД — выбрать группу\n/today — сегодня\n/week — 7 дней\n/hw — домашние задания\n'
                         '/addhw ПРЕДМЕТ | ГГГГ-ММ-ДД | ЗАДАНИЕ — добавить ДЗ (редактор)\n'
                         '/addlesson ГГГГ-ММ-ДД | ЧЧ:ММ | ПРЕДМЕТ | АУДИТОРИЯ — добавить пару (редактор)\n'
                         '/apply — заявка на роль старосты\n/pending — заявки (админ)\n/approve ID — подтвердить (админ)\n/reject ID — отклонить (админ)\n/revoke TG_ID КОД — отозвать права (админ)\n'
                         '/edithw ID | ПРЕДМЕТ | ГГГГ-ММ-ДД | ЗАДАНИЕ — изменить ДЗ (староста)\n'
                         '/delhw ID — удалить ДЗ (староста)\n/dellesson ID — удалить пару (староста)\n'
                         '/grant TG_ID КОД_ГРУППЫ — назначить редактора (администратор)')

@router.message(Command('group'))
async def set_group(message: Message):
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2 or not 2 <= len(parts[1].strip()) <= 40:
        return await message.answer('Пример: /group ЭЭКбд-04-26')
    group = parts[1].strip().upper()
    async with aiosqlite.connect(DB) as db:
        await db.execute('INSERT INTO users(tg_id,group_code) VALUES(?,?) ON CONFLICT(tg_id) DO UPDATE SET group_code=excluded.group_code', (message.from_user.id, group))
        await db.commit()
    await message.answer(f'✅ Группа выбрана: {escape(group)}', reply_markup=MENU)

async def show_lessons(message, days):
    group = await group_for(message.from_user.id)
    if not group:
        return await message.answer('Сначала выбери группу: /group ЭЭКбд-04-26')
    today = date.today()
    end = today + timedelta(days=days-1)
    async with aiosqlite.connect(DB) as db:
        async with db.execute('SELECT id,day,start_time,subject,room,source FROM lessons WHERE group_code=? AND day BETWEEN ? AND ? ORDER BY day,start_time', (group, today.isoformat(), end.isoformat())) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await message.answer('Пока нет подтверждённого расписания на этот период. Это не означает, что пар нет.')
    lines = [f'📅 Расписание: {escape(group)}']
    for lesson_id, day, tm, subject, room, source in rows:
        lines.append(f'#{lesson_id} {day} {tm} — {escape(subject)}' + (f' ({escape(room)})' if room else '') + (' [вручную]' if source == 'manual' else ''))
    await message.answer('\n'.join(lines)[:4000])

@router.message(Command('today'))
@router.message(F.text == '📅 Сегодня')
async def today_cmd(message: Message):
    await show_lessons(message, 1)

@router.message(Command('week'))
@router.message(F.text == '📆 Неделя')
async def week_cmd(message: Message):
    await show_lessons(message, 7)

@router.message(Command('hw'))
@router.message(F.text == '📚 Домашнее задание')
async def hw_cmd(message: Message):
    group = await group_for(message.from_user.id)
    if not group:
        return await message.answer('Сначала выбери группу: /group ЭЭКбд-04-26')
    async with aiosqlite.connect(DB) as db:
        async with db.execute('SELECT id,subject,due_date,content FROM homework WHERE group_code=? AND due_date>=? ORDER BY due_date LIMIT 20', (group, date.today().isoformat())) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await message.answer('📚 Актуальных домашних заданий пока не добавлено.')
    await message.answer(('📚 ДЗ для ' + escape(group) + '\n\n' + '\n\n'.join(f'• #{i} {escape(s)} — до {d}\n{escape(c)}' for i,s,d,c in rows))[:4000])

@router.message(F.text == '👤 Моя группа')
async def profile(message: Message):
    group = await group_for(message.from_user.id)
    await message.answer(f'👤 Группа: {escape(group) if group else "не выбрана"}\nИзменить: /group КОД')

@router.message(Command('grant'))
async def grant(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer('⛔ Только администратор.')
    args = (message.text or '').split()
    if len(args) != 3 or not args[1].isdigit():
        return await message.answer('Формат: /grant 123456789 ЭЭКбд-04-26')
    async with aiosqlite.connect(DB) as db:
        await db.execute('INSERT OR IGNORE INTO editors(tg_id,group_code) VALUES(?,?)', (int(args[1]), args[2].upper()))
        await db.commit()
    await message.answer('✅ Редактор назначен.')

@router.message(Command('addhw'))
async def add_hw(message: Message):
    group = await group_for(message.from_user.id)
    if not group:
        return await message.answer('Сначала выбери группу.')
    if not await can_edit(message.from_user.id, group):
        return await message.answer('⛔ Добавлять ДЗ могут редакторы группы.')
    raw = (message.text or '').partition(' ')[2]
    parts = [x.strip() for x in raw.split('|', 2)]
    if len(parts) != 3 or not all(parts):
        return await message.answer('Формат: /addhw Математика | 2026-11-20 | Решить №5')
    try:
        date.fromisoformat(parts[1])
    except ValueError:
        return await message.answer('Дата должна быть в формате ГГГГ-ММ-ДД.')
    if len(parts[0]) > 150 or len(parts[2]) > 2500:
        return await message.answer('Слишком длинный текст.')
    async with aiosqlite.connect(DB) as db:
        await db.execute('INSERT INTO homework(group_code,subject,due_date,content,author_id) VALUES(?,?,?,?,?)', (group, *parts, message.from_user.id))
        await db.commit()
    await message.answer('✅ Домашнее задание добавлено.')

@router.message(Command('addlesson'))
async def add_lesson(message: Message):
    group = await group_for(message.from_user.id)
    if not group or not await can_edit(message.from_user.id, group):
        return await message.answer('⛔ Нужны права редактора группы.')
    parts = [x.strip() for x in (message.text or '').partition(' ')[2].split('|')]
    if len(parts) != 4 or not all(parts[:3]):
        return await message.answer('Формат: /addlesson 2026-11-20 | 09:00 | Экономика | 101')
    try:
        date.fromisoformat(parts[0])
        from datetime import time
        time.fromisoformat(parts[1])
    except ValueError:
        return await message.answer('Проверь дату и время.')
    if any(len(p)>150 for p in parts):
        return await message.answer('Слишком длинное поле.')
    async with aiosqlite.connect(DB) as db:
        await db.execute('''INSERT INTO lessons(group_code,day,start_time,subject,room,source)
            VALUES(?,?,?,?,?,'manual') ON CONFLICT(group_code,day,start_time,subject)
            DO UPDATE SET room=excluded.room,source='manual' ''', (group,*parts))
        await db.commit()
    await message.answer('✅ Пара сохранена.')


async def audit(db, uid: int, action: str, group: str, target: int | None = None):
    await db.execute('INSERT INTO audit(actor_id,action,group_code,target_id) VALUES(?,?,?,?)',
                     (uid, action, group, target))

@router.message(Command('myid'))
async def myid(message: Message):
    await message.answer(f'Твой Telegram ID: {message.from_user.id}')

@router.message(Command('apply'))
async def apply(message: Message, bot: Bot):
    group = await group_for(message.from_user.id)
    if not group:
        return await message.answer('Сначала выбери группу: /group КОД')
    if await can_edit(message.from_user.id, group):
        return await message.answer('У тебя уже есть права старосты этой группы.')
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT id FROM applications WHERE tg_id=? AND group_code=? AND status='pending'",
                              (message.from_user.id, group)) as cur:
            if await cur.fetchone():
                return await message.answer('Заявка уже ожидает рассмотрения.')
        cur = await db.execute('INSERT INTO applications(tg_id,group_code) VALUES(?,?)',
                               (message.from_user.id, group))
        await db.commit()
        application_id = cur.lastrowid
    await message.answer(f'Заявка #{application_id} отправлена. Администратор проверит твою роль.')
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, f'Новая заявка #{application_id} на старосту\n'
                                         f'Группа: {escape(group)}\nTelegram ID: {message.from_user.id}\n'
                                         f'/approve {application_id} или /reject {application_id}')
        except Exception:
            pass  # Администратор должен сначала начать диалог с ботом

@router.message(Command('pending'))
async def pending(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer('⛔ Только администратор.')
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT id,tg_id,group_code FROM applications WHERE status='pending' ORDER BY id LIMIT 30") as cur:
            rows = await cur.fetchall()
    await message.answer('\n'.join(f'#{i}: {uid} — {escape(group)}' for i,uid,group in rows)
                         if rows else 'Нет заявок.')

async def decide(message: Message, bot: Bot, approved: bool):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer('⛔ Только администратор.')
    args = (message.text or '').split()
    if len(args) != 2 or not args[1].isdigit():
        return await message.answer('Укажи ID заявки, например /approve 3')
    async with aiosqlite.connect(DB) as db:
        await db.execute('BEGIN IMMEDIATE')
        async with db.execute("SELECT tg_id,group_code FROM applications WHERE id=? AND status='pending'",
                              (int(args[1]),)) as cur:
            row = await cur.fetchone()
        if not row:
            await db.rollback()
            return await message.answer('Заявка не найдена или уже обработана.')
        uid, group = row
        if approved:
            await db.execute('INSERT OR IGNORE INTO editors(tg_id,group_code) VALUES(?,?)', (uid, group))
        await db.execute('UPDATE applications SET status=? WHERE id=?',
                         ('approved' if approved else 'rejected', int(args[1])))
        await audit(db, message.from_user.id, 'approve' if approved else 'reject', group, uid)
        await db.commit()
    await message.answer('Заявка обработана.')
    try:
        await bot.send_message(uid, f'Заявка на старосту группы {escape(group)}: '
                                    + ('одобрена ✅' if approved else 'отклонена.'))
    except Exception:
        pass

@router.message(Command('approve'))
async def approve(message: Message, bot: Bot):
    await decide(message, bot, True)

@router.message(Command('reject'))
async def reject(message: Message, bot: Bot):
    await decide(message, bot, False)

@router.message(Command('revoke'))
async def revoke(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer('⛔ Только администратор.')
    args = (message.text or '').split()
    if len(args) != 3 or not args[1].isdigit():
        return await message.answer('Формат: /revoke 123456789 ЭЭКбд-04-26')
    uid, group = int(args[1]), args[2].upper()
    async with aiosqlite.connect(DB) as db:
        await db.execute('DELETE FROM editors WHERE tg_id=? AND group_code=?', (uid, group))
        await audit(db, message.from_user.id, 'revoke', group, uid)
        await db.commit()
    await message.answer('Права старосты отозваны.')

@router.message(Command('edithw'))
async def edit_hw(message: Message):
    parts = [x.strip() for x in (message.text or '').partition(' ')[2].split('|', 3)]
    if len(parts) != 4 or not parts[0].isdigit() or not all(parts[1:]):
        return await message.answer('Формат: /edithw 3 | Математика | 2026-12-01 | Решить №5')
    try:
        date.fromisoformat(parts[2])
    except ValueError:
        return await message.answer('Неверная дата.')
    if len(parts[1]) > 150 or len(parts[3]) > 2500:
        return await message.answer('Слишком длинный текст.')
    group = await group_for(message.from_user.id)
    if not group or not await can_edit(message.from_user.id, group):
        return await message.answer('⛔ Только староста группы.')
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('UPDATE homework SET subject=?,due_date=?,content=? WHERE id=? AND group_code=?',
                               (parts[1], parts[2], parts[3], int(parts[0]), group))
        if cur.rowcount:
            await audit(db, message.from_user.id, 'edithw', group, int(parts[0]))
        await db.commit()
    await message.answer('ДЗ обновлено.' if cur.rowcount else 'ДЗ этой группы не найдено.')

async def delete_item(message: Message, table: str):
    args = (message.text or '').split()
    if len(args) != 2 or not args[1].isdigit():
        return await message.answer('Укажи числовой ID из списка.')
    group = await group_for(message.from_user.id)
    if not group or not await can_edit(message.from_user.id, group):
        return await message.answer('⛔ Только староста группы.')
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(f'DELETE FROM {table} WHERE id=? AND group_code=?', (int(args[1]), group))
        if cur.rowcount:
            await audit(db, message.from_user.id, 'delete_' + table, group, int(args[1]))
        await db.commit()
    await message.answer('Удалено.' if cur.rowcount else 'Запись этой группы не найдена.')

@router.message(Command('delhw'))
async def del_hw(message: Message):
    await delete_item(message, 'homework')

@router.message(Command('dellesson'))
async def del_lesson(message: Message):
    await delete_item(message, 'lessons')

async def main():
    if not TOKEN or TOKEN == 'put_your_botfather_token_here':
        raise RuntimeError('Укажи BOT_TOKEN в .env')
    await init_db()
    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
