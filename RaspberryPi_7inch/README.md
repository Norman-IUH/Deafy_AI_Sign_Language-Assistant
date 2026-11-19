# Giao diện Raspberry Pi 7 inch

Pi có hai chế độ **Điều khiển IoT** và **Hỏi AI**, giữ riêng bản nháp khi chuyển. Gemini mặc định chạy mock đến khi cấu hình key ở backend. Mở launcher Deafy AI hoặc chạy `bash start_deafy.sh` từ gốc dự án; xem [hướng dẫn chạy mới](../docs/setup/pi.md).

Vite/JavaScript thuần; source độc lập trong src/, giữ logic giao tiếp hiện có, ưu tiên camera bên trái, câu bên phải và phụ đề phía dưới. Chủ đề/font tiếng Việt kế thừa Sign Assist; nút giao tiếp cao ít nhất 48px ở hai kích thước mục tiêu.

Tại workspace chạy `start_pi_preview.bat` (tự bảo đảm backend đã chạy).

Trên PowerShell Windows, từ thư mục gốc dự án chạy `./start_pi_preview.bat`, rồi mở http://localhost:5173. Nút **Phóng to camera** giữ nguyên camera và đưa các điều khiển **AI / IoT**, nút camera, **Thu nhỏ**, thông tin nhận diện vào fullscreen. Chế độ AI có ô sửa câu, nút **GỬI câu hỏi**, kết quả và lỗi; dùng cùng state/API và bản nháp như màn hình thường. Dùng **Esc** hoặc **Thu nhỏ** để quay lại.

Kiểm thử hồi quy giao diện: `tools/qa/check-pi-fullscreen.cjs` xuất hàm nhận một Playwright `page`. Chỉ chạy trong browser context dùng riêng cho test vì bài test xóa bản nháp localStorage của context đó. Cần Vite ở 5173 và backend mock riêng ở 8002 (`DAKT_AI_PROVIDER=mock`, `DAKT_DB` trỏ database test, tắt MQTT/ThingSpeak). Bài test kiểm tra API gửi thật tới backend mock, chống gửi trùng, lỗi 503, đổi chế độ, giữ bản nháp, phục hồi DOM khi thoát và bố cục 800×480/1440×900. Phần cứng camera/relay không được giả nhận là đã kiểm chứng.

- App: http://localhost:5173
- Khung 1024×600: http://localhost:5173/preview.html?size=1024x600
- Khung 800×480: http://localhost:5173/preview.html?size=800x480

Khung preview nạp chính ứng dụng qua iframe, không dựng HTML giả. Giữ zoom 100%; trang bao có thể cuộn nếu cửa sổ nhỏ hơn khung, còn màn hình giao tiếp của app đã kiểm tra không cuộn ở các kích thước trên.

Chạy trực tiếp: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort`. Nếu thiếu dependency, chạy npm ci tại đây. API/WebSocket dùng proxy tới backend 8001; không có database hoặc mô hình riêng.

Nút toàn màn hình có trong app; `bash start_deafy.sh --kiosk` mở Chromium kiosk. Camera/inference và Zipformer STT chạy trên Pi; TTS Pi gửi WAV qua MQTT/HTTP cho ESP. Thiếu checkpoint/thiết bị thì báo lỗi thật. Launcher, camera và thu/dừng micro đã kiểm tra trên Pi; trạng thái broker và phản hồi ESP được hiển thị riêng. Xem [kết quả kiểm tra](../docs/release/TEST_REPORT.md).
