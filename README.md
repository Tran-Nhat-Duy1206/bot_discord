# Tài Liệu Giải Thích Chi Tiết Mã Nguồn & Logic Thuật Toán trong Thư Mục `3_file`

Tài liệu này cung cấp một cái nhìn sâu sắc, chi tiết từng bước, phân tích toán học, sơ đồ luồng hoạt động và quá trình chạy thực tế (dry-run) của 3 thuật toán tìm kiếm và tối ưu hóa trong thư mục [3_file](file:///e:/R%E1%BA%A3%20file/3_file):
1. **Tìm đường đi tối ưu A\* (A-star)** tại [astar_heuristic.py](file:///e:/R%E1%BA%A3%20file/3_file/astar_heuristic.py)
2. **Tìm kiếm tối ưu cục bộ Leo Đồi (Hill Climbing)** tại [hill_climbing.py](file:///e:/R%E1%BA%A3%20file/3_file/hill_climbing.py)
3. **Quyết định đối kháng Minimax với Độ Sâu (Minimax Search with Depth)** tại [minimax_depth.py](file:///e:/R%E1%BA%A3%20file/3_file/minimax_depth.py)

---

## 1. Giải Thuật A* với Heuristic (`astar_heuristic.py`)

### 1.1. Bản chất Toán học và Heuristic
Thuật toán A\* tìm kiếm đường đi ngắn nhất dựa trên việc kết hợp thông tin chi phí thực tế và ước lượng khoảng cách.
- **Công thức cốt lõi**:
  $$f(n) = g(n) + h(n)$$
  - $g(n)$: Chi phí thực tế tích lũy từ nút xuất phát $S$ tới nút hiện tại $n$. Trong bài toán này, mỗi bước đi sang ô lân cận có chi phí là $1$, nên $g(n) = g(\text{parent}) + 1$.
  - $h(n)$: Hàm Heuristic ước lượng khoảng cách từ $n$ đến đích $G$. Ở đây ta dùng **Khoảng cách Manhattan** (Manhattan Distance), phù hợp cho việc di chuyển 4 hướng trên ô lưới phẳng:
    $$h(n) = |x_n - x_{goal}| + |y_n - y_{goal}|$$
  - $f(n)$: Tổng chi phí dự đoán. A\* luôn ưu tiên duyệt nút có $f(n)$ nhỏ nhất.

- **Tính chất của Heuristic**: Khoảng cách Manhattan ở đây là một **Admissible Heuristic** (Heuristic chấp nhận được) vì nó không bao giờ đánh giá cao hơn chi phí thực tế tối thiểu cần thiết để tới đích (do không thể đi chéo và không có lối đi tắt). Điều này đảm bảo thuật toán luôn tìm ra đường đi tối ưu nhất.

### 1.2. Sơ đồ Hoạt động của A*
```mermaid
graph TD
    A([Bắt đầu]) --> B[Thêm Start vào open_list với f=0]
    B --> C{open_list trống?}
    C -- Đúng --> D([Kết thúc: Không tìm thấy đường])
    C -- Sai --> E[Lấy nút current có f nhỏ nhất ra khỏi open_list]
    E --> F{current == goal?}
    F -- Đúng --> G[Truy vết ngược qua parent để dựng đường đi]
    G --> H([Kết thúc: Trả về đường đi])
    F -- Sai --> I[Duyệt qua các lân cận nx, ny của current]
    I --> J{Hợp lệ? Trong lưới & Không phải vật cản}
    J -- Sai --> I
    J -- Đúng --> K[Tính new_cost = cost[current] + 1]
    K --> L{nx, ny chưa duyệt OR new_cost < cost[nx, ny]?}
    L -- Sai --> I
    L -- Đúng --> M["Cập nhật cost[nx, ny] = new_cost<br>Tính f = new_cost + h(nx, ny)<br>Thêm vào open_list<br>Ghi nhận parent[nx, ny] = current"]
    M --> I
```

### 1.3. Mô phỏng Từng Bước Chạy (Dry-run Trace)
Bản đồ lưới $3 \times 3$ được định nghĩa:
```
Hàng 0: [ 0, 0, 0 ]   (Start ở tọa độ 0,0)
Hàng 1: [ 1, 1, 0 ]   (Có vật cản tại 1,0 và 1,1)
Hàng 2: [ 0, 0, 0 ]   (Goal ở tọa độ 2,2)
```
- **Khởi tạo**:
  - `start = (0, 0)`, `goal = (2, 2)`
  - `open_list = [(0, (0, 0))]` (lưu cặp `(f_score, tọa_độ)`)
  - `cost = {(0, 0): 0}`

- **Vòng lặp 1**:
  - Pop `current = (0, 0)` khỏi `open_list` (có $f=0$).
  - Xét các lân cận:
    - `(1, 0)`: Vật cản $\rightarrow$ Bỏ qua.
    - `(0, 1)`: Hợp lệ. Chi phí thực tế $g = 0 + 1 = 1$. Khoảng cách Manhattan tới đích $h = |0 - 2| + |1 - 2| = 3$. Tổng $f = 1 + 3 = 4$.
      - Cập nhật: `cost[(0, 1)] = 1`, `parent[(0, 1)] = (0, 0)`.
      - Đẩy `(4, (0, 1))` vào `open_list`.

- **Vòng lặp 2**:
  - Pop `current = (0, 1)` (có $f=4$).
  - Xét các lân cận:
    - `(0, 0)`: Đã có chi phí nhỏ hơn ($0 < 2$) $\rightarrow$ Bỏ qua.
    - `(1, 1)`: Vật cản $\rightarrow$ Bỏ qua.
    - `(0, 2)`: Hợp lệ. Chi phí $g = 1 + 1 = 2$. $h = |0 - 2| + |2 - 2| = 2$. Tổng $f = 2 + 2 = 4$.
      - Cập nhật: `cost[(0, 2)] = 2`, `parent[(0, 2)] = (0, 1)`.
      - Đẩy `(4, (0, 2))` vào `open_list`.

- **Vòng lặp 3**:
  - Pop `current = (0, 2)` (có $f=4$).
  - Xét các lân cận:
    - `(1, 2)`: Hợp lệ (vì `grid[1][2]` là `0`). Chi phí $g = 2 + 1 = 3$. $h = |1 - 2| + |2 - 2| = 1$. Tổng $f = 3 + 1 = 4$.
      - Cập nhật: `cost[(1, 2)] = 3`, `parent[(1, 2)] = (0, 2)`.
      - Đẩy `(4, (1, 2))` vào `open_list`.

- **Vòng lặp 4**:
  - Pop `current = (1, 2)` (có $f=4$).
  - Xét các lân cận:
    - `(2, 2)` (Goal): Hợp lệ. Chi phí $g = 3 + 1 = 4$. $h = 0$. Tổng $f = 4 + 0 = 4$.
      - Cập nhật: `cost[(2, 2)] = 4`, `parent[(2, 2)] = (1, 2)`.
      - Đẩy `(4, (2, 2))` vào `open_list`.

- **Vòng lặp 5**:
  - Pop `current = (2, 2)`.
  - Phát hiện `current == goal` $\rightarrow$ Dừng vòng lặp.

- **Truy vết đường đi**:
  - Từ `(2, 2)` $\rightarrow$ `parent` là `(1, 2)` $\rightarrow$ `(0, 2)` $\rightarrow$ `(0, 1)` $\rightarrow$ `(0, 0)`.
  - Kết quả in ra: `Duong di: [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)]`.

---

## 2. Giải Thuật Leo Đồi (`hill_climbing.py`)

### 2.1. Bản chất Toán học và Không gian trạng thái
Thuật toán Leo đồi giải quyết bài toán tìm kiếm tối ưu hóa cục bộ (Local Search) không cần nhớ lại các trạng thái trước đó. Nó hoạt động tương tự như một người leo núi trong sương mù dày đặc: chỉ nhìn xung quanh và bước theo hướng dốc đi lên.
- **Hàm mục tiêu (Hàm đánh giá)**:
  $$f(x) = -(x - 3)^2 + 10$$
  - Đây là hàm parabol ngược. Đạo hàm bậc nhất: $f'(x) = -2(x - 3)$.
  - Phương trình cực trị: $f'(x) = 0 \Leftrightarrow x = 3$.
  - Đạo hàm bậc hai: $f''(x) = -2 < 0 \Rightarrow x = 3$ là điểm cực đại toàn cục.
  - Giá trị cực đại: $f(3) = 10$.

- **Hạn chế tổng quát của thuật toán**: Rất dễ bị kẹt ở **Cực trị cục bộ** (Local Maxima), **Cao nguyên** (Plateau) hoặc **Sống núi** (Ridge). Tuy nhiên, vì hàm mục tiêu ở đây chỉ có một đỉnh duy nhất (unimodal), giải thuật chắc chắn sẽ tìm ra nghiệm tối ưu toàn cục.

### 2.2. Minh họa Trạng thái Leo Đồi
```
   f(x)
    ^
10  |              * (Cực đại toàn cục tại x = 3)
    |            /   \
    |           /     \
    |          /       \
-54 |  * (Bắt đầu tại x = -5)
    +--------------------------> x
      -5  -4  -3 ... 2   3   4
```

### 2.3. Mô phỏng Từng Bước Chạy (Dry-run Trace)
- **Bắt đầu**: Khởi tạo $x = -5$. Tính $f(-5) = -(-5 - 3)^2 + 10 = -64 + 10 = -54$.
- **Bước 1**:
  - Tính lân cận trái: `trai = -6` $\Rightarrow f(-6) = -(-6 - 3)^2 + 10 = -81 + 10 = -71$.
  - Tính lân cận phải: `phai = -4` $\Rightarrow f(-4) = -(-4 - 3)^2 + 10 = -49 + 10 = -39$.
  - So sánh: $f(-4) = -39 > f(-5) = -54$. Cập nhật $x = -4$.
- **Các bước tiếp theo**:
  - Thuật toán tiếp tục dịch chuyển về phía bên phải vì đạo hàm dương: $x$ tăng dần từ $-4 \rightarrow -3 \rightarrow -2 \rightarrow -1 \rightarrow 0 \rightarrow 1 \rightarrow 2 \rightarrow 3$.
- **Bước cuối cùng (tại $x = 3$)**:
  - Hiện tại: $x = 3 \Rightarrow f(3) = 10$.
  - Lân cận trái: `trai = 2` $\Rightarrow f(2) = -(2 - 3)^2 + 10 = 9$.
  - Lân cận phải: `phai = 4` $\Rightarrow f(4) = -(4 - 3)^2 + 10 = 9$.
  - So sánh: Cả $f(2)$ và $f(4)$ đều nhỏ hơn $f(3)$ ($9 < 10$).
  - Thuật toán rơi vào nhánh `else` $\rightarrow$ `break` (thoát vòng lặp).
- **Kết quả**: In ra `x tot nhat: 3` và `gia tri: 10`.

---

## 3. Giải Thuật Minimax với Độ Sâu (`minimax_depth.py`)

### 3.1. Phân tích Thuật toán Đối kháng Minimax
Trong Tic-Tac-Toe (hoặc bất kỳ trò chơi đối kháng Zero-Sum nào khác), cây trò chơi chứa các trạng thái luân phiên giữa hai người chơi:
- **Lượt AI (`is_ai = True` / Maximize)**: AI giả lập tất cả các nước đi có thể và chọn nước đi mang lại điểm số cao nhất từ các nhánh con.
- **Lượt Người chơi (`is_ai = False` / Minimize)**: AI giả lập người chơi sẽ đi nước đi thông minh nhất để cản trở AI, tức là chọn nước đi có điểm số thấp nhất từ các nhánh con.

#### Tại sao cần kết hợp tham số Độ sâu (`depth`)?
Nếu Minimax thông thường chỉ trả về $10$ khi thắng, $-10$ khi thua, và $0$ khi hòa:
- AI sẽ không phân biệt được việc **Thắng ở ngay lượt kế tiếp (độ sâu ngắn)** với **Thắng sau 5 lượt nữa (độ sâu dài)**. Nó có thể đi những nước kéo dài game một cách không cần thiết.
- Tương tự, khi rơi vào thế bắt buộc phải thua, AI có thể bỏ cuộc ngay lập tức thay vì đi nước cờ kéo dài thời gian tối đa để hy vọng đối thủ mắc sai lầm.

**Công thức điểm số hiệu chỉnh theo `depth`**:
- **AI (quân "O") thắng**: $10 - \text{depth}$
  - Thắng ở độ sâu $0$ (thắng ngay lập tức): Điểm = $10$.
  - Thắng ở độ sâu $2$: Điểm = $8$.
  - AI sẽ luôn chọn điểm số lớn nhất, do đó nó ưu tiên thắng nhanh nhất.
- **Đối thủ (quân "X") thắng**: $\text{depth} - 10$
  - Thua ở độ sâu $1$: Điểm = $-9$.
  - Thua ở độ sâu $3$: Điểm = $-7$.
  - AI sẽ chọn điểm lớn nhất (tối thiểu hóa thiệt hại), do đó $-7 > -9$, nó sẽ ưu tiên chọn nước đi trì hoãn việc thua lâu nhất.

### 3.2. Sơ đồ Đệ quy Minimax
```
                  [Lượt của AI: Chọn Max]
                         /      \
                        /        \
           [Lượt Người: Min]      [Lượt Người: Min]
              /        \              /        \
          [Max]        [Max]      [Max]        [Max]
          /            /          /            /
       (Thắng: 9)   (Hòa: 0)   (Thua: -9)   (Thắng: 7)
```

### 3.3. Mô phỏng Chạy Thực Tế thế cờ kiểm thử
Thế cờ khởi tạo trong mã nguồn:
```
Chỉ số ô:       Bản đồ hiện tại:
0 | 1 | 2        X | O | X
---------        ---------
3 | 4 | 5          | O |  
---------        ---------
6 | 7 | 8          |   | X
```
Các ô trống còn lại là: `3`, `5`, `6`, `7`.
Đến lượt AI (quân `O`) thực hiện hàm `best_move(board)` (độ sâu ban đầu = $0$):

- **Xét trường hợp AI thử đi vào ô `7`**:
  - Bàn cờ tạm thời trở thành:
    ```
    X | O | X
      | O |  
      | O | X
    ```
  - Gọi đệ quy `minimax(board, is_ai=False, depth=0)`.
  - Bên trong `minimax` dòng 14: `result = check(board)`.
  - Hàm `check` duyệt qua cấu hình thắng `[1, 4, 7]`. Do `board[1] == board[4] == board[7] == "O"`, hàm trả về `"O"`.
  - Điều kiện dừng: `result == "O"` $\rightarrow$ trả về `10 - depth = 10 - 0 = 10`.
  - Điểm của ô `7` ghi nhận là `10`.

- **Xét trường hợp AI thử đi vào các ô khác (Ví dụ ô `3`)**:
  - Bàn cờ tạm thời trở thành:
    ```
    X | O | X
    O | O |  
      |   | X
    ```
  - Gọi đệ quy `minimax(board, is_ai=False, depth=0)`.
  - `check(board)` trả về `None` (chưa phân thắng bại).
  - Vì `is_ai` là `False`, chương trình mô phỏng lượt của đối thủ (Min). Đối thủ sẽ thử đi vào các ô trống còn lại: `5`, `6`, `7`.
    - Nếu đối thủ (Min) đi vào ô `7`: ngăn AI thắng và tự tạo thế cờ của mình.
    - Nhánh này sẽ được đệ quy tính toán và chắc chắn giá trị trả về sẽ nhỏ hơn `10` (vì đối thủ luôn chọn nước đi có điểm tối thiểu cho AI).

- **Kết luận**:
  - Điểm số thu được cho các ô: `7` có điểm lớn nhất là `10`.
  - AI chọn nước đi tốt nhất `move = 7`.
  - Kết quả in ra màn hình:
    ```
    AI di o: 7
    X O X
      O  
      O X
    ```

---

## 4. Bảng So Sánh và Đánh Giá Hiệu Năng

| Thuật toán | Loại bài toán | Độ phức tạp Thời gian (Time Complexity) | Độ phức tạp Không gian (Space Complexity) | Ưu điểm | Nhược điểm |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **A\* Search** | Tìm đường đi ngắn nhất | $O(b^d)$ (Tệ nhất), thường nhanh hơn rất nhiều nhờ Heuristic tốt. | $O(b^d)$ (Lưu trữ toàn bộ các nút trong `open_list` và `cost`). | Đảm bảo tìm ra đường đi ngắn nhất (Optimal) và hoàn chỉnh (Complete). | Tiêu tốn nhiều bộ nhớ đối với không gian tìm kiếm lớn. |
| **Hill Climbing** | Tối ưu hóa / Tìm cực trị | $O(\infty)$ (Phụ thuộc vào kích thước bước và hình dạng hàm số). | $O(1)$ (Chỉ lưu trạng thái hiện tại). | Cực kỳ nhanh, tốn ít bộ nhớ. | Dễ bị kẹt ở các cực trị cục bộ (Local Maxima). |
| **Minimax** | Quyết định đối kháng | $O(b^m)$ ($b$: hệ số nhánh trống, $m$: độ sâu tối đa của game). | $O(m)$ (Độ sâu ngăn xếp đệ quy). | Đưa ra nước đi hoàn hảo, không thể thua nếu đối thủ cũng chơi hoàn hảo. | Bùng nổ tổ hợp (với game lớn như Cờ Vua, Cờ Vây thì không thể duyệt hết cây nếu không có cắt tỉa Alpha-Beta). |
