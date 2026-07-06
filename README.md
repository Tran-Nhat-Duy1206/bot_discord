# Tài liệu Giải thích Chi tiết Code các Chức năng Hệ thống CINEPLEX

Tài liệu này giải thích chi tiết cấu trúc code, logic nghiệp vụ, các câu lệnh cơ sở dữ liệu và các luồng xử lý (flow) cho các chức năng được yêu cầu trong các Sprint của dự án website bán vé xem phim CINEPLEX.

---

## MỤC LỤC
1. [Sprint 1](#sprint-1)
   - [UC26: Xác thực người dùng - Đăng nhập hệ thống](#uc26-xác-thực-người-dùng---đăng-nhập-hệ-thống)
   - [UC27: Xác thực người dùng - Đăng ký tài khoản](#uc27-xác-thực-người-dùng---đăng-ký-tài-khoản)
   - [UC28: Xác thực người dùng - Khôi phục mật khẩu](#uc28-xác-thực-người-dùng---khôi-phục-mật-khẩu)
   - [UC29: Xác thực người dùng - Đăng xuất hệ thống](#uc29-xác-thực-người-dùng---đăng-xuất-hệ-thống)
   - [UC19: Quản lý rạp và lịch chiếu - Thêm phòng chiếu mới](#uc19-quản-lý-rạp-và-lịch-chiếu---thêm-phòng-chiếu-mới)
   - [UC72: Tìm kiếm và khám phá - Tìm kiếm phim theo từ khóa](#uc72-tìm-kiếm-và-khám-phá---tìm-kiếm-phim-theo-từ-khóa)
2. [Sprint 2](#sprint-2)
   - [UC52: Đặt vé trực tuyến - Xem tạm tính và giá vé](#uc52-đặt-vé-trực-tuyến---xem-tạm-tính-và-giá-vé)
   - [UC73: Đặt vé trực tuyến - Xác nhận thông tin người dùng (Guest)](#uc73-đặt-vé-trực-tuyến---xác-nhận-thông-tin-người-dùng-guest)
3. [Sprint 3](#sprint-3)
   - [UC65: Quản lý voucher - Xem chi tiết voucher offer](#uc65-quản-lý-voucher---xem-chi-tiết-voucher-offer)
   - [UC66: Quản lý voucher - Cập nhật điều kiện sử dụng voucher](#uc66-quản-lý-voucher---cập-nhật-điều-kiện-sử-dụng-voucher)
   - [UC67: Quản lý voucher - Vô hiệu hóa voucher](#uc67-quản-lý-voucher---vô-hiệu-hóa-voucher)
   - [UC69: Đặt vé trực tuyến - Áp dụng voucher khi thanh toán](#uc69-đặt-vé-trực-tuyến---áp-dụng-voucher-khi-thanh-toán)
   - [UC53: Đặt vé trực tuyến - Cập nhật tổng tiền thanh toán sau khi áp dụng voucher](#uc53-đặt-vé-trực-tuyến---cập-nhật-tổng-tiền-thanh-toán-sau-khi-áp-dụng-voucher)
4. [Sprint 4](#sprint-4)
   - [UC45: Thông báo & Voucher - Thu hồi/Xóa thông báo đã gửi](#uc45-thông-báo--voucher---thu-hồixóa-thông-báo-đã-gửi)
   - [UC70: Thông báo và tiếp thị - Nhận thông báo phim mới/sự kiện](#uc70-thông-báo-và-tiếp-thị---nhận-thông-báo-phim-mớisự-kiện)

---

## SPRINT 1

### UC26: Xác thực người dùng - Đăng nhập hệ thống
* **Actor:** Guest, Customer, Admin
* **Mô tả:** Người dùng đăng nhập hệ thống bằng email và mật khẩu để lấy access token sử dụng cho các chức năng yêu cầu quyền hạn.
* **Đường dẫn file code:** [routers/Authentication.py](file:///e:/clone/web-ban-ve-xem-phim/routers/Authentication.py)
* **Chi tiết logic xử lý:**
  - **Pydantic Model nhận dữ liệu:** 
    ```python
    class LoginRequest(BaseModel):
        email_or_username: str = Field(..., min_length=1)
        password: str = Field(..., min_length=1)
    ```
  - **Endpoint xử lý:** `@router.post("/login")` ứng với hàm `login_user(payload: LoginRequest)`
  - **Quy trình thực hiện:**
    1. Thực hiện truy vấn kiểm tra email trong bảng `Users` kết hợp kết nối bảng `Roles` để lấy thông tin phân quyền:
       ```sql
       SELECT u.user_id, u.full_name, u.email, u.phone, u.password_hash, u.status, r.role_name
       FROM Users u
       JOIN Roles r ON u.role_id = r.role_id
       WHERE u.email = %s LIMIT 1
       ```
    2. Nếu không tìm thấy người dùng, hệ thống sẽ ném ra ngoại lệ HTTP 401: `"Mật khẩu không chính xác."` (Lưu ý: Không thông báo "Tài khoản không tồn tại" để tăng tính bảo mật, tránh bị dò quét tài khoản).
    3. Nếu tài khoản có trạng thái `'Locked'` (Bị khóa), hệ thống trả về lỗi HTTP 403: `"Tài khoản đã bị khóa."`.
    4. Xác thực mật khẩu: Sử dụng thư viện `passlib.context.CryptContext` thông qua hàm `verify_password(payload.password, user["password_hash"])` so khớp mật khẩu thuần với mật khẩu đã băm bằng thuật toán **bcrypt**. Nếu sai, trả về lỗi HTTP 401: `"Mật khẩu không chính xác."`.
    5. Tạo Token xác thực: Sử dụng thư viện `PyJWT` qua hàm `create_access_token(data: dict)` với khóa bí mật `SECRET_KEY = "CINEPLEX_BIMAT_KHONG_DUOC_DE_LO_SIEUBIMAT"`. Dữ liệu mã hóa bao gồm `user_id`, `role` và thời gian hết hạn (`exp` được thiết lập bằng thời gian hiện tại cộng thêm 24 giờ).
    6. Trả về phản hồi đăng nhập thành công chứa đầy đủ thông tin cá nhân và `access_token` để Client lưu trữ.

---

### UC27: Xác thực người dùng - Đăng ký tài khoản
* **Actor:** Guest
* **Mô tả:** Khách vãng lai đăng ký tài khoản thành viên (Customer) của hệ thống.
* **Đường dẫn file code:** [routers/Authentication.py](file:///e:/clone/web-ban-ve-xem-phim/routers/Authentication.py)
* **Chi tiết logic xử lý:**
  - **Pydantic Model nhận dữ liệu:**
    ```python
    class RegisterRequest(BaseModel):
        full_name: str = Field(..., min_length=2, max_length=100)
        phone: str = Field(..., min_length=9, max_length=20)
        email: EmailStr
        gender: Optional[str] = None
        password: str = Field(..., min_length=6, max_length=50)
        confirm_password: str = Field(..., min_length=6, max_length=50)
    ```
  - **Endpoint xử lý:** `@router.post("/register")` ứng với hàm `register_user(payload: RegisterRequest)`
  - **Quy trình thực hiện:**
    1. Kiểm tra sự trùng khớp của mật khẩu: Nếu `password != confirm_password`, hệ thống báo lỗi HTTP 400: `"Mật khẩu nhập lại không khớp."`.
    2. Kiểm tra giá trị giới tính hợp lệ (Nếu cung cấp, phải thuộc `["Nam", "Nữ"]`).
    3. Kiểm tra email duy nhất: Thực hiện truy vấn trong bảng `Users` để xem `email` đã tồn tại chưa. Nếu có, báo lỗi HTTP 409: `"Email đã được sử dụng."`.
    4. Kiểm tra số điện thoại duy nhất: Thực hiện truy vấn tương tự với cột `phone`. Nếu đã tồn tại, báo lỗi HTTP 409: `"Số điện thoại đã được sử dụng."`.
    5. Kiểm tra ký tự đặc biệt của mật khẩu: Sử dụng biểu thức chính quy (Regex) `[\x21-\x7E]+` để kiểm tra mật khẩu. Mật khẩu không được phép chứa các ký tự tiếng Việt có dấu hoặc Unicode, chỉ cho phép chữ cái không dấu, chữ số và ký tự đặc biệt ASCII.
    6. Lấy ID của vai trò `'Customer'` từ DB bằng hàm `get_customer_role_id()`.
    7. Mã hóa mật khẩu: Sử dụng `pwd_context.hash(payload.password)` băm mật khẩu bằng bcrypt.
    8. Ghi dữ liệu: Thực hiện câu lệnh SQL `INSERT INTO Users` thêm mới tài khoản với trạng thái mặc định là `'Active'`, điểm tích lũy ban đầu là `0`, và thứ hạng là `NULL` (hạng mới đăng ký).
       ```sql
       INSERT INTO Users (role_id, tier_id, full_name, email, password_hash, phone, gender, reward_points, status)
       VALUES (%s, NULL, %s, %s, %s, %s, %s, 0, 'Active')
       ```
    9. Trả về kết quả đăng ký thành công kèm thông tin chi tiết của tài khoản.

---

### UC28: Xác thực người dùng - Khôi phục mật khẩu
* **Actor:** Guest, Customer, Admin, Email/Notification Service
* **Mô tả:** Người dùng lấy lại mật khẩu thông qua mã OTP gửi tới Email đăng ký.
* **Đường dẫn file code:** [routers/Authentication.py](file:///e:/clone/web-ban-ve-xem-phim/routers/Authentication.py)
* **Chi tiết quy trình nghiệp vụ 3 bước:**

#### Bước 1: Yêu cầu gửi OTP khôi phục (`POST /forgot-password`)
1. Backend kiểm tra sự tồn tại của email trong hệ thống qua truy vấn `SELECT user_id FROM Users WHERE email = %s LIMIT 1`.
2. Sinh mã OTP ngẫu nhiên gồm 6 chữ số: `random.randint(100000, 999999)`.
3. Xác định thời gian hết hạn OTP là **5 phút** kể từ thời điểm yêu cầu (`datetime.now() + timedelta(minutes=5)`).
4. Lưu mã OTP và thời gian hết hạn vào cột `reset_otp` và `otp_expiry` của người dùng:
   ```sql
   UPDATE Users SET reset_otp = %s, otp_expiry = %s WHERE email = %s
   ```
5. Đẩy tiến trình gửi email vào tác vụ ngầm `BackgroundTasks` của FastAPI thông qua hàm `send_otp_email(payload.email, otp)`. Hàm này kết nối tới SMTP Server của Gmail (`smtp.gmail.com:587`), đăng nhập bằng email hỗ trợ của CINEPLEX (`rapchieuphim85@gmail.com`) để gửi email chứa mã OTP cho khách hàng.

#### Bước 2: Xác nhận mã OTP (`POST /verify-otp`)
1. Client gửi `VerifyOTPRequest` gồm `email` và `otp`.
2. Backend truy vấn lấy thông tin OTP từ DB: `SELECT reset_otp, otp_expiry FROM Users WHERE email = %s LIMIT 1`.
3. Kiểm tra mã OTP: Nếu không khớp hoặc không tồn tại, trả về lỗi HTTP 400: `"Mã xác nhận không chính xác."`.
4. Kiểm tra thời hạn: Nếu thời gian hiện tại vượt quá `otp_expiry`, hệ thống xóa OTP trong database và báo lỗi HTTP 400: `"Mã xác nhận đã hết hạn (quá 5 phút). Vui lòng yêu cầu mã mới."`.
5. Nếu hợp lệ, trả về thông báo xác nhận thành công để cho phép chuyển sang bước đổi mật khẩu.

#### Bước 3: Đặt lại mật khẩu mới (`POST /reset-password`)
1. Nhận thông tin gồm `email`, `otp`, `new_password`, `confirm_password`.
2. Kiểm tra tính hợp lệ của mật khẩu mới (khớp nhau, không chứa ký tự tiếng Việt có dấu).
3. Xác thực lại mã OTP và thời hạn của nó trong DB một lần nữa để tránh các cuộc tấn công gửi trực tiếp payload bỏ qua bước 2.
4. Băm mật khẩu mới bằng bcrypt và cập nhật cột `password_hash`, đồng thời xóa sạch mã OTP để tránh tái sử dụng mã:
   ```sql
   UPDATE Users SET password_hash = %s, reset_otp = NULL, otp_expiry = NULL WHERE email = %s
   ```

---

### UC29: Xác thực người dùng - Đăng xuất hệ thống
* **Actor:** Customer, Admin
* **Mô tả:** Người dùng đăng xuất để hủy bỏ phiên làm việc hiện tại trên thiết bị.
* **Đường dẫn file code:**
  - Client-side (Khách hàng): [front-end/js/dang_nhap.js](file:///e:/clone/web-ban-ve-xem-phim/front-end/js/dang_nhap.js) (Hàm `logout()`)
  - Admin-side (Quản trị viên): [front-end/js/quan_ly_tai_khoan.js](file:///e:/clone/web-ban-ve-xem-phim/front-end/js/quan_ly_tai_khoan.js) (Hàm `adminLogout()`)
* **Chi tiết logic xử lý:**
  - Vì hệ thống sử dụng cơ chế bảo mật Token JWT không lưu trạng thái ở Server (Stateless), Server không quản lý phiên lưu trữ đăng xuất. Chức năng đăng xuất được thực hiện hoàn toàn ở Client.
  - Khi người dùng bấm nút Đăng xuất, Client gọi hàm `logout()` (hoặc `adminLogout()`):
    1. Xóa bỏ tất cả thông tin đăng nhập và token đã lưu trữ trong trình duyệt bằng các lệnh:
       ```javascript
       localStorage.removeItem("currentUser");
       localStorage.removeItem("access_token");
       localStorage.removeItem("user_id");
       localStorage.removeItem("user_role");
       localStorage.removeItem("full_name");
       localStorage.removeItem("email");
       localStorage.removeItem("phone");
       ```
    2. Dọn sạch toàn bộ dữ liệu tạm thời của phiên làm việc bằng: `sessionStorage.clear()`.
    3. Gọi hàm `renderGuestAuth()` để cập nhật lại thanh điều hướng (header) về trạng thái cho khách vãng lai.
    4. Thực hiện điều hướng trang hoặc tải lại trang hiện tại bằng `window.location.reload()` hoặc `window.location.href = "../index.html"` để làm mới giao diện.

---

### UC19: Quản lý rạp và lịch chiếu - Thêm phòng chiếu mới
* **Actor:** Admin
* **Mô tả:** Admin thêm một phòng chiếu mới vào một cụm rạp xác định.
* **Đường dẫn file code:** [routers/quan_ly_phong.py](file:///e:/clone/web-ban-ve-xem-phim/routers/quan_ly_phong.py)
* **Chi tiết logic xử lý:**
  - **Phân quyền:** Sử dụng Dependency `current_admin: dict = Depends(get_current_admin)`. Hàm `get_current_admin` sẽ giải mã JWT token trong header, nếu role không thuộc `["S-admin", "C-admin"]` sẽ từ chối truy cập và báo lỗi HTTP 403.
  - **Endpoint xử lý:** `@router.post("")` ứng với hàm `create_room(cinema_id, room_name, room_type, capacity)` sử dụng tham số dạng `Form`.
  - **Quy trình thực hiện:**
    1. Kiểm tra sự tồn tại của cụm rạp: Truy vấn bảng `Cinemas` theo `cinema_id` để lấy tên rạp:
       ```sql
       SELECT name FROM Cinemas WHERE cinema_id = %s
       ```
       Nếu không tìm thấy, báo lỗi HTTP 404: `"Không tìm thấy cụm rạp yêu cầu."`.
    2. Kiểm tra trùng tên phòng chiếu: Để tránh trùng lặp dữ liệu, hệ thống kiểm tra xem trong cụm rạp này đã có phòng chiếu nào trùng tên chưa (các rạp khác nhau có thể cùng tên "Phòng 1", nhưng trong cùng một cụm rạp thì không được trùng):
       ```sql
       SELECT room_id FROM Rooms WHERE cinema_id = %s AND room_name = %s
       ```
       Nếu đã tồn tại phòng chiếu có tên này, báo lỗi HTTP 400: `"Lỗi: '<Tên phòng>' đã tồn tại trong rạp <Tên rạp>."`.
    3. Thêm phòng chiếu mới: Chèn thông tin phòng chiếu vào bảng `Rooms`:
       ```sql
       INSERT INTO Rooms (cinema_id, room_name, room_type, capacity)
       VALUES (%s, %s, %s, %s)
       ```
       Hàm `thuc_thi_lenh` sẽ thực thi câu lệnh SQL và trả về ID tự tăng (`room_id`) vừa được tạo.
    4. Trả về kết quả thành công chứa đầy đủ thông tin phòng chiếu mới.

---

### UC72: Tìm kiếm và khám phá - Tìm kiếm phim theo từ khóa
* **Actor:** Guest, Customer
* **Mô tả:** Tìm kiếm danh sách các bộ phim dựa trên từ khóa tìm kiếm theo tên phim, có hỗ trợ phân trang và lọc theo trạng thái.
* **Đường dẫn file code:** [routers/quan_ly_phim.py](file:///e:/clone/web-ban-ve-xem-phim/routers/quan_ly_phim.py)
* **Chi tiết logic xử lý:**
  - **Endpoint xử lý:** `@router.get("")` ứng với hàm `get_movies(page, limit, search, status)`
  - **Quy trình thực hiện:**
    1. Tính toán vị trí bắt đầu lấy dữ liệu để phân trang: `offset = (page - 1) * limit`.
    2. Xây dựng điều kiện lọc động dựa trên tham số đầu vào:
       - Nếu có tham số `search` (từ khóa tìm kiếm): Thêm điều kiện `m.title LIKE %s` và truyền giá trị tìm kiếm dạng `%<từ khóa>%`.
       - Nếu có tham số `status` (lọc trạng thái phim như Showing, Coming_Soon, Ended): Thêm điều kiện `m.status = %s`.
    3. Xây dựng câu lệnh SQL truy vấn chính sử dụng `LEFT JOIN` và hàm gộp nhóm `GROUP_CONCAT` để gom danh sách đạo diễn, diễn viên, nhà sản xuất thành chuỗi văn bản phân tách bằng dấu phẩy:
       ```sql
       SELECT m.*,
              COALESCE(GROUP_CONCAT(DISTINCT d.director_name SEPARATOR ', '), '') AS directors,
              COALESCE(GROUP_CONCAT(DISTINCT p.producer_name SEPARATOR ', '), '') AS producers,
              COALESCE(GROUP_CONCAT(DISTINCT a.actor_name SEPARATOR ', '), '') AS actors
       FROM Movies m
       LEFT JOIN movie_directors md ON m.movie_id = md.movie_id
       LEFT JOIN directors d ON md.director_id = d.director_id
       LEFT JOIN movie_producers mp ON m.movie_id = mp.movie_id
       LEFT JOIN producers p ON mp.producer_id = p.producer_id
       LEFT JOIN movie_actors ma ON m.movie_id = ma.movie_id
       LEFT JOIN actors a ON ma.actor_id = a.actor_id
       {WHERE_CLAUSE}
       GROUP BY m.movie_id
       ORDER BY m.created_at DESC
       LIMIT %s OFFSET %s
       ```
    4. Thực hiện đếm tổng số lượng bản ghi khớp điều kiện lọc để phục vụ phân trang:
       ```sql
       SELECT COUNT(*) AS total FROM Movies m {WHERE_CLAUSE}
       ```
    5. Tính toán tổng số trang: `total_pages = ceil(total / limit)`.
    6. Trả về kết quả thành công chứa danh sách phim kèm thông tin phân trang (`meta`).

---

## SPRINT 2

### UC52: Đặt vé trực tuyến - Xem tạm tính và giá vé
* **Actor:** Guest, Customer
* **Mô tả:** Khách hàng hoặc khách vãng lai khi chọn ghế trên sơ đồ phòng chiếu sẽ thấy mức giá chi tiết của từng ghế và tổng tiền tạm tính tương ứng.
* **Đường dẫn file code:**
  - Phía Backend: [routers/quan_ly_lich_chieu.py](file:///e:/clone/web-ban-ve-xem-phim/routers/quan_ly_lich_chieu.py) (Hàm `get_showtime_seats()`) và [utils/pricing.py](file:///e:/clone/web-ban-ve-xem-phim/utils/pricing.py)
  - Phía Frontend: Xử lý sự kiện click chọn ghế trong giao diện sơ đồ rạp.
* **Chi tiết logic xử lý:**
  - **Cơ chế tính giá vé linh hoạt (Phía Backend):**
    Khi quản trị viên lên lịch chiếu, hệ thống sẽ tính toán và lưu đơn giá cuối cùng của mỗi ghế thuộc suất chiếu đó vào bảng `Showtime_Seats` thông qua cơ chế tính toán trong `utils/pricing.py`:
    $$\text{Giá cuối cùng} = \text{Giá gốc phim} + \text{Phụ thu cụm rạp} + \text{Phụ thu định dạng chiếu} + \text{Điều chỉnh giá theo ngày} + \text{Phụ thu loại ghế}$$
    - *Giá gốc phim (Movie Base Price):* Lấy giá gốc được cấu hình cho phim hoạt động trong khoảng thời gian có ngày chiếu tương ứng.
    - *Phụ thu cụm rạp (Cinema Price Surcharges):* Lấy phụ thu theo từng rạp (ví dụ rạp trung tâm phụ thu cao hơn).
    - *Phụ thu định dạng chiếu (Projection Format Surcharges):* Phụ thu theo công nghệ chiếu (2D, 3D, IMAX).
    - *Điều chỉnh giá theo ngày (Daily Price Adjustments):* Điều chỉnh tăng giảm theo ngày lễ, cuối tuần, hoặc ngày đặc biệt.
    - *Phụ thu loại ghế (Seat Type Surcharges):* Phụ thu theo loại ghế (Standard, VIP, Sweetbox).
  - **Lấy sơ đồ ghế:** Endpoint `GET /api/rooms/{showtime_id}/seats` trả về thông tin sơ đồ ghế, trong đó mỗi ghế đã đi kèm giá trị cuối cùng (`price`).
  - **Tính tổng tiền tạm tính (Phía Frontend):**
    - Khi người dùng nhấn chọn các ghế trên màn hình sơ đồ rạp, Client sẽ đưa các `seat_id` đã chọn vào một danh sách tạm thời.
    - Frontend duyệt qua danh sách các ghế đã chọn, lấy giá tiền (`price`) của từng ghế và thực hiện cộng dồn để hiển thị "Tạm tính" tức thời trên giao diện cho người dùng thấy trước khi tiến hành đặt vé.

---

### UC73: Đặt vé trực tuyến - Xác nhận thông tin người dùng (Guest)
* **Actor:** Guest
* **Mô tả:** Khách vãng lai chưa có tài khoản phải cung cấp đầy đủ thông tin liên hệ (họ tên, số điện thoại, email) để xác nhận và đặt vé thành công.
* **Đường dẫn file code:** [routers/bookings.py](file:///e:/clone/web-ban-ve-xem-phim/routers/bookings.py) (Hàm `create_booking()`)
* **Chi tiết logic xử lý:**
  - **Pydantic Model nhận dữ liệu:**
    ```python
    class BookingRequest(BaseModel):
        showtime_id: int
        seat_ids: List[int]
        voucher_code: Optional[str] = None
        payment_method: str
        contact_name: str
        contact_phone: str
        contact_email: str
    ```
  - **Endpoint xử lý:** `@router.post("/create")` ứng với hàm `create_booking(payload: BookingRequest, request: Request)`
  - **Logic kiểm tra thông tin đối với Guest:**
    1. Hệ thống xác định trạng thái đăng nhập qua hàm `get_optional_user_id(request)`. Hàm này kiểm tra header `Authorization`. Nếu không chứa token hợp lệ, trả về `None` (xác định là Guest).
    2. Nếu `user_id` là `None` (Khách vãng lai):
       - Hệ thống thực hiện kiểm tra xem ba trường thông tin liên hệ là `contact_name`, `contact_phone`, và `contact_email` có được gửi lên đầy đủ hay không:
         ```python
         if not user_id:
             if not payload.contact_name or not payload.contact_phone or not payload.contact_email:
                 raise HTTPException(status_code=400, detail="Thiếu thông tin liên hệ khách vãng lai.")
         ```
       - Nếu thiếu bất kỳ trường nào trong ba trường này, hệ thống sẽ dừng tiến trình và trả về lỗi HTTP 400.
    3. Sau khi xác nhận thông tin đầy đủ, hệ thống tiến hành tạo đơn hàng và lưu các thông tin liên hệ khách vãng lai này trực tiếp vào các cột tương ứng (`contact_name`, `contact_phone`, `contact_email`) trong bảng `Bookings` để quản trị viên có thông tin liên hệ hỗ trợ hoặc gửi email thông tin vé.

---

## SPRINT 3

### UC65: Quản lý voucher - Xem chi tiết voucher offer
* **Actor:** Admin
* **Mô tả:** Admin xem thông tin chi tiết cấu hình điều kiện sử dụng của một mã voucher kèm theo các số liệu thống kê sử dụng thực tế.
* **Đường dẫn file code:** [routers/quan_ly_voucher.py](file:///e:/clone/web-ban-ve-xem-phim/routers/quan_ly_voucher.py)
* **Chi tiết logic xử lý:**
  - **Endpoint xử lý:** `@router.get("/{voucher_id}")` ứng với hàm `get_voucher_detail(voucher_id, current_admin)`
  - **Quy trình thực hiện:**
    1. Thực hiện câu lệnh SQL truy vấn lấy chi tiết voucher từ bảng `Vouchers` kết hợp `LEFT JOIN` với bảng hạng thành viên (`Membership_Tiers`), bảng người tạo (`Users`), và bảng phân phối voucher cho khách hàng (`User_Vouchers`):
       ```sql
       SELECT v.*,
              mt.tier_name AS required_tier_name,
              admin.full_name AS created_by_name,
              COUNT(DISTINCT uv.user_voucher_id) AS issued_count,
              SUM(CASE WHEN uv.status = 'Available' THEN 1 ELSE 0 END) AS available_count,
              SUM(CASE WHEN uv.status = 'Reserved' THEN 1 ELSE 0 END) AS reserved_count,
              SUM(CASE WHEN uv.status = 'Used' THEN 1 ELSE 0 END) AS used_count,
              SUM(CASE WHEN uv.status = 'Expired' THEN 1 ELSE 0 END) AS expired_count
       FROM Vouchers v
       LEFT JOIN Membership_Tiers mt ON mt.tier_id = v.required_tier_id
       LEFT JOIN Users admin ON admin.user_id = v.created_by
       LEFT JOIN User_Vouchers uv ON uv.voucher_id = v.voucher_id
       WHERE v.voucher_id = %s
       GROUP BY v.voucher_id, mt.tier_name, admin.full_name
       LIMIT 1
       ```
    2. Câu lệnh trên sử dụng các hàm gộp để tính toán ra:
       - `issued_count`: Tổng số lượng voucher đã được phát hành cho người dùng.
       - `available_count`: Số voucher đang khả dụng để dùng (`status = 'Available'`).
       - `reserved_count`: Số voucher đang bị giữ trong các phiên đặt vé chờ thanh toán (`status = 'Reserved'`).
       - `used_count`: Số voucher đã được sử dụng thanh toán thành công (`status = 'Used'`).
       - `expired_count`: Số voucher đã hết hạn sử dụng (`status = 'Expired'`).
    3. Nếu không tìm thấy voucher, trả lỗi HTTP 404: `"Không tìm thấy voucher."`.
    4. Trả về thông tin chi tiết voucher cùng các số liệu thống kê trên dưới dạng JSON.

---

### UC66: Quản lý voucher - Cập nhật điều kiện sử dụng voucher
* **Actor:** Admin
* **Mô tả:** Admin cập nhật lại các thông tin điều kiện áp dụng của voucher như loại giảm giá, giá trị đơn tối thiểu, thời gian hiệu lực, giới hạn sử dụng, hạng thành viên yêu cầu.
* **Đường dẫn file code:** [routers/quan_ly_voucher.py](file:///e:/clone/web-ban-ve-xem-phim/routers/quan_ly_voucher.py)
* **Chi tiết logic xử lý:**
  - **Pydantic Model nhận dữ liệu:** `VoucherUpdateRequest` (chứa đầy đủ các trường thông tin cấu hình điều kiện của voucher).
  - **Endpoint xử lý:** `@router.put("/{voucher_id}")` ứng với hàm `update_voucher(payload: VoucherUpdateRequest, voucher_id: int, current_admin)`
  - **Quy trình thực hiện:**
    1. Kiểm tra tính hợp lệ của dữ liệu đầu vào qua hàm `_validate_voucher_payload()`:
       - Loại giảm giá phải thuộc `["Percent", "Fixed_Amount"]`.
       - Nếu là loại phần trăm (`Percent`), giá trị giảm giá (`discount_value`) không được vượt quá `100%`.
       - Trạng thái voucher phải thuộc tập hợp hợp lệ `{"Active", "Expired", "Disabled"}`.
       - Nếu cho phép đổi bằng điểm tích lũy (`is_star_exchangeable = True`), chi phí điểm đổi (`star_cost`) phải lớn hơn `0`.
       - Ngày bắt đầu không được lớn hơn ngày kết thúc (`start_date <= end_date`), và thời gian bắt đầu đổi điểm không được lớn hơn thời gian kết thúc đổi điểm (`exchange_start_at <= exchange_end_at`).
    2. Kiểm tra voucher tồn tại trong hệ thống.
    3. Kiểm tra tính duy nhất của mã voucher (`code`): Đảm bảo mã voucher mới cập nhật không trùng với mã của các voucher khác đã có trong DB.
    4. Kiểm tra giới hạn số lượng phát hành: Nếu admin cấu hình giới hạn số lượng (`usage_limit`), giới hạn này không được nhỏ hơn số lượng voucher thực tế người dùng đã đổi (`exchanged_count`):
       ```python
       if payload.usage_limit is not None and payload.usage_limit < exchanged_count:
           raise HTTPException(...)
       ```
    5. Thực thi cập nhật dữ liệu: Cập nhật tất cả các điều kiện sử dụng mới vào bảng `Vouchers`.

---

### UC67: Quản lý voucher - Vô hiệu hóa voucher
* **Actor:** Admin
* **Mô tả:** Admin vô hiệu hóa mã voucher đang hoạt động để ngăn chặn người dùng sử dụng tiếp.
* **Đường dẫn file code:** [routers/quan_ly_voucher.py](file:///e:/clone/web-ban-ve-xem-phim/routers/quan_ly_voucher.py)
* **Chi tiết logic xử lý:**
  - **Pydantic Model nhận dữ liệu:**
    ```python
    class VoucherStatusRequest(BaseModel):
        status: str
    ```
  - **Endpoint xử lý:** `@router.patch("/{voucher_id}/status")` ứng với hàm `update_voucher_status(payload: VoucherStatusRequest, voucher_id, current_admin)`
  - **Quy trình thực hiện:**
    1. Kiểm tra tham số trạng thái yêu cầu gửi lên phải thuộc tập hợp `{"Active", "Expired", "Disabled"}`. Trong đó trạng thái `'Disabled'` đại diện cho việc vô hiệu hóa voucher.
    2. Xác nhận voucher tồn tại trong cơ sở dữ liệu.
    3. Thực hiện cập nhật cột `status` của voucher thành trạng thái mới:
       ```sql
       UPDATE Vouchers SET status = %s, updated_at = NOW() WHERE voucher_id = %s
       ```
    4. Khi voucher được cập nhật thành trạng thái `'Disabled'`, các luồng kiểm tra áp dụng voucher khi đặt vé sẽ tự động từ chối mã này.

---

### UC69: Đặt vé trực tuyến - Áp dụng voucher khi thanh toán
* **Actor:** Customer
* **Mô tả:** Khách hàng đã đăng nhập áp dụng voucher của mình sở hữu vào đơn đặt vé để được giảm giá tổng tiền thanh toán.
* **Đường dẫn file code:** [routers/bookings.py](file:///e:/clone/web-ban-ve-xem-phim/routers/bookings.py) (Hàm `create_booking()` và `validate_customer_voucher()`)
* **Chi tiết logic xử lý:**
  - Khi người dùng gửi yêu cầu đặt vé (`POST /api/bookings/create`) có truyền lên tham số `voucher_code`:
  - **Yêu cầu đăng nhập:** Hệ thống kiểm tra quyền hạn qua `get_optional_user_id()`. Chỉ khách hàng đã đăng nhập (Customer) mới có quyền sử dụng voucher. Nếu là Guest, hệ thống chặn ngay lập tức và trả về lỗi HTTP 401: `"Guest không được sử dụng voucher. Vui lòng đăng nhập."`.
  - **Hàm xác thực Voucher:** Gọi hàm trợ giúp `validate_customer_voucher(user_id, voucher_code, total_amount)` thực hiện xác thực thông tin qua SQL:
    ```sql
    SELECT uv.user_voucher_id, uv.status AS user_voucher_status,
           v.voucher_id, v.code, v.discount_type, v.discount_value, v.min_order_value,
           v.start_date, v.end_date, v.usage_limit, v.status AS voucher_status,
           required_tier.level_order AS required_level,
           user_tier.level_order AS user_level
    FROM User_Vouchers uv
    JOIN Vouchers v ON uv.voucher_id = v.voucher_id
    JOIN Users u ON uv.user_id = u.user_id
    LEFT JOIN Membership_Tiers user_tier ON u.tier_id = user_tier.tier_id
    LEFT JOIN Membership_Tiers required_tier ON v.required_tier_id = required_tier.tier_id
    WHERE v.code = %s AND uv.user_id = %s LIMIT 1
    ```
    Hệ thống sẽ thực hiện hàng loạt các kiểm tra nghiệp vụ:
    1. **Kiểm tra quyền sở hữu:** Người dùng phải sở hữu voucher này (tồn tại bản ghi liên kết trong bảng `User_Vouchers` ứng với `user_id` và mã voucher).
    2. **Kiểm tra trạng thái sở hữu:** Trạng thái voucher của cá nhân đó phải ở trạng thái khả dụng (`status = 'Available'`).
    3. **Kiểm tra trạng thái voucher:** Trạng thái chung của voucher trong hệ thống phải là đang hoạt động (`status = 'Active'`).
    4. **Kiểm tra thời gian hiệu lực:** Thời gian hiện tại phải nằm trong khoảng thời hạn sử dụng của voucher (`start_date <= NOW() <= end_date`).
    5. **Kiểm tra lượt sử dụng:** Tổng số lượt sử dụng còn lại của voucher phải lớn hơn 0 (`usage_limit > 0`).
    6. **Kiểm tra giá trị đơn tối thiểu:** Tổng số tiền vé tạm tính (`total_amount`) phải đạt giá trị tối thiểu quy định (`total_amount >= min_order_value`).
    7. **Kiểm tra cấp thành viên:** Cấp độ thành viên của người dùng phải đạt hoặc vượt quá cấp độ yêu cầu của voucher (`user_level >= required_level`).
  - **Khóa giữ voucher:** Nếu voucher hợp lệ, hệ thống cập nhật trạng thái voucher của người dùng thành `'Reserved'` (Đang giữ) và gắn mã đơn hàng sử dụng để tạm khóa voucher trong vòng 5 phút chờ thanh toán:
    ```sql
    UPDATE User_Vouchers SET status = 'Reserved', reserved_at = NOW(), booking_id_used = %s
    WHERE user_voucher_id = %s AND user_id = %s AND status = 'Available'
    ```

---

### UC53: Đặt vé trực tuyến - Cập nhật tổng tiền thanh toán sau khi áp dụng voucher
* **Actor:** Customer
* **Mô tả:** Hệ thống tính toán số tiền giảm giá và cập nhật lại số tiền phải thanh toán cuối cùng của đơn hàng sau khi áp dụng voucher thành công.
* **Đường dẫn file code:** [routers/bookings.py](file:///e:/clone/web-ban-ve-xem-phim/routers/bookings.py) (Hàm `check_customer_voucher()` và `create_booking()`)
* **Chi tiết logic xử lý:**
  - **Xem trước số tiền khi áp dụng voucher ở giao diện (Frontend preview):**
    - Client gửi yêu cầu dạng `GET /api/bookings/check-voucher?code=<Mã>&amount=<Tổng tiền tạm tính>`.
    - Backend xác thực mã voucher qua hàm `validate_customer_voucher()` và thực hiện tính toán số tiền giảm trừ:
      - Nếu loại giảm giá là phần trăm (`Percent`):
        $$\text{Số tiền giảm} = \text{Tổng tiền tạm tính} \times \frac{\text{Giá trị giảm}}{100}$$
      - Nếu loại giảm giá là số tiền cố định (`Fixed_Amount`):
        $$\text{Số tiền giảm} = \text{Giá trị giảm}$$
      - Hệ thống giới hạn số tiền giảm không vượt quá tổng số tiền đơn hàng:
        `discount_amount = min(discount_amount, total_amount)`
      - Số tiền thanh toán cuối cùng được tính:
        `final_amount = max(total_amount - discount_amount, 0)`
    - Trả về kết quả giảm giá cho Client cập nhật trực tiếp số tiền phải trả lên giao diện.
  - **Cập nhật dữ liệu thật khi tạo đơn hàng (Backend creation):**
    - Khi người dùng nhấn nút Xác nhận Đặt Vé (`POST /api/bookings/create`), backend thực hiện lại quy trình tính toán trên để đảm bảo tính an toàn dữ liệu, phòng tránh trường hợp người dùng can thiệp sửa giá ở Client.
    - Số tiền giảm giá (`discount_amount`) và số tiền thanh toán cuối cùng (`final_amount`) thực tế sẽ được chèn trực tiếp vào bản ghi đơn hàng trong bảng `Bookings`:
      ```sql
      INSERT INTO Bookings (user_id, showtime_id, contact_name, contact_phone, contact_email, voucher_id, user_voucher_id, total_amount, discount_amount, final_amount, status, payment_expires_at)
      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending', DATE_ADD(NOW(), INTERVAL 5 MINUTE))
      ```

---

## SPRINT 4

### UC45: Thông báo & Voucher - Thu hồi/Xóa thông báo đã gửi
* **Actor:** Admin
* **Mô tả:** Admin thực hiện thu hồi thông báo để ẩn khỏi giao diện người dùng ngay lập tức, hoặc xóa vĩnh viễn thông báo đã gửi khỏi hệ thống.
* **Đường dẫn file code:** [routers/tb_va_voucher.py](file:///e:/clone/web-ban-ve-xem-phim/routers/tb_va_voucher.py)
* **Chi tiết logic xử lý:**

#### Chức năng 1: Thu hồi thông báo (`PATCH /admin/notifications/{notification_id}/revoke`)
1. Backend kiểm tra thông báo tồn tại trong bảng `Notifications`.
2. Nếu thông báo đã có trạng thái `'Revoked'` trước đó, trả về thông báo hoàn thành.
3. Thực hiện cập nhật trạng thái thông báo thành `'Revoked'`, ghi nhận thời gian thu hồi và người thu hồi:
   ```sql
   UPDATE Notifications SET status = 'Revoked', revoked_at = NOW(), revoked_by = %s WHERE notification_id = %s
   ```
4. Để thông báo lập tức biến mất khỏi tất cả tài khoản khách hàng, hệ thống thực hiện câu lệnh xóa các bản ghi liên kết nhận tin nhắn trong bảng `User_Notifications`:
   ```sql
   DELETE FROM User_Notifications WHERE notification_id = %s
   ```
   *Lưu ý:* Việc xóa này giúp ẩn tin nhắn trên UI của khách hàng lập tức, nhưng bản ghi lịch sử thông báo gốc vẫn được giữ trong bảng `Notifications` của Admin với trạng thái `Revoked` để phục vụ công tác đối soát.

#### Chức năng 2: Xóa thông báo vĩnh viễn (`DELETE /admin/notifications/{notification_id}`)
1. Kiểm tra sự tồn tại của thông báo trong DB.
2. Kiểm tra tính an toàn: Chỉ cho phép xóa thông báo đã được thu hồi trước đó. Nếu trạng thái thông báo hiện tại vẫn là `'Sent'` (Đang hiển thị cho người dùng), hệ thống sẽ từ chối xóa và báo lỗi HTTP 400: `"Phải thu hồi thông báo trước khi xóa."`.
3. Xóa các bản liên kết nhận tin còn sót lại trong bảng `User_Notifications`.
4. Xóa vĩnh viễn bản ghi thông báo khỏi bảng `Notifications`:
   ```sql
   DELETE FROM Notifications WHERE notification_id = %s
   ```

---

### UC70: Thông báo và tiếp thị - Nhận thông báo phim mới/sự kiện
* **Actor:** Customer, Email/Notification Service
* **Mô tả:** Hệ thống tự động gửi thông báo về phim mới hoặc sự kiện tới hộp thư trong ứng dụng của khách hàng và gửi email thông báo ngầm qua dịch vụ email.
* **Đường dẫn file code:** [routers/tb_va_voucher.py](file:///e:/clone/web-ban-ve-xem-phim/routers/tb_va_voucher.py) (Hàm `send_general_notification()` và `get_my_notifications()`)
* **Chi tiết logic xử lý:**

#### Luồng gửi thông báo (Admin tác động)
1. Admin thực hiện gửi thông báo thông qua endpoint `POST /admin/general-notification` với phân loại nội dung là `'Marketing'` hoặc `'Event'`.
2. Xác định danh sách khách hàng mục tiêu nhận tin bằng hàm `get_target_users(target_type, target_tier_id)`:
   - Nếu `target_type` là `'All'`: Lấy danh sách toàn bộ người dùng có vai trò là `'Customer'` và trạng thái là `'Active'`.
   - Nếu `target_type` là `'TierAndAbove'`: Lấy danh sách các Customer đạt cấp độ thành viên lớn hơn hoặc bằng thứ hạng được chỉ định (`user_tier.level_order >= target_tier.level_order`).
3. Ghi nhận thông báo vào bảng `Notifications` với trạng thái mặc định là `'Sent'`.
4. Tạo liên kết hộp thư cá nhân cho từng khách hàng mục tiêu bằng hàm `create_recipients()`, chèn các bản ghi vào bảng `User_Notifications` với trạng thái chưa đọc:
   ```sql
   INSERT INTO User_Notifications (user_id, notification_id, is_read) VALUES (%s, %s, FALSE)
   ```
5. **Gửi Email ngầm không đồng bộ (Asynchronous Email Notification):**
   Nếu cấu hình gửi email (`send_email = True`), hệ thống sẽ duyệt qua danh sách khách hàng mục tiêu và sử dụng thư viện `BackgroundTasks` của FastAPI để gọi hàm `send_simple_email` chạy ngầm.
   - Hàm `send_simple_email` thiết lập kết nối SMTP với Google Mail Client (`smtp.gmail.com:587`), thực hiện đăng nhập bảo mật qua TLS và gửi email chứa nội dung thông báo.
   - Việc sử dụng `BackgroundTasks` giúp luồng phản hồi của API không bị nghẽn (vì gửi hàng trăm email qua SMTP thông thường mất rất nhiều thời gian), phản hồi API gửi thông báo được trả về cho Admin ngay lập tức trong khi email vẫn được tiếp tục gửi dưới nền.

#### Luồng nhận thông báo (Customer truy cập)
1. Khi khách hàng vào màn hình thông báo cá nhân, Client gửi yêu cầu tới endpoint `GET /api/notification-vouchers/me/notifications`.
2. Backend lấy ID người dùng từ JWT token đã giải mã (`user_id`).
3. Truy vấn danh sách các thông báo dành cho khách hàng từ bảng liên kết `User_Notifications` kết hợp bảng `Notifications` (chỉ hiển thị những thông báo có trạng thái gốc là `'Sent'`):
   ```sql
   SELECT un.id AS user_notification_id, un.is_read, un.read_at,
          n.notification_id, n.title, n.content, n.type, n.voucher_id, n.created_at
   FROM User_Notifications un
   JOIN Notifications n ON un.notification_id = n.notification_id
   WHERE un.user_id = %s AND n.status = 'Sent'
   ORDER BY n.created_at DESC
   ```
4. Trả về danh sách thông báo để hiển thị lên màn hình của khách hàng.
