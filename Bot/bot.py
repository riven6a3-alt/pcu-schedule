import os, json, logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (Application, CommandHandler, ConversationHandler,
                          MessageHandler, filters, ContextTypes)
import firebase_admin
from firebase_admin import credentials, db

BOT_TOKEN    = os.environ.get("BOT_TOKEN")
FIREBASE_URL = os.environ.get("FIREBASE_URL")
KEY_JSON     = os.environ.get("FIREBASE_KEY_JSON")

key_dict = json.loads(KEY_JSON)
cred = credentials.Certificate(key_dict)
firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_URL})

logging.basicConfig(level=logging.INFO)

XLD_SHIFTS = {'1':'Ca 1','2':'Ca 2','3':'Ca 3','4':'Ca 4'}
GC_SHIFTS  = {'s':'Ca sáng','t':'Ca tối'}

# States
CHON_TEN, CHON_TUAN, NHAP_CA = range(3)
LICHTOI_TEN = 10

def get_week_num(d):
    return d.isocalendar()[1]

def get_monday():
    today = datetime.today()
    return today - timedelta(days=today.weekday())

def get_3_weeks():
    mon = get_monday()
    weeks = []
    for i in range(3):
        start = mon + timedelta(weeks=i)
        weeks.append([start + timedelta(days=j) for j in range(7)])
    return weeks

def get_all_staff():
    data = db.reference('pcu/staff').get() or []
    return [s for s in data if isinstance(s, dict)]

def find_staff_by_name(name):
    for s in get_all_staff():
        if s.get('id','').lower() == name.lower() or s.get('name','').lower() == name.lower():
            return s
    return None

def chup_anh(web_url):
    import urllib.request
    key = os.environ.get("SCREENSHOT_KEY", "")
    if not key:
        return None
    api_url = (
        f"https://api.screenshotone.com/take"
        f"?access_key={key}"
        f"&url={web_url}"
        f"&viewport_width=1400"
        f"&viewport_height=900"
        f"&full_page=false"
        f"&format=jpg"
        f"&image_quality=80"
        f"&delay=8"
    )
    try:
        return urllib.request.urlopen(api_url, timeout=30).read()
    except:
        return None

# ═══ /start ═══
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Bot lịch trực PCU.\n\n"
        "Các lệnh:\n"
        "/dangky — Đăng ký ca rảnh\n"
        "/lichtoi — Xem ca đã đăng ký\n"
        "/lichchung — Xem lịch trực tuần này\n"
        "/huydangky — Hủy toàn bộ đăng ký"
    )

# ═══ /dangky ═══
async def dangky(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    staff_list = get_all_staff()
    if not staff_list:
        await update.message.reply_text("❌ Chưa có nhân sự nào trong hệ thống.")
        return ConversationHandler.END

    names = [s['name'] for s in staff_list if s.get('name')]
    keyboard = [names[i:i+3] for i in range(0, len(names), 3)]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "👤 Bạn là ai? Chọn tên hoặc gõ tên:",
        reply_markup=reply_markup
    )
    return CHON_TEN

