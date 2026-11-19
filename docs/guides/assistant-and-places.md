# Vì sao AI chưa tìm/đọc được địa chỉ quán?

**Cấu hình hiện tại dùng OpenStreetMap/Overpass miễn phí. Google Places đang tắt; không cần thực hiện các bước billing bên dưới.** Xem [báo cáo và cách thử nguồn miễn phí](../release/TEST_REPORT.md). Nội dung Google dưới đây chỉ để tham chiếu.

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


## Vận hành Trợ lý AI


Phiên bản 03/11/2026: Raspberry Pi là backend duy nhất; Windows chỉ chạy frontend preview. ESP32 chỉ phát loa, không điều khiển đèn/quạt.

## Mở ứng dụng

Trên Pi: nhấn launcher **Deafy AI**, hoặc chạy trong thư mục dự án:

```bash
bash ./start_deafy.sh
```

Giao diện Pi: `http://localhost:5173`. Backend: cổng 8001. Launcher hiện có được giữ nguyên; không chạy thêm backend nếu service đã hoạt động.

Trên Windows, mở hai Terminal PowerShell tại DAKT-Nc:

```powershell
npm --prefix RaspberryPi_7inch run dev -- --port 5173 --strictPort
```

```powershell
npm --prefix Android_App run dev -- --port 5174 --strictPort
```

Pi preview trên Windows: `http://localhost:5173`. Android preview: `http://localhost:5174`. Cả hai dùng proxy/discovery hiện có để tìm backend Pi đã ghép nối. Không chạy FastAPI/Gemini trên Windows. Android APK chưa được build lại.

Nếu mất kết nối, kiểm tra Pi/hotspot và mục Kết nối Raspberry Pi. Giữ cơ chế discovery hiện có; không thay IP hoặc nạp lại ESP chỉ để thử UI. Giao diện mới yêu cầu backend `assistant_version=1`; nếu backend cũ, các nút gửi/phát bị khóa để tránh hành vi tự phát loa của phiên bản trước.

## Ghép câu và phát loa

1. Nhập câu, làm ký hiệu rồi chọn lại trong **Sửa ký hiệu**, hoặc dùng micro.
2. Với micro: bấm **Bắt đầu nghe**, nói, chờ Pi nhận dạng; sửa chữ nếu cần, rồi bấm **Dùng làm câu của bạn**. Nút này chỉ đưa text vào bản nháp, không gửi AI/phát loa.
3. Mở **Trợ lý AI**, chọn **Chỉ ghép câu, không tìm kiếm**, rồi bấm **Ghép câu** ở thanh dưới.
4. So sánh **Câu gốc** và **Câu AI đề xuất**. Chọn **Dùng câu gợi ý** nếu đúng ý, hoặc **Chỉnh sửa câu**.
5. Bấm nút loa/Phát để Pi tạo TTS và ESP phát tiếng.

Ghép câu chỉ được gửi theo thao tác người dùng. Câu gợi ý không tự ghi đè bản nháp hoặc tự phát. Bộ kiểm tra giữ từ, thứ tự nội dung, số và phủ định; gợi ý thay đổi nội dung bị từ chối. Kiểm tra này bảo thủ, không bảo đảm hiểu nghĩa hoàn hảo: người dùng vẫn phải xác nhận. Nếu Gemini lỗi, câu gốc vẫn có thể chỉnh/phát bằng TTS local.

**Hỏi trợ lý AI** vẫn trả lời câu hỏi thông thường. Bấm **Đọc kết quả qua ESP32** nếu muốn nghe; không tự đọc khi nhận phản hồi.

## Sửa nhận diện

- Mở **Sửa ký hiệu**. Khi có output GRU hợp lệ, tối đa 3 lựa chọn lấy từ softmax thật được hiển thị kèm điểm. Điểm này chưa được hiệu chuẩn thành độ chính xác.
- Nếu không có dữ liệu xếp hạng, giao diện ghi rõ **Chọn thủ công từ bộ nhãn**, không giả Top 3.
- Chọn từ đúng để thêm vào bản nháp. Một sự kiện không được thêm lặp do retry.
- Muốn sửa từ vừa chọn: chọn **Thay ký hiệu cuối đã chọn**, rồi chạm từ đúng; hoặc bấm **Xóa ký hiệu cuối đã chọn**.
- Sau khi đã sửa trực tiếp cả câu, hãy tiếp tục sửa bằng ô văn bản; thao tác thay/xóa ký hiệu cuối bị khóa nếu revision không còn khớp.
- Nút X trong ô soạn xóa bản nháp qua backend, có đồng bộ. Không gửi AI, phát loa hoặc điều khiển thiết bị.

