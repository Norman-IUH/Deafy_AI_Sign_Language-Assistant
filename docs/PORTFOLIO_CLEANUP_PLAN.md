# Deafy RC8 — đề xuất dọn repository

Đã đối chiếu cả 294 đường dẫn theo dõi từ checkout có HEAD trùng GitHub `main` tại `1dc4aca27d0d14892d784f90a691f01b2c4ddd8f`. GitHub báo Private. Nhánh `chore/portfolio-cleanup` hiện chỉ tồn tại cục bộ. Đây là báo cáo xin duyệt; chưa di chuyển, xóa hoặc triển khai source.

## KEEP

| Phạm vi | Lý do |
| --- | --- |
| `backend/`, `RaspberryPi_7inch/`, `Android_App/`, `ESP32_SignAssist/`, `shared/`, `mqtt/`, `iPhone_GPS/` | Các thành phần chạy thực tế, cấu hình mẫu và test. iPhone là đường chia sẻ GPS. Các trang `public/preview.html` có hướng dẫn sử dụng và nằm trong luồng build Vite; giữ nguyên. |
| `Deafy_AI_share_ver0/` toàn bộ | Backend nhập code từ thư mục này; script export/parity/huấn luyện cũng tham chiếu nó. Tên có chữ “share” nhưng đây là dependency Model 2, không phải bản lưu dư. Giữ nguyên đường dẫn, không thêm hoặc thay trọng số. |
| `Deafy AI.desktop`, `start_deafy.sh`, `stop_deafy.sh`, `start_pi.sh`, `START_DEAFY_DEMO.bat`, `start_cit_tunnel.bat` | Giữ điểm vào Pi và laptop, gồm alias CIT. Service/start/stop kiểm tra đường dẫn `start_pi.sh`; đổi chỗ có thể làm hỏng launcher đã cài. |
| `start_all_preview.bat`, `start_android_preview.bat`, `start_pi_preview.bat`, `start_backend.bat` | Giữ lối mở bằng một cú nhấp. Chỉ sửa đường dẫn gọi PowerShell theo bảng MOVE. |
| Các script còn lại, docs hiện hành, README thành phần, CHANGELOG, ignore files và cấu hình mẫu | Giữ export/parity Model 2, huấn luyện, QA APK, build PWA, stage assets, service và công cụ release. Giữ cả `backend/pi.env.example` (profile Pi đầy đủ) và `backend/.env.example` (mẫu tối thiểu) với vai trò ghi rõ. |

## MOVE

| Tệp hiện tại | Đích / cách làm | Ảnh hưởng cần xử lý |
| --- | --- | --- |
| `HUONG_DAN_CHAY_DEAFY.md`, `HUONG_DAN_BUILD_APK.md`, `HUONG_DAN_CIT_VOICE.md`, `HUONG_DAN_IPHONE_PWA.md` | `docs/setup/{pi,android,cit-voice,iphone-gps}.md` | Sửa link README và release notes. Hướng dẫn APK có đoạn cũ nói không đóng gói trọng số và link tới báo cáo vắng mặt; cập nhật theo RC8 và yêu cầu asset khi build từ source sạch. Giữ GPS, không mở lại Safari inference. |
| `HUONG_DAN_PLACES_API.md`, `HUONG_DAN_SIGNASSIST_AI.md` | Gộp vào `docs/guides/assistant-and-places.md` | Giữ cấu hình backend, quy trình GPS và xử lý lỗi. Xóa nội dung trùng sau khi đối chiếu; phân biệt tìm gần và tìm địa chỉ. |
| `HUONG_DAN_HOC_CU_CHI_PI4GB.md`, `HUONG_DAN_BENCHMARK_MODELS.md`, `HUONG_DAN_THU_MODEL_WINDOWS.md` | `docs/model/{gesture-feedback,benchmark,windows-test}.md` | Giữ hướng dẫn thu mẫu, benchmark và phòng thử. Cập nhật tham chiếu trong script, README và đường dẫn tương đối; không đổi dataset/checkpoint. |
| `scripts/start-preview.ps1`, `scripts/check-preview.ps1`, `scripts/start-model-test.ps1`, `scripts/prepare_model_test_env.py` | `tools/preview/` | Sửa logic tìm thư mục gốc theo độ sâu mới; kiểm tra bốn BAT gọi preview, lệnh model test và export. |
| `scripts/check-android-offline.cjs`, `check-android-preview.cjs`, `check-dual-preview.cjs`, `check-pi-fullscreen.cjs`, `check-pi-input.cjs`, `ui_fixture.py` | `tools/qa/` | Sửa import backend của fixture và link README. Fixture chỉ dùng backend mock riêng; không chạy trên Pi thật. |

## REMOVE — chỉ sau khi duyệt

| Tệp | Lý do / ảnh hưởng |
| --- | --- |
| `PORTFOLIO_MANIFEST.json` ở gốc | Snapshot checksum của archive cũ, sẽ không còn đúng sau khi đổi đường dẫn. Giữ việc tạo manifest bên trong archive bằng `scripts/prepare_portfolio.py`; cập nhật script để lấy docs/tools mới. Không phải dependency chạy app. |
| `scripts/prepare_handover.py` | Export RC1 cũ trùng nhiệm vụ với `prepare_portfolio.py`, ghi vào layout bàn giao cũ và tham chiếu cây thư mục không có trên GitHub. Không tìm thấy caller chạy ứng dụng. Chuyển chức năng còn cần sang export portfolio trước khi bỏ. |
| Hai hướng dẫn AI/Places ở đường dẫn cũ | Chỉ bỏ sau khi đã gộp nội dung không trùng và cập nhật link. |

## Sau khi duyệt

- Chỉ sửa review checkout trên nhánh cleanup. Chạy tìm đường dẫn cũ, kiểm tra link, so sánh diff và chạy backend pytest, Node tests, build Pi và Android. Dùng asset/SDK cục bộ nếu được phép; không đưa trọng số vào Git. Sửa cả thông báo `start_pi.sh` đang trỏ tới `docs/PI_AI_IOT.md` không có trong repo.
- Rà lại index và lịch sử có thể đẩy để tìm secret, dữ liệu cá nhân, tệp build và tài sản không có quyền phân phối. Giữ notes giấy phép; nếu phát hiện tài sản chưa rõ quyền, dừng push. Chỉ push nhánh cleanup tới repo Private và mở PR về `main`; không merge.
- Không thay đổi workspace sản xuất, checkpoint, dữ liệu huấn luyện hay bản triển khai trên Raspberry Pi. Chưa chạy build/test vì chưa áp dụng thay đổi.
