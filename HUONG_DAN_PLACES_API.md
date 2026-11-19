# Vì sao AI chưa tìm/đọc được địa chỉ quán?

**Cấu hình hiện tại dùng OpenStreetMap/Overpass miễn phí. Google Places đang tắt; không cần thực hiện các bước billing bên dưới.** Xem [báo cáo và cách thử nguồn miễn phí](docs/OSM_PLACES_20261105.md). Nội dung Google dưới đây chỉ để tham chiếu.

Gemini/Groq xử lý ngôn ngữ; Google Places API (New) cung cấp tên và địa chỉ thực tế. Key Gemini không thay thế key Places. Hiện Pi chưa có GOOGLE_PLACES_API_KEY và chưa bật DAKT_PLACES_ENABLED, nên hệ thống báo NOT_CONFIGURED, không bịa quán hoặc đọc địa chỉ giả.

## 1. Quyết định về billing trước

Theo [Google Places: usage and billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing/), dự án dùng Places phải bật billing. Có hạn mức miễn phí tùy SKU nhưng không đồng nghĩa không cần billing hoặc luôn miễn phí. **Nếu bạn chưa muốn liên kết thanh toán, dừng bước cấu hình tại đây.** Camera, GRU, AI ngôn ngữ và phát câu giao tiếp vẫn dùng được. Codex chưa bật billing hoặc tạo tài khoản thanh toán cho bạn.

Ngân sách cảnh báo không phải giới hạn cứng ngăn mọi khoản phí; nếu quyết định dùng, kiểm tra quota của dịch vụ và giới hạn theo nhu cầu demo, theo dõi usage/billing trong Google Cloud. Không tự bấm chấp nhận nâng cấp trả phí chỉ để thử sửa lỗi tìm kiếm.

## 2. Tạo key nếu bạn đồng ý dùng dịch vụ