Phụ đề chỉ dùng sự kiện đã xác nhận và tự ẩn sau 10 giây không có sự kiện mới; không xóa bản nháp hoặc dừng camera. Nhãn được chọn sửa được lưu trong bảng SQLite `recognition_corrections`; không lưu ảnh hoặc tự training online.

## Tìm địa điểm

Mặc định nút **Gửi · tự phân loại yêu cầu**: các câu như “TÌM QUÁN CƠM GẦN ĐÂY” được backend đưa vào tìm địa điểm; câu hỏi thông thường đi vào Hỏi AI, còn câu giao tiếp đi vào ghép câu. Không gọi AI theo từng frame. Bạn vẫn có thể chọn tác vụ cụ thể nếu phân loại chưa đúng. Chủ động chọn **Chỉ ghép câu, không tìm kiếm** thì câu “Tìm…” vẫn chỉ được viết lại, không tự đọc/tìm Places.

Khi Gửi tự phân loại phát hiện tìm địa điểm mà thiếu vị trí, mở Trợ lý AI để nhập vị trí/tọa độ rồi gửi lại. Có thể chọn **Tìm địa điểm** trước để thấy ô vị trí ngay. Không có key thì ứng dụng báo **NOT CONFIGURED**, không trả quán giả.

Trên Pi fullscreen, panel Trợ lý AI là drawer bên phải rộng tối đa 440px; camera giữ nguyên kích thước. Cuộn bằng chuột/vuốt cảm ứng hoặc dùng nút **↑ / ↓**; nút **Đóng** thu drawer. Có thể dùng Tab vào nội dung rồi PageDown/PageUp. Thao tác vuốt đã kiểm thử bằng cảm ứng Chromium mô phỏng, chưa thay thế kiểm chứng màn hình vật lý Pi.

1. Nhập hoặc ghép **Tìm Ăn cơm**.
2. Mở **Trợ lý AI**, chọn **Tìm địa điểm**.
3. Nhập tên trường/địa chỉ tham chiếu, hoặc nhập tọa độ; thiết bị hỗ trợ có thể bấm **Dùng vị trí thiết bị** và tự cấp quyền.
4. Bấm **Tìm kiếm**. Không suy ra GPS từ IP/hotspot.

Hiện Places chưa bật và chưa có key: ứng dụng thông báo rõ, không tạo danh sách quán. Bấm **Tìm trên Google Maps** để tìm trực tiếp. Không gọi Places/Gemini cho phần fallback này.

Tích hợp Places đã có ở backend, nhưng chỉ hoạt động khi người dùng chủ động cấu hình cả `GOOGLE_PLACES_API_KEY` và `DAKT_PLACES_ENABLED=1` trong môi trường backend Pi. Không đưa key vào frontend/APK. Không tự bật billing hoặc thêm key trong lượt triển khai này. Nếu sau này muốn bật, cần kiểm tra quyền API, hạn mức và chi phí trên tài khoản Google Maps Platform trước.

Khi Places được cấu hình: Text Search (New) trả tối đa 3 kết quả có tọa độ hợp lệ trong phạm vi 5 km. Backend loại trùng và sắp xếp theo khoảng cách đường chim bay, nhưng không khẳng định đây là 3 nơi gần nhất tuyệt đối. Giao diện chỉ hiện tên và địa chỉ, nguồn và thời điểm tìm; không có bản đồ/chỉ đường/khoảng cách trên thẻ kết quả.

Yêu cầu phổ biến (quán cơm, quán cà phê, nhà thuốc, bệnh viện, ATM) được phân loại tại Pi. Yêu cầu khác có thể dùng Gemini → Groq để chuyển thành loại địa điểm, chỉ khi đã cấu hình Places và có tọa độ. AI không cung cấp tên/địa chỉ quán. Thời gian chờ tìm kiếm tối đa 45 giây; hỏi AI/ghép câu tối đa 35 giây.

Khi bạn bấm **Tìm kiếm**, kết quả thật được backend tự đọc đúng một lượt qua ESP32 nếu mục **Cho phép đọc văn bản thành tiếng** đang bật. Tắt mục này thì chỉ hiển thị chữ. Các giao diện nhận WebSocket không tự phát loa. Không có kết quả thật thì không phát danh sách. MQTT/TTS lỗi vẫn giữ kết quả và bản nháp; không tự thử phát lại.

Bấm **Đọc lại danh sách** hoặc **Đọc địa điểm 1/2/3** để chủ động nghe lại. Nút bị khóa lúc đang xử lý/phát. Không tự đọc câu AI ghép hoặc câu trả lời thông thường.

