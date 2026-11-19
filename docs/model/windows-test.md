# Thử artifacts_2 trên Windows — chưa cập nhật Pi

Cập nhật 05/11: theo phản hồi mới nhất, model mới ổn định hơn và đang là ứng viên thử. Xem [hướng dẫn benchmark độc lập](benchmark.md) và [kết quả hiện tại](../model/benchmark.md). Chưa đủ dữ liệu chọn winner hoặc bật hybrid; không suy kết quả 30 mẫu một nhãn thành accuracy 22 nhãn.

Đã tạo môi trường webcam riêng. UI SignAssist và backend Pi hiện có giữ nguyên. Không dùng SQLite, Gemini/Groq key, MQTT hoặc ESP32 của Pi trong phòng thử này.

## Mở nhanh

Nhấn đúp `test_new_model_windows.bat`, hoặc tại PowerShell trong DAKT-Nc:

```powershell
.\test_new_model_windows.bat
```

Mặc định mở model mới `artifacts_2`. Launcher tự chọn cổng 5173; nếu cổng đang được ứng dụng khác sử dụng thì chọn 5175 hoặc 5176 và báo URL thực tế. Không tắt ứng dụng đang chiếm cổng. Trên máy này đã thử thành công tại **http://localhost:5173**.

Sau phản hồi model mới nhận sai/nhảy chữ, tui đã chuyển tạm phòng thử về **model cũ 25 nhãn** để so sánh. Bạn vẫn có thể chọn lại model mới trong trang; model đang hoạt động luôn theo mục chẩn đoán của server. Bạn xác nhận model cũ ổn hơn. Chạy lại file `.bat` mặc định sẽ chọn model mới; muốn mở model cũ ngay:

```powershell
.\test_new_model_windows.bat -Profile old
```

Đổi camera nếu laptop có nhiều thiết bị:

```powershell
.\test_new_model_windows.bat -CameraIndex 1
```

Tham số camera áp dụng khi khởi tạo tiến trình mới; dừng môi trường thử trước khi đổi camera index.

## Thao tác

1. Kiểm tra tên checkpoint ở đầu trang, phiên bản run và SHA256 trong phần chẩn đoán.
2. Camera có hình, điểm tay bật theo checkbox. Làm ký hiệu với tay phải trong khung ít nhất 3 giây.
3. Theo dõi tiến độ, confidence/Top 3 thực tế. Chỉ dòng **Kết quả đã xác nhận** nhận các sự kiện qua gate; Top 3 thay đổi chưa có nghĩa đã xác nhận ký hiệu.
4. Bấm **Xóa kết quả thử** để xóa lịch sử trên trang thử. Không xóa dữ liệu production.
5. Đổi model: chọn **Model cũ** hoặc **artifacts_2**, rồi bấm **Đổi model**. Camera cũ được dừng/giải phóng trước khi nạp model khác; phiên này bỏ lịch sử kết quả cũ để tránh lẫn nhãn. Không đổi model trong lượt đánh giá đang chạy.
6. Model mới hỗ trợ 22 nhãn đọc từ checkpoint. Không có `Goi`, `Hom_Nay`, `Xoa_Bo`; chúng chỉ xuất hiện khi dùng model cũ 25 nhãn.

Ngưỡng vẫn **0,7**, cần **3 dự đoán ổn định**, cooldown **2 giây**, latch chống phát lặp, cửa sổ **3 giây/30 frame**. Không hạ ngưỡng hoặc thay preprocessing để làm demo trông tốt hơn. Phải phân biệt thời gian GRU forward khoảng 1 ms với thời gian chờ đủ cử chỉ 3 giây cộng ổn định; chúng không phải cùng độ trễ.

## Ghi đánh giá thay vì đoán accuracy

Chọn nhãn dự định làm trong **Đánh giá có nhãn người dùng**, bấm **Ghi lượt 10 giây**, rồi thực hiện đúng nhãn đó. Thử cùng ký hiệu, cùng người, vị trí/ánh sáng ở hai model. Mục **Không làm ký hiệu** dùng để kiểm tra nhận nhầm trong 10 giây; không thực hiện ký hiệu trong lượt này.

