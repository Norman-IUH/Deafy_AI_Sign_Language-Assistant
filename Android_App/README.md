# Giao diện Android

Source Vite/React tại src/ và shared/ được đóng gói bằng Capacitor8. Project Android hiện tại là android/. Đã sync và build APK debug ngày 02/11/2026 theo yêu cầu mới; chưa build release hoặc thử điện thoại. Xem [hướng dẫn Android Studio](../docs/setup/android.md).

Tại workspace chạy `start_android_preview.bat` (tự bảo đảm backend đã chạy).

Đợt UX 01/11/2026: dùng mockup Sign Assist làm tham chiếu, palette xanh lá/xanh dương, card camera có thể thu gọn bằng nút cạnh “Camera Pi”, chat bubble, card lịch sử và nhóm cài đặt thống nhất. Camera hiển thị preview mặc định nhưng không tự bật camera máy chủ. Vùng nhập thích ứng visual viewport; khi bàn phím làm giảm chiều cao, tạm ẩn camera và điều hướng để ưu tiên soạn câu. Android safe area và bàn phím thật vẫn cần thử trên thiết bị.

Chỉ build web bằng `npm run build` để kiểm tra Vite; **chưa build APK**, không chạy `cap sync`, Gradle hoặc thay APK. Các kiểm thử trình duyệt ở `tools/qa/check-android-preview.cjs` nhận Playwright page trong context dùng riêng cho test, backend riêng ở 8002 và database test. TTS/STT được kiểm tra đường gọi bằng stub trong context test, không coi đó là đã phát loa hoặc thu micro thật. Xem `docs/UI_PREVIEW_REPORT.md` ở gốc dự án.

- App dạng điện thoại, kể cả cửa sổ desktop: http://localhost:5174
- Chọn 390×844, 360×800 hoặc 412×915: http://localhost:5174/preview.html

Khung kiểm tra tải app thật, không tạo mockup riêng. Giữ zoom 100%. Layout tập trung phụ đề, soạn câu và điều hướng dưới; camera máy chủ ở phía dưới. Cỡ chữ/theme vẫn có trong Cài đặt.

Chạy trực tiếp: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5174 --strictPort`. Thiếu dependency thì npm ci tại thư mục này. Backend dùng proxy chung 8001 ở web preview.

Capacitor giữ plugin native STT8.4.0/TTS8.0.2. Web preview dùng micro USB WebCamera qua backend Pi, có ô sửa và Xác nhận kết quả; không giả lập kết nối thành công. Native giữ micro/giọng trên điện thoại, chưa kiểm chứng quyền/giọng tiếng Việt thực tế. Nhập IP LAN/hostname Pi và token trong Cài đặt; không nhúng địa chỉ preview localhost hoặc Gemini/MQTT credential vào APK.

Android cho HTTP LAN/mixed content và tắt backup như trước; HTTP không mã hóa. Chưa tạo release, chưa cài lên thiết bị, chưa chạy firmware hoặc deploy.
