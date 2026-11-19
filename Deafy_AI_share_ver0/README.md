# Deafy_AI — Bản chuyển máy để thu dữ liệu song song

Bản này chứa code 6 bước và tests, không chứa dataset, checkpoint, split, môi trường
`.venv`, lịch sử Git hoặc thông tin kết nối ChatGPT. Giải nén vào một thư mục riêng
trên máy người hỗ trợ; không cần dùng đúng ổ D như máy gốc.

## 1. Chuẩn bị máy người hỗ trợ

Cài Python 3.12 bản 64-bit. Mở PowerShell trong thư mục vừa giải nén
(chứa README này và các file `step*.py`), chạy:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe step1_test_mediapipe.py
```

Chưa cần PyTorch/GPU để kiểm tra camera và thu dữ liệu. Đóng Zoom/Teams nếu webcam
bị chiếm, cấp quyền Camera cho desktop apps. Kiểm tra vẽ landmarks cả hai tay,
đưa tay ra rồi vào lại, nhấn Q/Esc để thoát. Có thể thử `--backend dshow` hoặc
`--camera 1` nếu cần. Không cài chồng opencv-python/headless lên opencv-contrib-python.

## 2. Thống nhất trước khi chia nhau thu

- Máy chính hiện dùng **P01**. Người thứ hai dùng **P02**, người thứ ba P03.
  Mỗi người thực hiện ký hiệu có mã riêng; đổi máy nhưng cùng người thì giữ mã đó.
  Luôn truyền `--signer`, vì mặc định của chương trình là P01.
- Nhãn hiện tại: **Bat_Den**, **Dong_Y**, **Tam_Biet**. Viết đúng chữ hoa/thường,
  không đổi thành tên có dấu hoặc tạo thư mục theo tên người ở bên dưới thư mục nhãn.
- Mỗi mẫu: một lần ký hiệu trong **2 giây**, **30 frame**, XYZ hai tay theo thứ tự
  Left rồi Right; shape `(1,30,126)`, float32. Giữ nguyên code trích xuất, không tự
  đổi chiều ảnh, thứ tự tay, thời lượng hoặc số frame ở một máy.
- Ba nhãn hiện tại được thu với `--required-hands right`. Ví dụ dưới giữ quy tắc này.
  Nếu thống nhất chuyển một nhãn sang hai tay, cả nhóm dùng `both` cho nhãn đó và
  kiểm tra lại dữ liệu cũ trước khi gộp. Tham số này kiểm tra sự hiện diện tay,
  không biến hai cách làm ký hiệu khác nhau thành cùng một động tác.
- Thống nhất động tác, nghĩa của từng nhãn và tư thế bắt đầu/kết thúc bằng một mẫu
  biểu diễn chung. Script không kiểm tra ký hiệu có đúng VSL hay không.
- Có thể phân công theo người/nhãn/số mẫu; ghi lại số mẫu từng nhãn đã thu.
  Tên file có thời gian UTC + UUID; session_id tự tạo mỗi lần mở chương trình.

## 3. Thu dữ liệu trên máy người hỗ trợ

Chạy lần lượt từng lệnh, thoát phiên hiện tại trước khi chạy nhãn kế tiếp:

```powershell
.\.venv\Scripts\python.exe step2_collect_data.py --label Bat_Den --signer P02 --required-hands right --duration 2 --sequence-length 30
.\.venv\Scripts\python.exe step2_collect_data.py --label Dong_Y --signer P02 --required-hands right --duration 2 --sequence-length 30
.\.venv\Scripts\python.exe step2_collect_data.py --label Tam_Biet --signer P02 --required-hands right --duration 2 --sequence-length 30
```

Trong cửa sổ camera: đưa tay vào hình → Space → đếm ngược 3 giây → thực hiện
một ký hiệu trong lúc RECORDING → REVIEW → S lưu hoặc R bỏ. Lặp lại Space để thu
mẫu mới; Q/Esc thoát. REVIEW hiển thị webcam trực tiếp, không phát lại mẫu.
Mất dấu tay bắt buộc sẽ hủy mẫu; thu lại, không điền tọa độ bằng tay.

Chương trình tự tạo `data/raw/<nhãn>/`. Mỗi mẫu gồm **một .npy và một .json cùng tên**.
JSON chứa signer, session_id và cấu hình thu. Luôn giữ cả cặp, không sửa/đổi metadata.
Không cần chạy bước 3–6 để thu và gửi dữ liệu.

## 4. Gửi kết quả và hợp nhất sau này

Sau khi thoát chương trình thu, người hỗ trợ nén thư mục `data/raw` mới tạo:

```powershell
Compress-Archive -Path .\data
aw -DestinationPath .\P02_raw_v1.zip
```

Dùng tên v2, v3... cho đợt gửi sau. Gửi ZIP này kèm số mẫu mỗi nhãn, mã người và
những thay đổi đã thống nhất. Không gửi .venv hoặc model. Nếu gửi toàn bộ dữ liệu
lần nữa, ghi rõ đây là bản đầy đủ để máy chính không nhập trùng đợt trước.

Trên máy chính:

1. Sao lưu dataset đang có. Giải nén gói nhận vào một thư mục `incoming/P02_v1`
   riêng, chưa giải nén thẳng đè vào dataset chính.
2. Kiểm tra từng cặp NPY/JSON: tên nhãn khớp thư mục, signer đúng P02, shape
   `(1,30,126)`, float32, hữu hạn; cấu hình/tay/ký hiệu đúng quy ước nhóm.
3. Chép **từng cặp** vào `data/raw/<nhãn>/` tương ứng, giữ nguyên tên file và
   metadata. Không tạo `data/raw/P02/<nhãn>` hoặc `data/raw/<nhãn>/P02`.
   Nếu trùng tên, dừng kiểm tra nội dung; không chọn Replace/ghi đè.
4. Sau khi gộp, tạo manifest mới, không dùng hoặc ghi đè split đã dùng để train:

```powershell
.\.venv\Scripts\python.exe step3_smoke.py --manifest artifacts/step3_split_merged_v1.json
.\.venv\Scripts\python.exe step4_smoke.py
.\.venv\Scripts\python.exe step5_train.py --split artifacts/step3_split_merged_v1.json --epochs 3 --device cpu
```

Bước 3 kiểm tra NPY và từ chối mẫu trùng nội dung; bước 5 kiểm tra thêm metadata.
Các kiểm tra này không thay thế việc kiểm chứng động tác/nhãn trước khi nhập.
Split hiện tại vẫn là chia theo mẫu; thêm P02 không tự biến nó thành đánh giá trên
người chưa thấy. Muốn đo khả năng tổng quát hóa cần thiết kế split theo người/phiên.
Nếu hai người cùng sửa code, gửi riêng phần code đã sửa và ghi thay đổi để đối chiếu;
không ghi đè toàn bộ dự án chính bằng bản trên máy phụ.

## 5. Chạy các bước còn lại khi cần

Chỉ cần cài PyTorch nếu muốn chạy tests hoặc bước 3–6. Bản CPU đủ cho máy thu:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.14.1+cpu --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

| Bước | File chạy | File hỗ trợ |
|---|---|---|
| 1 | step1_test_mediapipe.py | — |
| 2 | step2_collect_data.py | — |
| 3 | step3_smoke.py | step3_dataset.py |
| 4 | step4_smoke.py | step4_model.py |
| 5 | step5_train.py | step5_training_data.py |
| 6 | step6_app.py | step6_inference_pipeline.py |

Bước 3 cần dữ liệu đã thu, bước 5 cần split mới và bước 6 cần checkpoint tự train
hoặc nhận riêng. Gói này không kèm các file đó. Ví dụ sau khi tự thu đủ dữ liệu:

```powershell
.\.venv\Scripts\python.exe step3_smoke.py
.\.venv\Scripts\python.exe step4_smoke.py
.\.venv\Scripts\python.exe step5_train.py --epochs 3 --device cpu
# Thay TEN_RUN bằng thư mục thực tế được in sau khi train:
.\.venv\Scripts\python.exe step6_app.py --checkpoint artifacts/step5/TEN_RUN/best_model.pth --required-hands right
```

Tài liệu chi tiết: [Bước 2](guide/STEP2.md), [Bước 3](guide/STEP3.md),
[Bước 4](guide/STEP4.md), [Bước 5](guide/STEP5.md), [Bước 6](guide/STEP6.md).
Các tài liệu chi tiết giữ ví dụ đường dẫn/kết quả máy gốc để tham khảo;
hãy dùng thư mục hiện tại, checkpoint thực tế và quy ước nhóm trong README này.


.\.venv\Scripts\python.exe step6_app.py --checkpoint "D:\Study\ki7_2026_2027\DAKT-Nc\Deafy_AI_share_ver0\artifacts\step5\run_20261026T045637Z_ebe324f6\best_model.pth" --check-only

.\.venv\Scripts\python.exe step6_app.py --checkpoint "D:\Study\ki7_2026_2027\DAKT-Nc\Deafy_AI_share_ver0\artifacts\step5\run_20261026T045637Z_ebe324f6\best_model.pth" --required-hands right