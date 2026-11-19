# SignAssist trên iPhone — HTTPS nội bộ

Pi phục vụ giao diện Android dạng PWA và API/WebSocket cùng origin. Không cần IPA, Xcode hoặc backend AI thứ hai. iPhone và Pi phải cùng mạng `deafy`; không mở port ra Internet.

## Ghép nối một lần

1. Safari mở `http://deafy.local:8080/signassist-ca.cer` để tải **chứng chỉ công khai** của Pi. Đây chỉ là trang phân phối chứng chỉ, không phải ứng dụng.
2. Đối chiếu fingerprint SHA-256 của chứng chỉ với Pi trước khi tin cậy:

   `82418f07b1bc07cdd646d51a0c6ef4808b177b7b3c2a0a3724478b5646382eea`

   Có thể xác minh tại Terminal Pi: `openssl x509 -in .tools/pwa-https/data/caddy/pki/authorities/local/root.crt -noout -fingerprint -sha256` từ thư mục dự án. Fingerprint này chỉ áp dụng CA hiện tại; không tự chấp nhận nếu CA thay đổi.
3. Tự cài profile chứng chỉ trong Cài đặt → Cài đặt chung → VPN & Quản lý thiết bị. Sau đó bật tin cậy SSL cho đúng CA vừa đối chiếu trong Cài đặt chung → Giới thiệu → Cài đặt tin cậy chứng nhận. Xem [hướng dẫn Apple](https://support.apple.com/en-gb/102390). Không bỏ qua cảnh báo TLS nếu vẫn xuất hiện.
4. Mở `https://deafy.local:8443`, vào Cài đặt ứng dụng. Để trống địa chỉ backend để dùng cùng origin; nhập mã truy cập Pi hiện có nếu được yêu cầu. Không nhập Gemini/Groq/MQTT key vào điện thoại.
5. Safari → Chia sẻ → Thêm vào Màn hình chính.

Chứng chỉ CA tạo quyền tin cậy trên thiết bị: chỉ cài CA của Pi mình quản lý. Khi hết thử nghiệm, tắt tin cậy và xóa đúng profile đã cài trong VPN & Quản lý thiết bị. Không sao chép hoặc chia sẻ file khóa riêng trong `.tools/pwa-https/data`.

## Vị trí và thời tiết

- Trong Cài đặt ứng dụng, chủ động bấm lấy vị trí và cho phép Safari một lần; không theo dõi nền. Hoặc nhập vị trí tham chiếu thủ công.
- Giao diện hiển thị nguồn, thời điểm và sai số. Vị trí quá cũ/sai số trên 500 m không được sử dụng; cần cập nhật lại. Có thể tắt tái sử dụng hoặc xóa vị trí đã lưu.
- Gửi câu hỏi thời tiết qua backend Pi. Dữ liệu Open-Meteo, không suy đoán bằng LLM. Chỉ phát loa khi có kết quả hợp lệ và bật chức năng đọc; có thể phát lại.
- Google Places chưa có key: giao diện phải thông báo chưa cấu hình, không giả lập địa điểm. Không tự bật billing.
- Mất Pi: ứng dụng có thể giữ bản nháp nhưng không có inference, tìm kiếm hoặc điều khiển offline. Nút micro hiện dùng WebCamera của Pi.

## Vận hành

`start_deafy.sh` khởi động thêm dịch vụ HTTPS nếu đã cài; `stop_deafy.sh` dừng dịch vụ thuộc dự án. Chưa bật tự chạy khi boot.

```sh
systemctl --user status deafy-pwa.service signassist-connected.service
journalctl --user -u deafy-pwa.service -n 50 --no-pager
```

Khôi phục trước bản PWA khi cần: chạy `python3 .tools/pwa-location-weather-20261105-213525/rollback.py` trên Pi, từ thư mục dự án. Script dừng HTTPS và khôi phục source/cấu hình đã sao lưu; không ghi đè model hoặc hội thoại hiện tại.

## Xác minh ngày 05/11/2026

PASS: TLS có kiểm tra CA + hostname; HTTPS shell/manifest/icons/service worker; API thiếu token 401, token hợp lệ 200; WSS có xác thực nhận state và ping/pong; Model2 22 nhãn sẵn sàng, camera có frame, MQTT kết nối. Wi-Fi runtime power_save off và profile disable; chưa kết luận độ ổn định dài hạn.

PASS: 19 test vị trí/thời tiết; build frontend; Android debug build/lint (0 lỗi, 16 cảnh báo); kiểm tra 34 tài sản web trong APK, không có giá trị bí mật cấu hình. Kiểm thử UI dùng dữ liệu thử, không chứng minh GPS thật.

NOT VERIFIED: Safari/iPhone thật, quyền GPS thật, Home Screen/offline trên iOS, thời tiết theo vị trí người dùng và âm thanh ESP của lượt thời tiết, Google Places thật, cài APK trên Android thật. Giữ nguyên firmware, chân và nguồn ESP.

Log Windows: `.tools/pwa-live-verification.log`, `.tools/pwa-correction.log`, `.tools/pwa-tls-install.log`, `.tools/pwa-location-weather-tests.log`, `.tools/pwa-backend-final.log`, `.tools/pwa-android-build.log`, `.tools/pwa-apk-verification.json`.
