# Backend dùng chung

Backend phục vụ thật chỉ chạy trên Raspberry Pi. Windows chạy frontend preview; venv Windows dành cho test/fixture loopback tạm. Xem [hướng dẫn chạy mới](../docs/setup/pi.md) và [kết quả audit](../docs/release/TEST_REPORT.md). Các API hội thoại cũ của APK được giữ nguyên.

Cấu hình đã thử bằng key thật, broker local và ThingSpeak: xem [báo cáo live](../docs/release/TEST_REPORT.md). Bí mật chỉ lưu ở cấu hình backend ignored, không nằm trong source được chia sẻ.

FastAPI duy nhất, SQLite duy nhất tại `data/communication.sqlite3`. Không tạo database ở frontend. Đang ưu tiên checkpoint Deafy MediaPipe + GRU 25 ký hiệu; xem `data/DEAFY_TRIAL.md`. Baseline cũ vẫn giữ tại `data/LANDMARK_TRIAL.md`. Thứ tự chọn model xem `data/MODEL_INTEGRATION.md`.

Trên Pi, từ gốc workspace:

```bash
bash start_deafy.sh
backend/.venv-pi/bin/python -m pytest backend/tests -q
```

`start_backend.bat` trên Windows chỉ kiểm tra backend Pi. Không khởi chạy thêm uvicorn Windows để phục vụ ứng dụng.

URL health: http://127.0.0.1:8001/api/health. Trang gốc chỉ báo dịch vụ; backend không còn phục vụ build frontend cũ.

Venv Windows mới được tạo riêng ở đây. Khi phục hồi trên máy khác, tạo venv Python 3.12, cài `requirements-deafy.txt` và `requirements-dev.txt` để dùng checkpoint Deafy. `requirements-windows.lock` ghi môi trường Windows hiện tại. Không chép venv Windows sang Pi.

Token và chính sách xóa tiếp tục dùng `DAKT_API_TOKEN` / `DAKT_ALLOW_DELETE`; mặc định chỉ bind loopback. CORS chấp nhận cả frontend dev 5173 và 5174 (localhost/127.0.0.1). Native Android phải cấu hình IP LAN/hostname trong Cài đặt, không dùng localhost điện thoại. HTTP LAN không mã hóa; cấu hình HTTPS trước khi dùng mạng không tin cậy.

Dữ liệu cũ đã được chuyển, có bản sao an toàn `.tools/split-backup/communication.sqlite3` và file backup không hoạt động còn ở thư mục cũ. Chỉ backend/data được dùng khi chạy. Dừng backend trước khi sao lưu SQLite để tránh bỏ sót WAL.
