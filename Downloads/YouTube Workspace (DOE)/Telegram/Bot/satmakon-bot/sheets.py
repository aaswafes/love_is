import os
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

RAW_HEADERS = ["Sana & Vaqt", "Username", "Ism", "User ID", "Mijoz xabari", "Bot javobi", "Holat"]
ADMIN_HEADERS = ["Username", "Ism", "User ID", "Oxirgi xabar sanasi", "Xulosa", "Izoh"]


def _connect():
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if not creds_json:
        logger.warning("[Sheets] GOOGLE_CREDENTIALS missing")
        return None, None
    if not sheet_id:
        logger.warning("[Sheets] GOOGLE_SHEET_ID missing")
        return None, None

    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)

    # Tab 1: raw conversation log
    try:
        raw_sheet = spreadsheet.worksheet("Suhbatlar")
    except gspread.WorksheetNotFound:
        raw_sheet = spreadsheet.add_worksheet(title="Suhbatlar", rows=1000, cols=10)
        raw_sheet.insert_row(RAW_HEADERS, 1)
        _format_header(raw_sheet)

    # Tab 2: admin summary
    try:
        admin_sheet = spreadsheet.worksheet("Admin")
    except gspread.WorksheetNotFound:
        admin_sheet = spreadsheet.add_worksheet(title="Admin", rows=1000, cols=10)
        admin_sheet.insert_row(ADMIN_HEADERS, 1)
        _format_header(admin_sheet)

    return raw_sheet, admin_sheet


def _format_header(sheet):
    try:
        sheet.format("A1:G1", {
            "backgroundColor": {"red": 0.13, "green": 0.13, "blue": 0.45},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "CENTER",
        })
    except Exception:
        pass


def detect_status(bot_reply: str) -> str:
    reply = bot_reply.lower()
    if any(w in reply for w in ["ro'yxatdan o'tdingiz", "yozib oldim", "guruhga qo'shdim", "yozildingiz"]):
        return "✅ Yozildi"
    if any(w in reply for w in ["markazga keling", "tashrif buyuring", "kelib ko'ring", "sinov darsi"]):
        return "📍 Kelmoqchi"
    if any(w in reply for w in ["qo'ng'iroq qiling", "telefon qiling", "+998"]):
        return "📞 Qo'ng'iroq qilmoqchi"
    if any(w in reply for w in ["o'ylab ko'raman", "maslahatlash", "qayta bog'lan", "o'ylab ko'ring"]):
        return "🤔 O'ylab ko'rmoqda"
    return "💬 Suhbat davom etmoqda"


def detect_conclusion(user_msg: str, bot_reply: str) -> str:
    combined = (user_msg + " " + bot_reply).lower()

    if any(w in combined for w in ["ro'yxatdan o'tdingiz", "yozib oldim", "guruhga qo'shdim", "yozildingiz"]):
        return "✅ Yozildi"
    if any(w in combined for w in ["kelaman", "boraman", "sinov darsi", "kelib ko'raman"]):
        return "📍 Kelmoqchi"
    if any(w in combined for w in ["qo'ng'iroq qilaman", "telefon", "zang uraman"]):
        return "📞 Qo'ng'iroq qilmoqchi"
    if any(w in combined for w in ["o'ylab ko'raman", "keyin", "hozir emas", "keyinroq"]):
        return "🤔 O'ylab ko'rmoqda"
    if any(w in combined for w in ["narx", "qancha", "to'lov"]):
        return "💰 Narx so'radi"
    if any(w in combined for w in ["manzil", "qayer", "joylash"]):
        return "📍 Manzil so'radi"
    if any(w in combined for w in ["men bilaman", "kerak emas", "qiziqmayman"]):
        return "❌ Qiziqmadi"
    return "💬 Ma'lumot oldi"


def log_message(username: str, full_name: str, user_id: int, user_msg: str, bot_reply: str):
    for attempt in range(2):
        try:
            raw_sheet, admin_sheet = _connect()
            if not raw_sheet:
                return

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            uname = f"@{username}" if username else "-"
            fname = full_name or "-"
            uid = str(user_id)

            # --- Tab 1: append raw row ---
            status = detect_status(bot_reply)
            raw_sheet.append_row(
                [now, uname, fname, uid, user_msg, bot_reply, status],
                value_input_option="USER_ENTERED",
            )

            # --- Tab 2: upsert admin summary row ---
            conclusion = detect_conclusion(user_msg, bot_reply)
            all_rows = admin_sheet.get_all_values()
            existing_row = None
            row_index = None
            for i, row in enumerate(all_rows[1:], start=2):  # skip header
                if len(row) >= 3 and row[2] == uid:
                    existing_row = row
                    row_index = i
                    break

            if existing_row:
                admin_sheet.update(f"D{row_index}:F{row_index}", [[now, conclusion, user_msg[:100]]])
            else:
                admin_sheet.append_row(
                    [uname, fname, uid, now, conclusion, user_msg[:100]],
                    value_input_option="USER_ENTERED",
                )
            return
        except Exception as e:
            logger.error(f"[Sheets] attempt {attempt + 1} failed: {e}")
