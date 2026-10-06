# Xổ số & Vietlott Analytics Auto — GitHub

Đây là **gói dành riêng cho GitHub**. GitHub chịu trách nhiệm:

1. Tự lấy dữ liệu kết quả XSMN/Vietlott theo lịch.
2. Merge dữ liệu vào `data/history.json`.
3. Chạy phân tích + walk-forward backtest.
4. Sinh `data/dashboard.json`.
5. Tự deploy GitHub Pages.
6. Nếu cấu hình Hugging Face, tự đẩy **chỉ các file web cần thiết** sang Hugging Face Space.

## Cài đặt GitHub

### 1) Tạo repository
Tạo repository mới và upload **toàn bộ nội dung của thư mục này** vào nhánh `main`.

### 2) Bật GitHub Pages
Vào:

`Settings → Pages → Build and deployment → Source → GitHub Actions`

### 3) Cho phép workflow ghi dữ liệu
Nếu workflow không commit được, vào:

`Settings → Actions → General → Workflow permissions`

chọn **Read and write permissions**.

### 4) Chạy lần đầu
Vào:

`Actions → Auto Update Lottery Data → Run workflow`

Lần đầu pipeline bootstrap tối đa khoảng **730 ngày**. Các lần sau chỉ quét cửa sổ gần đây để bù dữ liệu thiếu.

## Lịch tự động

Workflow `Auto Update Lottery Data` chạy mỗi ngày theo `Asia/Ho_Chi_Minh`:

- 17:17 — cập nhật sau XSMN.
- 18:47 — cập nhật sau Vietlott.

Sau khi dữ liệu thay đổi, GitHub Actions tự commit `data/history.json` và `data/dashboard.json` về `main`.

## Tự đồng bộ sang Hugging Face

Sau khi đã tạo Hugging Face Static Space, trong GitHub vào:

`Settings → Secrets and variables → Actions`

Tạo:

- **Variable** `HF_SPACE_ID` = `TEN_TAI_KHOAN_HF/TEN_SPACE`
- **Secret** `HF_TOKEN` = access token Hugging Face có quyền ghi vào Space.

Workflow `Deploy Web` sẽ đóng gói đúng các file web tĩnh rồi upload sang Hugging Face. Bạn không cần copy dữ liệu thủ công mỗi ngày.

> File ZIP Hugging Face đi kèm là gói khởi tạo riêng để bạn upload Space lần đầu. Sau đó GitHub có thể tự đồng bộ tiếp.

## Logic XSMN

- Học riêng từng đài/tỉnh.
- Mô hình vị trí 6 chữ số có trọng số thời gian.
- Transition theo chữ số cùng vị trí từ kỳ trước.
- G1–G8 tạo thêm tín hiệu đuôi 2/3 số.
- Thư viện công thức biến đổi từ kỳ liền trước.
- Mọi công thức đều được đánh giá bằng **walk-forward backtest**: tại kỳ `t`, chỉ dùng dữ liệu `< t`.
- Có case audit Bình Thuận: `24/09/2026 ĐB 377346 → 24 + 7346 = 247346`, sau đó mới đối chiếu kỳ `01/10/2026`.

## Logic Vietlott

- Mega 6/45 và Power 6/55 tách riêng.
- Tần suất có trọng số thời gian và khoảng cách kỳ chưa xuất hiện.
- Phân tích cặp đồng xuất hiện, chẵn/lẻ, thấp/cao và tổng.
- Sinh bộ gợi ý bằng weighted sampling có seed cố định để cùng dữ liệu cho cùng kết quả.
- Có backtest để so với baseline ngẫu nhiên.

## Chạy local

```bash
pip install -r requirements-update.txt
python tests/smoke_test.py
python scripts/update_data.py
```

`update_data.py` cần Internet để lấy dữ liệu thật.

## Lưu ý thống kê

Điểm lịch sử/backtest không phải xác suất chắc chắn trúng. Nếu quá trình quay độc lập và công bằng, kết quả cũ không làm một tổ hợp cụ thể có xác suất toán học cao hơn ở kỳ kế tiếp.

## Nếu web hiện toàn dấu — / Cập nhật: —

Điều đó có nghĩa `data/dashboard.json` vẫn là bản khởi tạo (`generated_at: null`, `fetch.mode: not-run`).

Bản FIX AUTO DEPLOY này đã sửa luồng triển khai: `Deploy Web` nghe sự kiện `workflow_run` của `Auto Update Lottery Data`, nên sau khi cập nhật dữ liệu thành công nó sẽ tự deploy lại GitHub Pages và Hugging Face. Không phụ thuộc vào push do `GITHUB_TOKEN` tạo ra.

Khôi phục nhanh:

1. Actions → **Auto Update Lottery Data** → **Run workflow**.
2. Chờ workflow xanh hoàn toàn.
3. Mở `data/dashboard.json` và kiểm tra `generated_at` đã có thời gian, `fetch.mode` là `bootstrap` hoặc `incremental`.
4. Sau khi Auto Update hoàn tất, workflow **Deploy Web** sẽ tự chạy.
5. Chờ cả job `pages` và `huggingface` xanh rồi Ctrl+F5 trang web.

Nếu Auto Update đỏ, mở step **Update results and analytics** và xem lỗi; bản này sẽ cố ý fail thay vì deploy một dashboard rỗng nếu lần chạy đầu không lấy được bất kỳ dữ liệu nào.

## Engine XSMN Adaptive Walk-Forward V4

Phần XSMN không còn dùng một công thức cố định. Với mỗi đài, hệ thống lấy **kỳ liền trước của đúng đài** làm điểm xuất phát và tự đánh giá nhiều họ mô hình:

- tần suất từng vị trí chữ số với cửa sổ 12/24/52/104 kỳ;
- transition `chữ số kỳ trước -> chữ số kỳ sau` theo từng vị trí;
- delta `(kỳ sau - kỳ trước) mod 10` theo từng vị trí;
- blend của ba họ trên;
- engine đuôi 2 học delta từ ĐB/G1..G8 (các nhãn giải trong nguồn) của kỳ trước sang đuôi ĐB kỳ sau;
- thư viện công thức biến đổi có backtest và shrinkage để một lần trúng ngẫu nhiên không chiếm trọng số quá lớn.

### Cách tự chọn logic

1. Mỗi mô hình được walk-forward trên các kỳ quá khứ: ở kỳ `N`, nó chỉ được nhìn `< N`.
2. Chấm điểm bằng log-loss và hit-rate Top-1/Top-5/Top-10 so với baseline ngẫu nhiên.
3. Mẫu ít kỳ bị shrink để tránh overfit.
4. Chỉ các mô hình xếp hạng cao nhất được đưa vào ensemble và được gán trọng số tự động.
5. Một khối holdout cuối được khóa: việc chọn mô hình chỉ dùng dữ liệu **trước holdout**, rồi mới chấm trên holdout để kiểm tra lợi thế có thật hay không.
6. Khi có kết quả mới, toàn bộ quá trình trên chạy lại và trọng số có thể đổi.

Các phần trăm `P mô hình` trên giao diện là phân bố do mô hình lịch sử tạo ra, không phải xác suất vật lý/chắc chắn của kỳ quay. Nếu hệ thống quay độc lập và công bằng, xác suất lý thuyết của một số ĐB 6 chữ số cụ thể vẫn là `1/1.000.000`.
