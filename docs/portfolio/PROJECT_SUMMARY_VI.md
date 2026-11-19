# Deafy — Trợ lý giao tiếp ngôn ngữ ký hiệu

Deafy là dự án môn học chạy trên Raspberry Pi 5 RAM 4 GB. Dự án phân loại một tập ký hiệu đã huấn luyện, ghép thành bản nháp tiếng Việt có thể chỉnh sửa, gửi yêu cầu AI theo thao tác người dùng và phát giọng qua ESP32-S3.

MediaPipe trích xuất điểm tay; GRU đọc cửa sổ 30 × 126. Pi dùng FastAPI, SQLite và MQTT để điều phối. Android có suy luận tại chỗ; ESP32-S3 đưa âm thanh qua I2S tới MAX98357A. Mẫu người dùng gửi cần được duyệt trước khi dùng để huấn luyện lại.

Kết quả đã lưu: 115/115 tensor validation có top-1 và top-3 trùng giữa Pi PyTorch và ONNX cũ cùng trọng số. Đây là độ tương đương runtime, không phải độ chính xác theo camera. Trước khi đưa lên CV, bổ sung phần việc cá nhân có thể chứng minh, không lấy phần của nhóm làm thành tích riêng.
