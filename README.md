# Phân Tích Chuyên Sâu: Giải Thuật A* và Minimax

Tài liệu này đi sâu vào chi tiết kỹ thuật, bản chất vấn đề giải quyết, cơ chế hoạt động chi tiết và các kỹ thuật tối ưu hóa nâng cao của hai thuật toán nền tảng trong Trí tuệ Nhân tạo: **A\* Search** và **Minimax Search**.

---

## PHẦN 1: THUẬT TOÁN A* (A-STAR SEARCH)

### 1. Vấn đề giải quyết (What problem does it solve?)
Trong khoa học máy tính và bản đồ học, bài toán tìm đường đi ngắn nhất từ điểm $A$ đến điểm $B$ là cực kỳ phổ biến.
- **Hạn chế của các thuật toán cổ điển**:
  - **Dijkstra**: Tìm kiếm mù quáng (Uninformed Search). Nó duyệt đều ra mọi hướng xung quanh như một làn sóng tròn lan tỏa. Dijkstra đảm bảo tìm ra đường đi ngắn nhất nhưng cực kỳ chậm và lãng phí tài nguyên tính toán vì duyệt qua cả những vùng ngược hướng với đích.
  - **Greedy Best-First Search**: Chỉ dựa vào Heuristic (ước lượng khoảng cách đến đích) để đi tiếp. Thuật toán này chạy rất nhanh nhưng dễ bị kẹt vào ngõ cụt (vật cản lớn hình chữ U) và không đảm bảo tìm được đường đi ngắn nhất.
- **Giải pháp của A\***: A\* ra đời để giải quyết bài toán tìm đường đi **ngắn nhất** một cách **nhanh nhất** bằng cách kết hợp ưu điểm của cả Dijkstra (độ tin cậy chi phí thực tế) và Greedy Best-First Search (định hướng thông minh bằng Heuristic).

### 2. Chi tiết Cơ chế Hoạt động của A*

#### 2.1. Bản chất hàm đánh giá $f(n) = g(n) + h(n)$
Mỗi nút $n$ trên đồ thị được gán một giá trị $f(n)$, đại diện cho tổng chi phí ước lượng của đường đi từ điểm đầu, đi qua nút $n$, để tới điểm đích:
1. **$g(n)$ (Thành phần Dijkstra)**: Chi phí thực tế tích lũy từ điểm xuất phát đến nút hiện tại $n$. Thành phần này giữ cho thuật toán luôn bám sát thực tế, tránh việc chọn những con đường đi vòng quá xa dù hướng đi có vẻ thẳng tới đích.
2. **$h(n)$ (Thành phần Heuristic)**: Ước lượng chi phí từ $n$ đến đích. Thành phần này đóng vai trò định hướng, giúp A\* tập trung duyệt các nút nằm trên trục đường hướng về phía đích.

#### 2.2. Điều kiện để A* tối ưu (Optimality)
Để A\* chắc chắn tìm được đường đi ngắn nhất, hàm Heuristic $h(n)$ phải thỏa mãn hai tính chất quan trọng:
- **Tính chấp nhận được (Admissibility)**: Hàm $h(n)$ không bao giờ được ước lượng cao hơn chi phí thực tế từ $n$ đến đích ($h(n) \le h^*(n)$). Nếu vi phạm, thuật toán có thể bỏ qua đường đi tối ưu thực sự vì nghĩ rằng nó quá dài.
- **Tính nhất quán (Consistency / Monotonicity)**: Với mọi nút $n$ và láng giềng $n'$ của nó, ước lượng khoảng cách không được thay đổi đột ngột: $h(n) \le c(n, n') + h(n')$ (trong đó $c(n, n')$ là chi phí đi từ $n$ đến $n'$). Tính chất này đảm bảo một khi một nút đã bị đóng (closed), đường đi tìm thấy tới nút đó chắc chắn là tối ưu nhất, giúp thuật toán không phải duyệt lại các nút cũ.

