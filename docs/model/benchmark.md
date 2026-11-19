# Benchmark model trên Windows

Model 1 là checkpoint cũ 25 nhãn; Model 2 là artifacts_2, 22 nhãn. Phản hồi mới nhất của bạn là Model 2 ổn định hơn; giữ Model 2 trong phòng thử, chưa thay Pi. Không chọn bằng confidence cao hơn hoặc trộn logits. Webcam bình thường chỉ chạy một model.

## Thu bộ dữ liệu độc lập

Chạy trong PowerShell tại DAKT-Nc:

```powershell
.\test_new_model_windows.bat
```

Mở URL launcher thông báo (thường http://localhost:5173, cổng dự phòng 5175/5176). Mở **Thu bộ benchmark độc lập · chỉ lưu landmarks**.

1. Điền mã người và session thật, dùng nhất quán. Chỉ dùng chữ Latin, số, `_`, `-`, không dùng tên/mật khẩu. P01/P02 đã có trong train; không đổi mã của cùng người để giả lập người mới.
2. Chọn validation hoặc final test trước khi thu. Ưu tiên người riêng cho final test. Không dùng cùng người/session ở hai tập. Công cụ chặn nội dung trùng và session lẫn hai tập, không xác minh được danh tính thật.
3. Chọn điều kiện và đúng nhãn thật. Bấm thu: có 2 giây chuẩn bị, sau đó 10 giây thực hiện đúng một ký hiệu; tay phải hiện rõ. Không làm chuỗi nhiều ký hiệu trong một mẫu.
4. Thu 20–30 mẫu mỗi nhãn chung (22 nhãn), nhiều người, ít nhất hai điều kiện. Thu thêm 20–30 mẫu mỗi loại âm: không cử chỉ, chuyển động ngẫu nhiên, ký hiệu ngoài tập nhãn.
5. Muốn đánh giá phạm vi riêng model cũ, thu thêm Goi, Hom_Nay, Xoa_Bo. Model mới không hỗ trợ ba nhãn này; chỉ số lớp được ánh xạ bằng tên checkpoint.

Mỗi mẫu nằm trong `.tools/model-test/benchmark-data/<split>/<subject>/<session>/`: NPZ landmarks/mask/timestamp và JSON nhãn/điều kiện/checksum. Không lưu ảnh/âm thanh, không training hoặc gửi cloud/Pi. Ground truth tự khai báo; kiểm tra nhãn trước khi benchmark. Không sửa nhãn/checksum sau khi xem final test.

## Benchmark và đóng băng final test

```powershell
# Dùng validation để chọn phương án; lưu báo cáo riêng
.\run_model_benchmark.bat --split validation --output .tools/model-benchmark/validation

# Chỉ chạy một lần khi đã thu XONG final test
.\run_model_benchmark.bat --freeze-test

# Chạy lại đúng tập test đã đóng băng
.\run_model_benchmark.bat
```

Không freeze khi đang thu. Manifest `frozen-test.json` không ghi đè; lần chạy sau giữ danh sách/checksum, không tự thêm mẫu mới. Muốn đánh giá lần khác, dùng corpus mới qua `--capture-dir` và thư mục báo cáo mới qua `--output`; không xóa manifest để chọn lại kết quả đẹp hơn. Không điều chỉnh threshold/routing/hybrid theo final test.

Nếu chưa thu webcam test, mặc định chỉ dùng raw không xuất hiện ở cả train lẫn validation của hai checkpoint. Hiện chỉ có 30 mẫu Goi_Dien_Thoai, người P02 đã biết: không đủ kết luận 22 lớp hay người mới. Validation rỗng được báo thiếu, không mượn final test.

Hai model chạy tuần tự trên cùng đầu vào. Để đo tốc độ sạch hơn, tắt camera bằng nút trên trang trước khi chạy benchmark; không đổi gate/threshold.

## Đọc kết quả

Trong `.tools/model-benchmark/latest/`:

- `report.md`: tóm tắt; có link từ trang thử sau khi chạy lệnh.
- `report.json`: precision/recall/F1, accuracy, macro F1, từng người/điều kiện, âm/nhầm/bỏ sót/lặp, timing, tài nguyên, độ phủ.
- `per_class.csv`, `confusion_old.csv`, `confusion_new.csv`: mở Excel; ô trống/null là thiếu dữ liệu hoặc mẫu số, không phải 0 hay 100%.

Thời gian xác nhận tính từ cue thu, chưa phải onset động tác được gán nhãn video. FPR là tỷ lệ clip âm có sự kiện, kèm sự kiện/phút. Replay FPS không phải FPS camera. CPU/RAM gồm tiến trình Windows/Python/Torch, không phải RAM riêng trọng số hoặc hiệu năng Pi.

Chính sách mô tả cố định: final test đã freeze, đủ mẫu/lớp/âm/người/điều kiện và có người ngoài train/validation; macro F1 hơn ít nhất 0,02, FPR không tăng, P95 không quá 1,2 lần. Không phải kiểm định ý nghĩa thống kê. Chưa đủ validation/calibration độc lập nên hybrid NOT ELIGIBLE; không bật chế độ hoặc kết quả hybrid giả. Việc học routing nếu có phải dùng validation, sau đó nghiệm thu phương án cố định trên final test.

```powershell
.\.venv-model-test\Scripts\python.exe -m pytest backend\tests Deafy_AI_share_ver0\tests\test_inference_pipeline.py -q
.\stop_new_model_windows.bat
```

Log tại `.tools/model-test/server.out.log`, `server.err.log`. Không cần build Vite/APK cho trang thử tĩnh. Không đổi Pi, MQTT, ESP32, TTS, khóa API hoặc model production. Xem báo cáo triển khai `docs/model/benchmark.md`.
