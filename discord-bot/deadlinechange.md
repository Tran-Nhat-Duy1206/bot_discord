🚀 Deadline Google Account Linking - Design Plan (v2)
🎯 Mục tiêu

Cho phép mỗi user Discord:

Liên kết nhiều Google account
Chọn account mặc định
Khi tạo Sheet/Docs:
Dùng account mặc định (không cần login lại)
Có thể mở rộng để chọn account khác

👉 Loại bỏ hoàn toàn phụ thuộc vào token global của bot

🧱 1) Hiện trạng (as-is)
Bot đang dùng _google_creds() đọc từ keys/token.json (1 account duy nhất)
create_deadline_sheet() và create_deadline_doc() luôn dùng token global
Không có khái niệm:
user account
multiple account
default account

👉 Kết quả:

Tất cả file nằm trong 1 Google Drive duy nhất (bot owner)
🆕 2) Kiến trúc mới (to-be)
🔑 2.1 Lưu nhiều Google account cho mỗi user
DB Schema mới:
CREATE TABLE IF NOT EXISTS user_google_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    google_email TEXT NOT NULL,
    token_json TEXT NOT NULL,
    scopes TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, google_email)
);
Ý nghĩa:
1 Discord user → nhiều Google account
mỗi account có:
token riêng
email
is_default:
account dùng mặc định khi tạo deadline
🔐 2.2 Bảo mật
Encrypt token_json (Fernet/AES)

Key từ env:

GOOGLE_TOKEN_ENCRYPTION_KEY
Không log token
Validate state OAuth chống CSRF
🔄 3) OAuth Flow (multi-account)
Module mới: features/google_auth.py
Core functions:
start_link_flow(user_id) -> auth_url, state
finish_link_flow(user_id, code, state) -> email, token_json
get_user_google_creds(user_id, scopes, email=None) -> Credentials
set_default_account(user_id, email)
list_accounts(user_id)
unlink_account(user_id, email)
Logic quan trọng:
Khi login:
Nếu email chưa tồn tại → thêm mới
Nếu đã tồn tại → update token
Nếu là account đầu tiên → set default
💬 4) Slash Commands mới
🔗 /deadline_google_login
Trả link OAuth
Dùng để:
login lần đầu
hoặc thêm account mới
✅ /deadline_google_verify
Xác thực OAuth
Lưu account vào DB

Thông báo:

✅ Đã liên kết: abc@gmail.com
📂 /deadline_google_accounts

Hiển thị danh sách:

1. abc@gmail.com (default)
2. xyz@gmail.com
⭐ /deadline_google_set_default email:<...>
Đổi account mặc định
❌ /deadline_google_unlink email:<...>
Xoá 1 account cụ thể
📊 /deadline_google_status
Shortcut:
account mặc định
số account đã link
⚙️ 5) Refactor create Sheet/Docs
Đổi function signature:
create_deadline_sheet(title: str, creds: Credentials)
create_deadline_doc(title: str, creds: Credentials)
Khi tạo tài liệu:
creds = get_user_google_creds(owner_id, scopes)
Trường hợp:
❌ chưa link account:
Bạn chưa liên kết Google account.
Dùng /deadline_google_login
✅ đã link:
File được tạo bằng account: abc@gmail.com
🧠 6) Logic chọn account
Phase 1 (khuyến nghị)
Luôn dùng account mặc định
Phase 2 (optional)
Cho chọn account khi tạo:
slash command option
hoặc dropdown UI
🔁 7) Migration strategy
Giai đoạn 1 (safe)
Nếu user chưa link:
DEADLINE_ALLOW_GLOBAL_GOOGLE_FALLBACK=1

→ dùng token global

Giai đoạn 2
Tắt fallback
bắt buộc user link account
🎨 8) UX đề xuất
Khi user bấm tạo Sheet/Docs
❌ chưa link:
⚠️ Bạn chưa liên kết Google account
→ /deadline_google_login
✅ đã link:
✅ File đã tạo
📧 Account: abc@gmail.com
🔐 9) OAuth Scopes
drive
documents
spreadsheets
openid
email
📁 10) Phạm vi file cần sửa
Update:
features/deadlines.py
bỏ _google_creds() global
New:
features/google_auth.py
features/deadline_google_commands.py
DB:
thêm bảng user_google_accounts
🛠 11) Kế hoạch triển khai
Tạo bảng user_google_accounts
Implement google_auth.py
Thêm commands:
login
verify
accounts
set_default
unlink
Refactor create Sheet/Docs dùng creds user
Bật fallback global
Test nhiều user + nhiều account
Tắt fallback
🧪 12) Test checklist
User A:
link 2 account
set default
User B:
link account khác
Test:
A tạo deadline → dùng account mặc định A
B tạo → dùng account B
đổi default → file tạo đúng account mới
unlink → không dùng được nữa
token refresh hoạt động