Kết quả lưu ở `.tools/model-test/trials.jsonl`: model/SHA, nhãn người dùng chọn, các nhãn đã xác nhận, số sự kiện sai, thời gian và metrics. Không lưu ảnh/âm thanh hoặc tự training. Nhãn kỳ vọng do người dùng khai báo, chưa được người thứ hai xác minh. Lượt không có frame hợp lệ không được coi là nhận diện đúng hoặc không có false positive. Chưa có lượt gắn nhãn thì không có accuracy webcam để báo cáo.

Model mới đã tải và chạy webcam, nhưng bạn phản hồi nhận sai/nhảy chữ; model cũ ổn hơn. Kết quả so sánh file dữ liệu nằm trong `docs/release/TEST_REPORT.md`. **Chưa đủ điều kiện đưa model mới lên Pi.**

## Dừng và quay lại preview Pi

Bấm **Dừng môi trường thử** trên trang hoặc chạy:

```powershell
.\stop_new_model_windows.bat
```

Sau khi tiến trình thử đã dừng và nhả cổng/camera:

```powershell
.\start_pi_preview.bat
```

Thao tác này dùng lại proxy/discovery và backend Pi hiện có. Không cần sửa URL/token trong file cấu hình; trang thử không sửa localStorage hoặc cấu hình frontend production.

## Môi trường Python

`.venv-model-test` là venv Python riêng, chứa **bản sao độc lập** các package đang hoạt động của `backend/.venv`. Không dùng system-site-packages hoặc sửa gói trong venv nguồn. Đã kiểm tra Torch/OpenCV/MediaPipe/FastAPI/Uvicorn thực sự được import từ venv mới. Bản sao khoảng 1,34 GB, không cần tải model/phần mềm cloud.

Phiên bản đã kiểm thử: Python 3.12; Torch 2.14.1+cpu, NumPy 1.26.4, MediaPipe 0.10.21 (API `solutions`), OpenCV 4.11.0.86, FastAPI 0.115.12, Uvicorn 0.34.2. Checkpoint được train bằng Torch 2.14.1+cu130, đã load strict và chạy CPU thành công.

Nếu venv thử chưa tồn tại, launcher tạo từ `backend/.venv` đã được cài đặt. Có thể chuẩn bị/kiểm tra thủ công:

```powershell
.\backend\.venv\Scripts\python.exe tools\preview\prepare_model_test_env.py
.\.venv-model-test\Scripts\python.exe tools\preview\prepare_model_test_env.py --check
```

Nếu máy chưa có cả `backend/.venv`, xem `backend/README.md`, tạo venv và cài theo `backend/requirements-windows.lock` trước. Không nâng cấp các gói production chỉ để thử model mới. Cấu hình môi trường đã kiểm tra lưu tại `.tools/model-test/environment.json`.

## Log, test và so sánh lại

- Server: `.tools/model-test/server.out.log`, `server.err.log`.
- File chọn tiến trình/cổng riêng: `.tools/model-test/runtime.json`; không chứa key Pi/Gemini/Groq/MQTT.
- Báo cáo số liệu: `.tools/model-test/comparison.json`.
- Báo cáo và backup: `docs/release/TEST_REPORT.md`, `.tools/model-test-backup.txt`.

```powershell
.\.venv-model-test\Scripts\python.exe scripts\compare_model_checkpoints.py
.\.venv-model-test\Scripts\python.exe -m pytest backend\tests Deafy_AI_share_ver0\tests\test_inference_pipeline.py -q
```

Web tĩnh của phòng thử dùng FastAPI, không có bước build Vite/APK. Đã kiểm tra trình duyệt, cú pháp JS và regression backend. Nếu mất camera/thiếu quyền, trang báo lỗi; kiểm tra Privacy → Camera của Windows, camera index và ứng dụng khác đang giữ webcam. Không đổi driver, threshold hoặc model Pi để xử lý lỗi webcam Windows.

Chưa triển khai model lên Pi, chưa build APK. Chỉ xem xét Pi khi có kiểm thử độc lập tốt hơn và bạn xác nhận sau đó.