1. Mở [Google Cloud Console](https://console.cloud.google.com/), đăng nhập tài khoản của bạn.
2. Chọn/tạo project cho Sign Assist. Google có thể yêu cầu cấu hình billing; chỉ tiếp tục khi bạn đồng ý các điều kiện hiển thị.
3. APIs & Services → Library → tìm đúng **Places API (New)** → Enable. Không cần bật Maps JavaScript/Routes cho luồng tìm tên và địa chỉ hiện tại.
4. APIs & Services → Credentials → Create credentials → API key.
5. Edit key → API restrictions → Restrict key → chỉ chọn Places API (New). Không đặt HTTP referrer/Android restriction cho key dùng từ backend Pi. Nếu dùng IP restriction, đó phải là IP ra Internet hợp lệ, không phải IP hotspot 192.168.137.x.
6. Lưu key trong trình quản lý mật khẩu/cấu hình backend. **Không gửi key vào chat, không đưa vào frontend, APK, ESP, Git hoặc ảnh chụp.**

[Hướng dẫn chính thức tạo và giới hạn key](https://developers.google.com/maps/documentation/places/web-service/get-api-key).

## 3. Nhập trực tiếp trên Pi

Mở Terminal trong RealVNC. Thư mục cài hiện tại là `/home/pipi/Desktop/Test`. Không dùng lệnh có key thật vì dễ lưu vào shell history.

```bash
cd /home/pipi/Desktop/Test
umask 077
cp -n backend/.env.local ".tools/env-before-places-$(date +%Y%m%d-%H%M%S)"
nano backend/.env.local
```

Giữ nguyên mọi dòng cấu hình cũ, đặc biệt token/MQTT/Gemini/Groq/model. Thêm hoặc chỉnh đúng hai biến sau trong nano:

```dotenv
DAKT_PLACES_ENABLED=1
GOOGLE_PLACES_API_KEY="DAN_KEY_PLACES_THAT_TAI_DAY"
```

Đây là placeholder, không phải key hoạt động. Dán key thật trong Terminal Pi, không trong chat. Ctrl+O → Enter để lưu; Ctrl+X để thoát. Nếu chưa tạo key thật, không bật biến enabled để giả lập đã cấu hình.

```bash
chmod 600 backend/.env.local
systemctl --user restart signassist-connected.service
bash start_deafy.sh --no-ui
```

Lệnh restart cần thiết để nạp cấu hình mới và sẽ tạm ngắt camera/backend; không restart broker, đổi Wi-Fi hoặc nạp firmware. Nếu chưa muốn làm Terminal, sau khi tạo key hãy nhắn Codex “tui đã tạo key, hướng dẫn nhập trên Pi”, không gửi giá trị key.

## 4. Chọn vị trí và thử

Mở Trợ lý AI → chọn **Tìm địa điểm**, nhập tọa độ vĩ độ/kinh độ của vị trí bạn muốn tìm gần đó. Có thể lấy tọa độ bằng cách chọn đúng địa điểm trên Google Maps và sao chép hai số hiển thị. Không dùng IP hotspot làm vị trí.

Nút **Dùng vị trí thiết bị** phụ thuộc quyền vị trí và môi trường HTTPS/localhost; Pi không tự có GPS. Nếu bị từ chối, nhập tọa độ thủ công. Chỉ nhập tên trường/địa chỉ hiện chưa đủ để xếp gần: backend hiện yêu cầu tọa độ hợp lệ, không tự geocode tên đó.

Nhập `Tìm quán cơm gần đây`, giữ tác vụ **Gửi · tự phân loại** hoặc **Tìm địa điểm**, bấm Gửi. Chế độ **Chỉ ghép câu, không tìm kiếm** được giữ đúng ý nghĩa: chỉ sửa trình bày câu.

Kết quả hợp lệ tối đa 3 tên + địa chỉ từ Google Places trong phạm vi kiểm tra5km; không khẳng định là3quán gần nhất tuyệt đối. Khi bật giọng nói, backend tự phát một lần qua ESP. Nút Đọc lại gửi một request mới; WebSocket reconnect không tự phát lại. Chưa có kết quả thật thì nút đọc bị khóa và có lời giải thích.

## 5. Đọc lỗi

| Trạng thái | Cách xử lý |
|---|---|
| NOT_CONFIGURED | Chưa có key hoặc chưa bật Places tại backend; không phải lỗi model/loa |
| Cần vị trí | Nhập đủ tọa độ hợp lệ; không suy GPS từ Wi-Fi/IP |
| HTTP_401 | Kiểm tra key đúng dịch vụ, nhập trên backend |
| HTTP_403 | Kiểm tra Places API New đã enable, quyền/key restriction và billing; chưa chắc chỉ do key sai |
| HTTP_429 | Kiểm tra quota/usage và chờ, không tự tăng hạn mức trả phí |
| Không có kết quả | Nguồn không trả địa điểm đủ tên/địa chỉ/vị trí hợp lệ; không thêm quán giả |
| Tìm thấy nhưng chưa có tiếng | Xem riêng lỗi TTS/MQTT/ESP, trạng thái giọng nói trong Cài đặt và ACK/PLAYING/DONE |

Key lưu ở Pi; ứng dụng Android chỉ gửi yêu cầu tới backend. Không dùng Gemini/Groq để tự viết tên quán/địa chỉ thay nguồn Places.

## Cập nhật cấu hình ngày 05/11/2026

Key người dùng cung cấp đã được lưu riêng trên Pi trong `backend/.env.local`, quyền 600; cấu hình trước đó sao lưu tại `.tools/places-setup-20261105-230303/env.before`, thư mục riêng quyền 700. Không đưa key vào tài liệu, frontend/PWA hoặc APK.

Hiện `DAKT_PLACES_ENABLED=0` để chờ người dùng xác nhận một lượt kiểm thử có thể tính phí; chưa gọi Places thật và chưa xác minh key, API enable, billing hoặc restriction. Không bật billing tự động. Vì vậy NOT_CONFIGURED vẫn là trạng thái có chủ đích đến khi được phép kích hoạt. Không dùng test mock làm bằng chứng key hoạt động.

Backend hiện phân biệt error_code: NOT_CONFIGURED, LOCATION_REQUIRED, PERMISSION_DENIED, QUOTA_EXCEEDED, TIMEOUT, ZERO_RESULTS; giữ status cũ để không phá frontend. HTTP lỗi còn có http_status, không chứa nội dung phản hồi bí mật của Google. Field mask chỉ gồm displayName, formattedAddress và location; tối đa 3 kết quả, lọc trong 5 km rồi xếp theo khoảng cách.

Không cần nhập lại vị trí nếu GPS hoặc vị trí tham chiếu còn hợp lệ và cho phép tái sử dụng. Trong Cài đặt hiện đã có **Tìm khu vực theo tên** (Open-Meteo/GeoNames) rồi người dùng xác nhận lưu; không suy vị trí từ tên Wi-Fi.

Kiểm thử: backend Windows 160 passed, 1 skipped; nhóm Places/location/weather tại Pi 59 passed. Model2/camera/MQTT sẵn sàng sau cập nhật. Chưa gọi Places thật, chưa xác minh loa đọc địa chỉ quán thật. Thời tiết đã được kiểm tra riêng ở lượt trước, người dùng xác nhận nghe loa.