async def nhan_ten(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ten = update.message.text.strip()
    staff = find_staff_by_name(ten)

    if not staff:
        await update.message.reply_text(
            f"❌ Không tìm thấy '{ten}'.\nThử lại hoặc nhắn Admin.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    ctx.user_data['staff'] = staff

    # Hỏi chọn tuần
    weeks = get_3_weeks()
    week_labels = []
    for week in weeks:
        wn = get_week_num(week[0])
        label = f"Tuần {wn} ({week[0].strftime('%d/%m')}–{week[6].strftime('%d/%m')})"
        week_labels.append(label)

    ctx.user_data['weeks_data'] = [
        [d.strftime('%Y-%m-%d') for d in w] for w in weeks
    ]
    ctx.user_data['week_labels'] = week_labels

    keyboard = [[w] for w in week_labels]
    keyboard.append(["📅 Tất cả 3 tuần"])
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        f"✅ Xin chào {staff['name']}!\n\nChọn tuần muốn đăng ký:",
        reply_markup=reply_markup
    )
    return CHON_TUAN

async def nhan_tuan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chon = update.message.text.strip()
    staff = ctx.user_data.get('staff', {})
    weeks_data = ctx.user_data.get('weeks_data', [])
    week_labels = ctx.user_data.get('week_labels', [])
    dept = staff.get('dept', [])

    # Xác định tuần nào được chọn
    if chon == "📅 Tất cả 3 tuần":
        selected_weeks = weeks_data
        tuan_str = "3 tuần tới"
    else:
        idx = next((i for i, l in enumerate(week_labels) if l == chon), 0)
        selected_weeks = [weeks_data[idx]]
        tuan_str = chon

    ctx.user_data['selected_weeks'] = selected_weeks

    msg = f"📝 Đăng ký ca cho {staff['name']} — {tuan_str}\n\n"
    msg += "Gửi ca rảnh theo định dạng:\n"
    msg += "`T2:1,3 T3:2 T5:1,2,3,4`\n\n"

    if any(d in dept for d in ['xld', 'robux']):
        msg += "Số ca XLĐ/Robux:\n"
        msg += "  1 = Ca 1 (8–12h)\n"
        msg += "  2 = Ca 2 (12–16h)\n"
        msg += "  3 = Ca 3 (16–20h)\n"
        msg += "  4 = Ca 4 (20–24h)\n\n"

    if 'giftcard' in dept:
        msg += "Ca Gift Card:\n"
        msg += "  s = Ca sáng (8–16h)\n"
        msg += "  t = Ca tối (16–24h)\n\n"

    msg += "Ví dụ: `T2:1,3 T4:2 T6:s`\n"
    msg += "Gõ /cancel để hủy"

    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return NHAP_CA

async def nhan_ca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    staff = ctx.user_data.get('staff', {})
    selected_weeks = ctx.user_data.get('selected_weeks', [])
    dept  = staff.get('dept', [])
    sid   = staff.get('id', '')

    day_map = {'T2':0,'T3':1,'T4':2,'T5':3,'T6':4,'T7':5,'CN':6}

    reg_data = {}
    saved = []

    try:
        for part in text.upper().split():
            if ':' not in part:
                continue
            day_str, shifts_str = part.split(':', 1)
            if day_str != 'CN':
                day_str = day_str.capitalize()
            day_idx = day_map.get(day_str)
            if day_idx is None:
                continue

            # Lưu vào tất cả tuần được chọn
            for week in selected_weeks:
                if day_idx >= len(week):
                    continue
                date = week[day_idx]

                for c in shifts_str.split(','):
                    c = c.strip().lower()
                    if c in ['1','2','3','4']:
                        shift_name = XLD_SHIFTS[c]
                        if 'xld' in dept:
                            key = f"xld_{date}"
                            if key not in reg_data: reg_data[key] = []
                            if shift_name not in reg_data[key]:
                                reg_data[key].append(shift_name)
                                saved.append(f"{day_str} {shift_name} (XLĐ) [{date}]")
                        if 'robux' in dept:
                            key = f"robux_{date}"
                            if key not in reg_data: reg_data[key] = []
                            if shift_name not in reg_data[key]:
                                reg_data[key].append(shift_name)
                                saved.append(f"{day_str} {shift_name} (Robux) [{date}]")
                    elif c in ['s','t']:
                        shift_name = GC_SHIFTS[c]
                        if 'giftcard' in dept:
                            key = f"gc_{date}"
                            if key not in reg_data: reg_data[key] = []
                            if shift_name not in reg_data[key]:
                                reg_data[key].append(shift_name)
                                saved.append(f"{day_str} {shift_name} (GC) [{date}]")
    except Exception as e:
        await update.message.reply_text("❌ Sai định dạng. Thử lại:\n`T2:1,3 T4:s`", parse_mode='Markdown')
        return NHAP_CA

    if not reg_data:
        await update.message.reply_text("❌ Không nhận được ca nào. Kiểm tra định dạng: `T2:1,3`", parse_mode='Markdown')
        return NHAP_CA

    db.reference(f'pcu/registrations/{sid}').update(reg_data)

    msg = f"✅ Đã lưu {len(saved)} ca cho {staff['name']}:\n\n"
    for s in saved:
        msg += f"  • {s}\n"
    msg += "\nDùng /lichtoi để xem lại."
    await update.message.reply_text(msg)
    return ConversationHandler.END

# ═══ /lichtoi ═══
async def lichtoi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 Bạn là ai? Nhập tên:")
    return LICHTOI_TEN

async def lichtoi_nhan_ten(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ten = update.message.text.strip()
    staff = find_staff_by_name(ten)
    if not staff:
        await update.message.reply_text(f"❌ Không tìm thấy '{ten}'.")
        return ConversationHandler.END

    # Thử chụp ảnh trước
    await update.message.reply_text("⏳ Đang tải lịch của bạn...")
    web_url = (
        f"https://pcu-schedule-web-production.up.railway.app"
        f"/pcu-schedule.html#register#{staff['id']}"
    )
    img_data = chup_anh(web_url)

    if img_data:
        from io import BytesIO
        await update.message.reply_photo(
            photo=BytesIO(img_data),
            caption=f"📅 Lịch đăng ký ca của {staff['name']}"
        )
    else:
        # Fallback: gửi text
        reg = db.reference(f"pcu/registrations/{staff['id']}").get() or {}
        if not reg:
            await update.message.reply_text(f"📭 {staff['name']} chưa đăng ký ca nào.")
            return ConversationHandler.END

        msg = f"📅 Ca đã đăng ký ({staff['name']}):\n\n"
        for key, shifts in sorted(reg.items()):
            under = key.index('_')
            dk = key[:under].upper()
            date = key[under+1:]
            try:
                d = datetime.strptime(date, '%Y-%m-%d')
                date_str = d.strftime('%d/%m/%Y')
            except:
                date_str = date
            if isinstance(shifts, list):
                msg += f"📆 {date_str} [{dk}]: {', '.join(shifts)}\n"
            elif isinstance(shifts, dict):
                msg += f"📆 {date_str} [{dk}]: {', '.join(shifts.values())}\n"
        await update.message.reply_text(msg)

    return ConversationHandler.END

# ═══ /lichchung ═══
async def lichchung(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Đang tải lịch trực...")

    # Thử chụp ảnh
    web_url = (
        "https://pcu-schedule-web-production.up.railway.app"
        "/pcu-schedule.html#view-schedule"
    )
    img_data = chup_anh(web_url)

    if img_data:
        from io import BytesIO
        await update.message.reply_photo(
            photo=BytesIO(img_data),
            caption="📋 Lịch trực tuần này"
        )
    else:
        # Fallback: gửi text
        mon = get_monday()
        wn = get_week_num(mon)
        wk = f"W{wn}"

        sched = db.reference(f"pcu/schedules/{wk}").get()
        if not sched:
            await update.message.reply_text(f"📭 Tuần {wk} chưa có lịch chính thức.")
            return

        msg = f"📋 Lịch trực {wk}:\n\n"
        for date_str, day_data in sorted(sched.items()):
            try:
                d = datetime.strptime(date_str, '%Y-%m-%d')
                msg += f"📆 {d.strftime('%d/%m (%a)')}\n"
            except:
                msg += f"📆 {date_str}\n"

            xld = day_data.get('xld', {}) or {}
            for sn, names in xld.items():
                if isinstance(names, list) and names:
                    ft = [n for n in names if n not in ['Vinh','MinhPK','VanNK']]
                    if ft:
                        msg += f"  XLĐ {sn}: {', '.join(ft)}\n"

            gc = day_data.get('gc', {}) or {}
            for sn, names in gc.items():
                if isinstance(names, list) and names:
                    msg += f"  GC {sn}: {', '.join(names)}\n"
            msg += "\n"

        await update.message.reply_text(msg[:4000])

# ═══ /huydangky ═══
async def huydangky(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 Nhập tên để hủy đăng ký:")
    return LICHTOI_TEN

async def huydangky_nhan_ten(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ten = update.message.text.strip()
    staff = find_staff_by_name(ten)
    if not staff:
        await update.message.reply_text(f"❌ Không tìm thấy '{ten}'.")
        return ConversationHandler.END
    db.reference(f"pcu/registrations/{staff['id']}").delete()
    await update.message.reply_text(f"✅ Đã hủy toàn bộ đăng ký của {staff['name']}.")
    return ConversationHandler.END

# ═══ Cancel ═══
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Đã hủy.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ═══ MAIN ═══
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_dangky = ConversationHandler(
        entry_points=[CommandHandler('dangky', dangky)],
        states={
            CHON_TEN:  [MessageHandler(filters.TEXT & ~filters.COMMAND, nhan_ten)],
            CHON_TUAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, nhan_tuan)],
            NHAP_CA:   [MessageHandler(filters.TEXT & ~filters.COMMAND, nhan_ca)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    conv_lichtoi = ConversationHandler(
        entry_points=[CommandHandler('lichtoi', lichtoi)],
        states={
            LICHTOI_TEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, lichtoi_nhan_ten)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    conv_huy = ConversationHandler(
        entry_points=[CommandHandler('huydangky', huydangky)],
        states={
            LICHTOI_TEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, huydangky_nhan_ten)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv_dangky)
    app.add_handler(conv_lichtoi)
    app.add_handler(conv_huy)
    app.add_handler(CommandHandler('lichchung', lichchung))

    print("🤖 Bot PCU đang chạy...")
    app.run_polling()

if __name__ == '__main__':
    main()