#### 2.3. Các loại Heuristic phổ biến
Tùy thuộc vào quy tắc di chuyển của hệ thống, ta chọn hàm Heuristic phù hợp:
- **Khoảng cách Manhattan**: Dùng khi chỉ được di chuyển 4 hướng (Lên, Xuống, Trái, Phải).
  $$h(n) = |x_1 - x_2| + |y_1 - y_2|$$
- **Khoảng cách Euclidean**: Dùng khi có thể di chuyển tự do theo mọi góc độ (đường chim bay).
  $$h(n) = \sqrt{(x_1 - x_2)^2 + (y_1 - y_2)^2}$$
- **Khoảng cách Diagonal / Chebyshev**: Dùng khi được di chuyển 8 hướng (kèm đi chéo với chi phí bằng đi thẳng).
  $$h(n) = \max(|x_1 - x_2|, |y_1 - y_2|)$$

---

## PHẦN 2: THUẬT TOÁN MINIMAX (MINIMAX SEARCH)

### 1. Vấn đề giải quyết (What problem does it solve?)
Minimax giải quyết bài toán ra quyết định và lập kế hoạch hành động trong môi trường đối kháng đầy cạnh tranh. Cụ thể là các trò chơi đáp ứng đủ 4 tiêu chí:
1. **Đối kháng hai người (Two-player)**: Có hai thực thể đối lập trực tiếp (thường gọi là MAX và MIN).
2. **Trò chơi có tổng bằng không (Zero-sum)**: Lợi ích của người này là thiệt hại của người kia. Không có kịch bản cả hai cùng thắng hay cùng thua (Ví dụ: Thắng = +1, Thua = -1, Tổng = 0).
3. **Thông tin hoàn hảo (Perfect Information)**: Không có yếu tố ngẫu nhiên (như gieo xúc xắc) hay ẩn giấu thông tin (như bài úp). Cả hai người chơi đều biết toàn bộ trạng thái hiện tại của bàn cờ (Ví dụ: Cờ vua, Cờ tướng, Tic-Tac-Toe, Reversi).
4. **Theo lượt (Turn-based)**: Các bên thay phiên nhau đi.

**Mục tiêu của Minimax**: Giúp người chơi MAX tìm ra nước đi tối ưu nhất, giả định rằng đối thủ MIN cũng là một người chơi cực kỳ thông minh và luôn đi những nước đi tốt nhất của họ để chống lại MAX.

### 2. Chi tiết Cơ chế Hoạt động của Minimax

#### 2.1. Cấu trúc cây Trò chơi (Game Tree)
Minimax biểu diễn toàn bộ các trạng thái có thể xảy ra của trò chơi dưới dạng một cây phân cấp:
- **Nút gốc (Root)**: Trạng thái hiện tại của bàn cờ cần quyết định nước đi tiếp theo.
- **Nút nhánh (Branch Nodes)**: Các nước đi giả định tiếp theo của MAX hoặc MIN.
- **Nút lá (Terminal Nodes)**: Các trạng thái kết thúc trò chơi (Thắng, Thua, Hòa) hoặc các trạng thái ở độ sâu giới hạn. Tại đây, ta sử dụng **Hàm đánh giá trạng thái (Evaluation Function)** để quy đổi thế cờ thành một điểm số cụ thể.

#### 2.2. Cơ chế lan truyền ngược (Backpropagation) điểm số
Thuật toán duyệt cây theo chiều sâu (DFS) xuống tận các nút lá, sau đó truyền điểm số ngược lên trên theo quy tắc:
- **Tại lượt của MAX**: Chọn nước đi có điểm số **lớn nhất** từ các nút con.
  $$\text{Value}(n) = \max_{s \in \text{Successors}(n)} \text{Value}(s)$$
- **Tại lượt của MIN**: Chọn nước đi có điểm số **nhỏ nhất** từ các nút con (vì MIN muốn dìm điểm của MAX xuống thấp nhất).
  $$\text{Value}(n) = \min_{s \in \text{Successors}(n)} \text{Value}(s)$$