Muốn tìm lại: chỉnh câu/vị trí nếu cần rồi bấm **Tìm kiếm**. Vị trí phải được bạn chọn/cấp quyền; Pi không suy ra GPS từ hotspot. Thiếu cấu hình hiện **NOT CONFIGURED**, lỗi mạng hoặc không có kết quả đều thông báo riêng. Liên kết Maps ngoài ứng dụng chỉ là phương án tra cứu thủ công khi chưa có danh sách, không đọc dữ liệu từ trang Maps.

Tài liệu API: https://developers.google.com/maps/documentation/places/web-service/text-search

## Ba kịch bản demo

1. **Giao tiếp có xác nhận:** dùng ký hiệu hiện có “Xin chào” (hoặc chọn từ vocabulary), ghép câu, kiểm tra gợi ý, dùng câu và phát loa. Các từ chưa được train như “tôi muốn uống nước” cần nhập/micro, không tuyên bố GRU nhận được.
2. **Trợ lý tìm kiếm (phút 1–2):** dùng “Tìm” + “Ăn cơm” (đã có trong vocabulary), hoặc nhập/micro; chọn vị trí thật. Nếu đã cấu hình Places, tìm tên/địa chỉ, nghe tự đọc một lượt và thử Đọc địa điểm 2. Nếu chưa cấu hình, chỉ trình diễn thông báo NOT CONFIGURED và Maps ngoài ứng dụng; không gọi đó là tìm Places thành công.
3. **Sửa nhận diện:** chọn lại ký hiệu từ Top 3 khi có output thật; nếu chưa có output, dùng vocabulary và nói rõ đó là chọn thủ công. Thay/xóa từ vừa chọn, xem Android preview đồng bộ, rồi tự bấm phát.

## Lỗi thường gặp

- Gemini 503: backend thử Gemini tối đa 2 lần, sau đó dùng Groq nếu đã cấu hình, chờ tăng dần giữa các lần; không đổi model trả phí. Tổng thời gian chờ tối đa 35 giây. 429 báo hạn mức, không retry dồn dập.
- Gemini chưa cấu hình: mock được ghi rõ; không coi đó là câu trả lời Gemini thực tế.
- Places chưa cấu hình: dùng Maps; không cần nạp tiền chỉ để chạy bản hiện tại.
- Không có ESP/MQTT: câu vẫn ở trên màn hình; chỉ báo thành công phát tiếng khi có trạng thái thật. Kiểm tra log `.tools/deafy-logs/system.log` trên Pi.
- Câu gợi ý đã cũ: ghép lại sau khi thay đổi câu; ứng dụng không áp dụng gợi ý lên bản nháp khác.

Không flash ESP, đổi I2S GPIO5/6/7, nguồn/gain, model hoặc credential để thử các chức năng trên.

## AI dự phòng Groq

Gemini vẫn là AI chính. Groq chỉ được gọi sau khi Gemini hết các lần thử với lỗi tạm thời (429, 5xx, timeout/mạng). 429 không retry dồn dập; 401/403 và lỗi cấu hình không chuyển provider. Không gọi hai provider song song.

Giao diện hiện nhãn Gemini, AI dự phòng: Groq hoặc Ngoại tuyến. Nếu cả hai lỗi, bản nháp vẫn có thể sửa/phát bằng TTS local. Mọi câu AI vẫn cần kiểm tra và thao tác phát rõ ràng.

Cấu hình riêng trong `backend/.env.local` trên Pi:

```dotenv
GROQ_API_KEY=nhap_key_rieng_tren_pi
GROQ_MODEL=openai/gpt-oss-20b
```

Đây là tên biến và giá trị mẫu, không chép đè file `.env.local` đang có. Giữ nguyên các biến Gemini, MQTT, ASR và discovery. Dùng editor trên Pi để thay key, không gửi key vào chat hoặc thêm vào frontend/APK. Sau khi thay cấu hình, restart service dự án khi không đang nghe/phát.

Groq dùng API riêng tại `https://api.groq.com/openai/v1`; tên model có `openai/` không yêu cầu OpenAI API key. Tài liệu: https://console.groq.com/docs/openai và https://console.groq.com/docs/reasoning . Hạn mức/chi phí phụ thuộc tài khoản; lượt triển khai này không bật billing hoặc gọi sinh văn bản thật.

Groq không thay thế dữ liệu Places hay GRU: tìm địa điểm vẫn cần bản đồ/Maps fallback, Top 3 vẫn từ softmax mô hình hiện có.
