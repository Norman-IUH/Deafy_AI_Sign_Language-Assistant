# Giọng Ngọc Huyền qua CIT Voice Studio

1. Kết nối Pi vào hotspot của laptop và mở CIT Voice Studio. Chọn **VieNeu-TTS-v3-Turbo (GPU)** và giữ ứng dụng mở.
2. Mở `START_DEAFY_DEMO.bat` trên Windows. Giữ cửa sổ mở và chờ dòng `PASS - Pi -> CIT` xác nhận Pi đã tạo được WAV. Nhập mật khẩu SSH của Pi trong Terminal nếu được hỏi. Tệp `.tools/cit-pi-known-hosts` chứa khóa máy chủ công khai của Pi đã xác minh. Nếu đổi Pi, xác minh lại dấu vân tay khóa trước khi cập nhật tệp.
3. Trên Pi, mở Cài đặt → Giọng nói, chọn **CIT Voice Studio – Ngọc Huyền**. Dùng nút nghe thử trước khi lưu. Chọn lại Aoede hoặc Kore để quay về Gemini.
4. Nếu laptop tắt hoặc bị sleep, Pi báo mất kết nối CIT. Mở lại CIT và chạy lại launcher, hoặc chọn Aoede/Kore trong Cài đặt. Khi chọn Ngọc Huyền, một lượt lỗi không tự đổi sang eSpeak.

Launcher thử tên `deafy.local` trước. Nếu không tìm được đúng khóa SSH theo tên, launcher dò cổng 22 trong subnet hotspot và đối chiếu khóa đã ghim. Nếu tunnel đứt, launcher tìm lại Pi và thử kết nối tối đa ba lần trong một lần chạy. Cổng 8001 của CIT ở loopback laptop, và Pi gọi qua cổng loopback 18001. Với cấu hình loopback của CIT v1.0.6, ứng dụng xem đây là yêu cầu cục bộ và không cần khóa API. Nếu cấu hình CIT yêu cầu khóa, đặt `DAKT_CIT_API_KEY` trong `backend/.env.local` trên Pi. Tùy chọn `DAKT_CIT_ENABLED=1` bật giọng CIT, và đổi về `0` rồi khởi động lại dịch vụ sẽ ẩn giọng này.

Pi nhận WAV mono 48 kHz PCM16, chuyển xuống 24 kHz rồi dùng đường phát ESP32 hiện có. `/stream` gửi header WAV sớm với độ dài chưa xác định. Đường phát hiện tại dùng WAV hoàn chỉnh để giữ kiểm tra dữ liệu, chống clipping và giảm tiếng bật/tắt đột ngột.

Trong thư mục dự án trên Pi, chạy `grep -a 'CIT timing' .tools/deafy-logs/system.log` để xem số đo. `first_ms` tính cả tạo giọng và thời gian đến những byte đầu trên Pi, `transfer_ms` tính thời gian đọc phần còn lại, `convert_ms` tính thời gian chuyển PCM. Trường `playing_ms` đo từ lúc backend bắt đầu xử lý câu đến khi Pi nhận MQTT PLAYING.

