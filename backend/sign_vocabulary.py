"""Display names of the existing supplied sign labels; no new model classes."""
LABEL_TEXT = dict(zip(
    ['An_Com', 'Bat_Den', 'Cha', 'Chinh_Sua', 'Chup_Anh', 'Dia_Chi', 'Dong_Y',
     'Dung_Khong', 'Goi', 'Goi_Dien_Thoai', 'Hom_Nay', 'Khong_Dong_Y', 'Me',
     'Mo', 'Quat_Cay', 'Tai_Sao', 'Tam_Biet', 'Tat', 'Tat_Den', 'Them',
     'The_Nao', 'Thoi_Tiet', 'Tim', 'Xin_Chao', 'Xoa_Bo'],
    ['Ăn cơm', 'Bật đèn', 'Cha', 'Chỉnh sửa', 'Chụp ảnh', 'Địa chỉ', 'Đồng ý',
     'Đúng không', 'Gọi', 'Gọi điện thoại', 'Hôm nay', 'Không đồng ý', 'Mẹ',
     'Mở', 'Quạt cây', 'Tại sao', 'Tạm biệt', 'Tắt', 'Tắt đèn', 'Thêm',
     'Thế nào', 'Thời tiết', 'Tìm', 'Xin chào', 'Xóa bỏ']))

VOCABULARY = {key.lower(): text for key, text in LABEL_TEXT.items()}
