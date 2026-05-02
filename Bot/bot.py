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

# Conversation states
CHON_TEN, NHAP_CA = range(2)

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
    staff_list = get_all_staff()
    for s in staff_list:
        if s.get('id','').lower() == name.lower() or s.get('name','').lower() == name.lower():
            return s
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

# ═══ /dangky — Bước 1: hỏi tên ═══
async def dangky(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    staff_list = get_all_staff()
    if not staff_list:
        await update.message.reply_text("❌ Chưa có nhân sự nào trong hệ thống.")
        return ConversationHandler.END

    # Tạo bàn phím tên nhân viên
    names = [s['name'] for s in staff_list if s.get('name')]
    # Chia thành hàng 3 người
    keyboard = [names[i:i+3] for i in range(0, len(names), 3)]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "👤 Bạn là ai? Chọn tên hoặc gõ tên của bạn:",
        reply_markup=reply_markup
    )
    return CHON_TEN

# ═══ Bước 2: nhận tên → hỏi ca ═══
async def nhan_ten(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ten = update.message.text.strip()
    staff = find_staff_by_name(ten)

    if not staff:
        await update.message.reply_text(
            f"❌ Không tìm thấy '{ten}' trong hệ thống.\n"
            "Thử lại hoặc nhắn Admin để được thêm vào.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    dept = staff.get('dept', [])
    weeks = get_3_weeks()

    msg = f"✅ Xin chào {staff['name']}!\n"
    msg += f"Mảng: {', '.join(dept)}\n\n"
    msg += "📅 3 tuần tới:\n"
    for week in weeks:
        wn = get_week_num(week[0])
        msg += f"  Tuần {wn}: {week[0].strftime('%d/%m')} → {week[6].strftime('%d/%m/%Y')}\n"

    msg += "\n📝 Gửi ca rảnh theo định dạng:\n"
    msg += "`T2:1,3 T3:2 T5:1,2,3,4`\n\n"

    if any(d in dept for d in ['xld','robux']):
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

    ctx.user_data['staff'] = staff
    ctx.user_data['weeks'] = [[d.strftime('%Y-%m-%d') for d in w] for w in weeks]

    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return NHAP_CA

# ═══ Bước 3: nhận ca và lưu ═══
async def nhan_ca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    staff = ctx.user_data.get('staff', {})
    weeks = ctx.user_data.get('weeks', [])
    dept  = staff.get('dept', [])
    sid   = staff.get('id', '')

    day_map = {'T2':0,'T3':1,'T4':2,'T5':3,'T6':4,'T7':5,'CN':6}
    week = weeks[0] if weeks else []

    reg_data = {}
    saved = []

    try:
        for part in text.upper().split():
            if ':' not in part:
                continue
            day_str, shifts_str = part.split(':', 1)
            if day_str == 'CN':
                pass
            else:
                day_str = day_str.capitalize()
            day_idx = day_map.get(day_str)
            if day_idx is None or day_idx >= len(week):
                continue
            date = week[day_idx]

            for c in shifts_str.split(','):
                c = c.strip().lower()
                if c in ['1','2','3','4']:
                    shift_name = XLD_SHIFTS[c]
                    if 'xld' in dept:
                        key = f"xld_{date}"
                        if key not in reg_data:
                            reg_data[key] = []
                        if shift_name not in reg_data[key]:
                            reg_data[key].append(shift_name)
                            saved.append(f"{day_str} {shift_name} (XLĐ)")
                    if 'robux' in dept:
                        key = f"robux_{date}"
                        if key not in reg_data:
                            reg_data[key] = []
                        if shift_name not in reg_data[key]:
                            reg_data[key].append(shift_name)
                            saved.append(f"{day_str} {shift_name} (Robux)")
                elif c in ['s','t']:
                    shift_name = GC_SHIFTS[c]
                    if 'giftcard' in dept:
                        key = f"gc_{date}"
                        if key not in reg_data:
                            reg_data[key] = []
                        if shift_name not in reg_data[key]:
                            reg_data[key].append(shift_name)
                            saved.append(f"{day_str} {shift_name} (GC)")
    except Exception as e:
        await update.message.reply_text(
            "❌ Sai định dạng. Thử lại:\n`T2:1,3 T4:s`",
            parse_mode='Markdown'
        )
        return NHAP_CA

    if not reg_data:
        await update.message.reply_text(
            "❌ Không nhận được ca nào hợp lệ.\n"
            "Kiểm tra lại định dạng: `T2:1,3 T4:2`",
            parse_mode='Markdown'
        )
        return NHAP_CA

    db.reference(f'pcu/registrations/{sid}').update(reg_data)

    msg = f"✅ Đã lưu {len(saved)} ca cho {staff['name']}:\n\n"
    for s in saved:
        msg += f"  • {s}\n"
    msg += "\nDùng /lichtoi để xem lại."

    await update.message.reply_text(msg)
    return ConversationHandler.END

async def lichtoi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 Bạn là ai? Nhập tên của bạn:")
    return CHON_TEN

async def lichtoi_nhan_ten(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ten = update.message.text.strip()
    staff = find_staff_by_name(ten)
    if not staff:
        await update.message.reply_text(f"❌ Không tìm thấy '{ten}'.")
        return ConversationHandler.END

    await update.message.reply_text("⏳ Đang tải lịch của bạn...")
    try:
        key = os.environ.get("SCREENSHOT_KEY")
        web_url = f"https://pcu-schedule-web-production.up.railway.app/pcu-schedule.html?page=register&staff={staff['id']}"

        api_url = (
            f"https://api.screenshotone.com/take"
            f"?access_key={key}"
            f"&url={web_url}"
            f"&viewport_width=1400"
            f"&viewport_height=900"
            f"&full_page=false"
            f"&format=jpg"
            f"&image_quality=80"
            f"&delay=4"
        )

        import urllib.request
        from io import BytesIO
        img_data = urllib.request.urlopen(api_url).read()
        await update.message.reply_photo(
            photo=BytesIO(img_data),
            caption=f"📅 Lịch đăng ký ca của {staff['name']}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {str(e)}")

    return ConversationHandler.END

# ═══ /huydangky ═══
async def huydangky(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 Nhập tên của bạn để hủy đăng ký:")
    return CHON_TEN

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

async def lichchung(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Đang tải lịch trực...")
    try:
        key = os.environ.get("SCREENSHOT_KEY")
web_url = "https://pcu-schedule-web-production.up.railway.app/pcu-schedule.html?page=view-schedule"
        api_url = (
            f"https://api.screenshotone.com/take"
            f"?access_key={key}"
            f"&url={web_url}"
            f"&viewport_width=1400"
            f"&viewport_height=900"
            f"&full_page=false"
            f"&format=jpg"
            f"&image_quality=80"
            f"&delay=5"
        )
        import urllib.request
        from io import BytesIO
        img_data = urllib.request.urlopen(api_url).read()
        await update.message.reply_photo(
            photo=BytesIO(img_data),
            caption="📋 Lịch trực tuần này"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {str(e)}")
# ═══ MAIN ═══
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation đăng ký
    conv_dangky = ConversationHandler(
        entry_points=[CommandHandler('dangky', dangky)],
        states={
            CHON_TEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, nhan_ten)],
            NHAP_CA:  [MessageHandler(filters.TEXT & ~filters.COMMAND, nhan_ca)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Conversation xem lịch cá nhân
    conv_lichtoi = ConversationHandler(
        entry_points=[CommandHandler('lichtoi', lichtoi)],
        states={
            CHON_TEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, lichtoi_nhan_ten)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Conversation hủy đăng ký
    conv_huy = ConversationHandler(
        entry_points=[CommandHandler('huydangky', huydangky)],
        states={
            CHON_TEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, huydangky_nhan_ten)],
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