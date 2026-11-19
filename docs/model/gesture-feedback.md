# Thu mẫu và huấn luyện lại trên dự án môn học

Mở SignAssist trên Pi 5 4 GB, vào **Cài đặt → AI học từ người dùng** và bật **Bắt đầu phiên thu mẫu**. Quay lại **Giao tiếp**, bật camera và làm ký hiệu. Bấm **Đúng · Lưu mẫu**, hoặc bấm **Sai**, chọn nhãn đúng rồi bấm **Lưu mẫu đã sửa**. Mẫu chờ duyệt chứa đúng 30 × 126 đặc trưng đầu vào của GRU. Hệ thống giữ tối đa sáu chuỗi gần nhất trong RAM và cho phép xác nhận trong 45 giây. Video không được lưu vào kho mẫu.

Trong **Xem kho mẫu**, duyệt mẫu chính xác, loại hoặc xóa mẫu sai. Tắt rồi bật thu mẫu để tạo phiên mới. Thu riêng phiên huấn luyện, phiên kiểm định và phiên kiểm thử, với điều kiện quay khác nhau. **Xuất mẫu đã duyệt** tạo tập dùng cho laptop. **Sao lưu toàn bộ mẫu** gồm cả mẫu chờ duyệt và mẫu bị loại. Cất bản sao như dữ liệu cá nhân.

## Huấn luyện từ giao diện Pi

1. Vào **Cài đặt → AI học từ người dùng → Huấn luyện trên laptop**. Xem số mẫu đã duyệt theo từng nhãn. Khoảng 20 mẫu cho một nhãn cần cải thiện là mốc tham khảo.
2. Thu tối thiểu ba phiên riêng. Hai phiên dùng để kiểm định và kiểm thử cần ít nhất hai mẫu đã duyệt của mỗi nhãn. Phiên còn lại cung cấp mẫu mới cho train. Thay đổi góc, khoảng cách và tốc độ thực hiện giữa các phiên. Chỉ mẫu đúng phiên bản model đang chạy được chọn.
3. Bấm **Chuẩn bị huấn luyện** để chốt một bộ dữ liệu. Nếu vừa duyệt thêm mẫu, chuẩn bị gói mới trước khi gửi đi.
4. Trên laptop Windows, mở `start_course_training_agent.bat`, chọn URL HTTPS của Pi (mặc định `https://deafy.local:8443`) và nhập mã truy cập Sign Assist trong Terminal. Máy cần Python môi trường `backend/.venv` có PyTorch CPU và NumPy. Nếu dùng chứng chỉ Caddy nội bộ, đặt chứng chỉ CA công khai đã xác minh của chính Pi tại `.tools/course-pi-ca.crt`.
5. Khi Pi báo **Laptop đã kết nối**, bấm **Bắt đầu huấn luyện**. Pi cập nhật số vòng đã hoàn tất. Laptop lưu file ZIP kể cả khi gửi về Pi thất bại. Khi mất kết nối và lượt bị treo, chọn **Đặt lại lượt** rồi nhập file ZIP đã có hoặc bắt đầu lại.

## Khi laptop không kết nối Pi

Sau khi chuẩn bị, bấm **Tải gói dữ liệu**, chuyển file JSON sang laptop và chạy trong thư mục dự án:

```powershell
.ackend\.venv\Scripts\python.exe scripts/course_training_agent.py train deafy-GOI.json model.zip
```

Sau khi chạy xong, chọn **Nhập gói model ZIP** trên Pi. Nếu đã đổi sang một model học lại mà laptop thiếu checkpoint đó, chỉ định `--baseline DUONG_DAN_CHECKPOINT`. Nếu dữ liệu gốc nằm chỗ khác, dùng `--original THU_MUC_RAW`. Mỗi file gốc được đối chiếu SHA-256 với dữ liệu dùng cho baseline. Train sẽ báo thiếu nếu cả dữ liệu cũ và mẫu mới đều thiếu cho một nhãn. Với kho dữ liệu laptop hiện có, nên thu thêm mẫu train cho **Gọi điện thoại** và **Tìm**.

## Đánh giá, áp dụng và khôi phục

- Mở **Kết quả đánh giá** để xem accuracy, macro F1 và precision/recall/F1 từng nhãn. Hai model chạy trên cùng bộ test độc lập. Trainer từ chối dữ liệu gần trùng giữa các tập. Cổng đánh giá cho phép giảm tối đa 2 điểm phần trăm về accuracy và macro F1 và 5 điểm F1 cho Chào, Tạm biệt, Bật đèn, Tắt đèn.
- Bấm **Kiểm tra trên Pi** để đo p95 và RAM của GRU, kiểm tra bộ nhãn và checksum. Sau khi cả hai bước kiểm tra đạt, bấm **Áp dụng model mới** và xác nhận. Pi khởi động lại dịch vụ, xác minh checksum đã nạp và thử lấy ảnh camera. Nếu kiểm tra lỗi, Pi phục hồi cấu hình model trước. Chờ giao diện kết nối lại trước khi thao tác tiếp.
- Bấm **Khôi phục model cũ** khi muốn quay về phiên bản liền trước. Checkpoint Model 2 và kho mẫu được giữ nguyên. Với nhiều phiên bản, có thể khôi phục từng bước. Xem lỗi chi tiết bằng `journalctl --user -u deafy-course-model`.
- Gói JSON chứa keypoints cá nhân. Chỉ giữ và gửi qua thiết bị hoặc kết nối bạn tin cậy. Báo cáo chạy với dữ liệu tổng hợp chỉ dùng kiểm tra pipeline.