#### 2.3. Tối ưu hóa thực tế với Độ sâu (`depth`)
Trong các trò chơi có cây quyết định lớn, việc chỉ tính kết quả Thắng/Thua ở cuối trận sẽ làm thuật toán trở nên thụ động. Việc cộng/trừ độ sâu vào điểm số giúp định hình hành vi cho AI:
- **Khi thắng**: Điểm số = $V_{win} - \text{depth}$. AI sẽ chọn nước đi chiến thắng ở độ sâu nhỏ nhất (thắng nhanh nhất có thể).
- **Khi thua**: Điểm số = $V_{lose} + \text{depth}$. AI sẽ chọn nước đi kéo dài game tối đa (thua muộn nhất có thể), tạo cơ hội cho đối phương mắc sai lầm.

---

## PHẦN 3: CÁC KỸ THUẬT TỐI ƯU HÓA NÂNG CAO

Cả hai thuật toán đều gặp phải vấn đề bùng nổ tổ hợp khi không gian trạng thái quá lớn. Dưới đây là các kỹ thuật thực tế được dùng để tối ưu hóa chúng:

### 1. Tối ưu hóa A*
- **A\* đa hướng (Bidirectional A\*)**: Tìm kiếm song song từ điểm xuất phát (tiến) và từ điểm đích (lùi) cho đến khi hai nhánh tìm kiếm gặp nhau ở giữa. Kỹ thuật này giúp giảm đáng kể số lượng nút phải duyệt.
- **Cắt giảm trùng lặp (Closed Set / Visited Set)**: Sử dụng bảng băm (Hash Set) để lưu lại các tọa độ đã duyệt, tránh việc duyệt lặp lại các nút trong các chu trình khép kín.
- **Nhảy điểm (Jump Point Search - JPS)**: Đối với lưới phẳng không trọng số, JPS loại bỏ các nút trung gian không cần thiết trên hành lang thẳng và chỉ đưa các "điểm nhảy" (điểm rẽ nhánh hoặc góc tường) vào hàng đợi ưu tiên, giúp tăng tốc độ tìm kiếm lên gấp nhiều lần.

### 2. Tối ưu hóa Minimax
- **Cắt tỉa Alpha-Beta (Alpha-Beta Pruning)**:
  Đây là kỹ thuật tối ưu hóa quan trọng nhất cho Minimax. Nó duy trì hai tham số trong quá trình duyệt cây:
  - $\alpha$: Điểm số tối thiểu mà người chơi MAX đã chắc chắn đạt được.
  - $\beta$: Điểm số tối đa mà người chơi MIN có thể khống chế.
  
  Nếu tại bất kỳ thời điểm nào trong quá trình duyệt nhánh, ta phát hiện thấy $\alpha \ge \beta$, điều đó có nghĩa là đối thủ thông minh sẽ không bao giờ cho phép thế cờ đi vào nhánh này $\Rightarrow$ Ta có thể **ngắt (cắt tỉa)** toàn bộ nhánh con còn lại mà không cần duyệt tiếp, giúp tiết kiệm tới 50% thời gian tính toán.

```
                    [MAX] (alpha=5, beta=10)
                   /     \
               [MIN]     [MIN] <--- Giả sử nhánh này trả về điểm 4 (nhỏ hơn alpha=5)
               /   \       |
              5     6     (Cắt tỉa nhánh con còn lại vì MAX sẽ không chọn nhánh này)
```

- **Bảng chuyển vị (Transposition Table)**: Sử dụng bảng băm để lưu lại điểm số của các thế cờ đã từng được tính toán trước đó (do các nước đi hoán vị dẫn đến cùng một thế cờ). Kỹ thuật này giúp tránh việc tính toán lại đệ quy nhiều lần cho cùng một trạng thái.
- **Giới hạn độ sâu phối hợp Hàm đánh giá (Heuristic Evaluation)**: Đối với các game siêu lớn như Cờ Vua, thuật toán không thể đi đến trạng thái cuối cùng (chiếu bí). Người ta giới hạn độ sâu (ví dụ: duyệt trước 8 lượt) rồi áp dụng hàm đánh giá thế trận tại thời điểm đó (tổng giá trị quân cờ, quyền kiểm soát trung tâm, độ an toàn của Vua) làm điểm số giả lập.
