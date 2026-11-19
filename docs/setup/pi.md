# Chạy Deafy AI / Sign Assist

## 1. Kiến trúc và địa chỉ

Pi là máy chủ duy nhất: FastAPI, SQLite, camera USB, MediaPipe + GRU, nhận tiếng Việt Zipformer, Gemini, eSpeak NG và MQTT. Android/Pi UI dùng cùng REST + WebSocket. ESP32 nhận lệnh từ backend Pi, trả ACK/PLAYING/DONE/ERROR. Chỉ chế độ Điều khiển IoT được gửi lệnh relay; Hỏi AI không diễn giải câu hỏi thành lệnh thiết bị.

| Thành phần | Địa chỉ |
|---|---|
| Pi UI trên màn hình Pi | `http://localhost:5173` |
| Backend trên Pi | `http://127.0.0.1:8001` |
| Backend từ điện thoại/Windows | `http://IP_LAN_PI:8001` |
| Android preview trên Windows | `http://localhost:5174` |
| MQTT local trên Pi | cổng `1883`, có tài khoản riêng |

Pi hiện dùng thư mục `/home/pipi/Desktop/Test`. Khi chuyển máy, chép toàn bộ source cần thiết gồm backend, shared, RaspberryPi_7inch, scripts và Deafy_AI_share_ver0/artifacts. Không chép venv/node_modules Windows sang Pi. Không sửa/đổi model đang dùng chỉ vì tên khác `gru_best.pt`: hiện backend ưu tiên checkpoint Deafy `best_model.pth` 25 nhãn đã xác minh, sau đó mới đến pipeline mẫu/YOLO + GRU cũ nếu đủ file. Không có `gru_best.pt`/`hand_pose.pt` trong backend/data hiện tại.

## 2. Pi hiện tại: mở bằng một nhấn

Launcher **Deafy AI** đã được cài trên Desktop. Nhấn đúp để kiểm tra dependency, tái sử dụng hoặc mở một backend, đợi API sẵn sàng, bật camera/inference và mở Chromium. Micro chỉ thu khi bấm Bắt đầu nghe.

Nếu desktop yêu cầu, chọn cho phép khởi chạy launcher. Để cài lại launcher sau khi đổi thư mục, mở Terminal trong gốc dự án:

```bash
bash scripts/install-deafy-launcher.sh
bash start_deafy.sh
```

Các lệnh khác, cũng chạy từ gốc dự án:

```bash
bash start_deafy.sh --check    # chỉ kiểm tra, không mở camera
bash start_deafy.sh --kiosk    # mở toàn màn hình
bash start_deafy.sh --no-ui    # chạy qua SSH, không mở cửa sổ
bash stop_deafy.sh
```

`stop_deafy.sh` dừng backend, inference, camera/micro và cửa sổ do launcher mở. Không kill theo tên Python/Node và không tắt browser khác hoặc Mosquitto dùng chung. Các lần mở đồng thời được khóa bằng flock; systemd chỉ giữ một service. Nếu thiếu camera/model, giao diện thông báo lỗi để vẫn sửa cấu hình và dùng các phần còn hoạt động.

Service được sinh từ template theo đường dẫn thực của checkout, không chép template trực tiếp vào systemd. Cấu hình service cũ được backup trước khi thay. Script kiểm tra unit hợp lệ trước khi cài.

## 3. Cài lần đầu trên Pi mới

**Không chạy lại bước tạo venv/cấu hình trên Pi hiện tại đang hoạt động.** Bộ đã kiểm tra là Pi 5 4GB, OS 64-bit Debian 13, Python 3.12, Node 22. Python mặc định 3.13 của OS không phải môi trường đã kiểm chứng cho MediaPipe 0.10.18.

Sau khi chép source và mở Terminal trong gốc dự án:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nodejs npm alsa-utils ffmpeg espeak-ng mosquitto mosquitto-clients chromium zenity xdg-user-dirs

# Chỉ khi chưa có backend/.venv-pi:
python3 -m venv .tools/bootstrap
.tools/bootstrap/bin/python -m pip install uv
.tools/bootstrap/bin/uv python install 3.12
.tools/bootstrap/bin/uv venv --python 3.12 backend/.venv-pi
backend/.venv-pi/bin/python -m ensurepip
backend/.venv-pi/bin/python -m pip install -r backend/requirements-pi.txt

# Kiểm tra Node >=20.19 hoặc >=22.12; Pi hiện dùng Node22 qua nvm.
node --version
npm --prefix RaspberryPi_7inch ci
```

`requirements-pi.txt` dùng MediaPipe 0.10.18 có wheel ARM64/Python3.12 và PyTorch CPU đúng phiên bản đã chạy trên Pi. Không dùng requirements Windows thay cho manifest này, không cài đè cả opencv-python và opencv-contrib-python khi không cần. Bản OS/máy mới hoàn toàn chưa được nghiệm thu lại; đọc lỗi pip thay vì đổi model để lách lỗi.

Tải model nhận **giọng nói**, không thay GRU:

```bash
mkdir -p .tools
curl -fL --retry 2 -o .tools/zipformer-vi.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-vi-30M-int8-2026-02-09.tar.bz2
backend/.venv-pi/bin/python -c "import tarfile; tarfile.open('.tools/zipformer-vi.tar.bz2').extractall('.tools', filter='data')"

# Không ghi đè cấu hình đã có:
test -f backend/.env.local || cp backend/pi.env.example backend/.env.local
chmod 600 backend/.env.local
nano backend/.env.local
```

Ví dụ không chứa bí mật tại `backend/pi.env.example`. Cần điền riêng token API, tài khoản MQTT, IP Pi cho audio và Gemini key ở **backend**. Không đưa các giá trị này vào Android, ESP giao diện web hoặc Git; ESP chỉ cần cấu hình Wi-Fi/MQTT riêng, không cần Gemini key. Giá trị có ký tự đặc biệt phải đặt trong nháy vì script nguồn Bash file này. Không gửi key/mật khẩu vào chat hoặc ảnh chụp.

Để Android truy cập LAN: đặt `DAKT_BIND_HOST=0.0.0.0`, tạo `DAKT_API_TOKEN` đủ dài và nhập token đó trong Cài đặt Android. Có thể tạo token bằng `backend/.venv-pi/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"` rồi lưu riêng. Launcher từ chối mở LAN nếu token trống. Giữ `DAKT_PREVIEW_API=http://127.0.0.1:8001` trên Pi.

Gemini: `DAKT_AI_PROVIDER=gemini`, điền `GEMINI_API_KEY` trong backend/.env.local; model hiện được khóa ở `gemini-3.1-flash-lite`. Nếu chưa có key thì backend dùng mock có ghi rõ. Không tự bật billing hoặc đổi sang model trả phí. Không bảo đảm hạn mức Free Tier luôn còn; UI hiển thị lỗi khi quota/mạng lỗi.

```bash
bash start_deafy.sh --check
bash scripts/install-deafy-launcher.sh
bash start_deafy.sh
```

## 4. MQTT và ESP32

Broker thật dùng xác thực; kiểm tra bằng `systemctl status mosquitto`. Không đổi broker thật sang anonymous để thử. Cấu hình mẫu/test broker không được dùng cho mạng thật. Nếu Mosquitto chưa chạy, khởi động bằng `sudo systemctl start mosquitto`; launcher cũng giữ hỗ trợ broker user đã có trên Pi hiện tại. Không có broker thì camera/UI vẫn dùng được, IoT/TTS hiển thị lỗi thay vì báo thành công.

Sau reboot 03/11 phát hiện hai bản broker cùng muốn cổng1883. Launcher nay chờ broker hệ thống trước; nếu vẫn chưa có listener và bản broker user cũ tồn tại, chạy nó trong unit riêng `deafy-mqtt.service`. Broker này không bị dừng theo backend. Phiên Pi hiện tại dùng unit user này; `mosquitto.service` hệ thống còn báo failed từ lần tranh cổng, không được tự sửa cấu hình root vì chưa có quyền quản trị. Kiểm tra broker đang dùng bằng `systemctl --user status deafy-mqtt.service --no-pager`, `ss -ltn` và trạng thái MQTT trong UI, không chỉ nhìn một service.

Tài khoản Pi/ESP hiện tại dùng chung credential đã có. File password/ACL của broker dự phòng đã được sao lưu rồi đồng bộ; quyền được giới hạn hai chiều trên bốn topic mode/command/speech/status. Không đổi password của ESP, không flash lại firmware. Chưa reboot lại sau sửa để nghiệm thu thứ tự khởi động; không tự bật thêm autostart hoặc tắt service hệ thống.

**Chỉ cho broker mới chưa có listener/cấu hình làm việc**, không chạy lại trên Pi hiện tại: tạo tài khoản với mật khẩu nhập tương tác, không đưa mật khẩu vào dòng lệnh. Các lệnh này không ghi đè file đã có; nếu file đã tồn tại, phải đọc và đối chiếu cấu hình trước khi tiếp tục.

```bash
sudo test -e /etc/mosquitto/deafy-passwords || sudo mosquitto_passwd -c /etc/mosquitto/deafy-passwords signassist
sudo chown root:mosquitto /etc/mosquitto/deafy-passwords
sudo chmod 640 /etc/mosquitto/deafy-passwords
sudo test -e /etc/mosquitto/conf.d/deafy.conf || printf 'listener 1883 0.0.0.0\nallow_anonymous false\npassword_file /etc/mosquitto/deafy-passwords\n' | sudo tee /etc/mosquitto/conf.d/deafy.conf >/dev/null
sudo systemctl restart mosquitto
```

Điền tài khoản/mật khẩu tương ứng vào backend/.env.local và secrets.h của ESP. LAN MQTT không TLS chỉ dùng trong mạng trình diễn tin cậy; không mở cổng ra Internet. Không có bước nào ở trên được tự áp dụng lên broker hiện tại.

Topic gốc hiện là `signassist/esp32`: `/mode`, `/command`, `/speech`, `/status`. Gói mang request_id, epoch và hạn dùng; backend/ESP bỏ lệnh trùng và phản hồi cũ. ACK chỉ xác nhận đã nhận; DONE là hoàn tất. “Đã nối broker” không chứng minh ESP đang online. UI chỉ báo phản hồi lệnh thực tế, không suy đoán trạng thái relay.

ESP source ở `ESP32_SignAssist/`; cấu hình riêng `include/secrets.h` bị ignore. Giữ GPIO5/6/7 của MAX98357A, nguồn 3V3 và MAX9814 hiện tại. Không flash lại chỉ để khởi chạy ứng dụng. Relay hiện chưa có GPIO được xác nhận (LIGHT_PIN/FAN_PIN=-1); cần xác minh dây/chân trước khi cấu hình và nghiệm thu relay. Đừng coi test ESP mô phỏng là relay thật.

Pi tạo WAV và gửi URL HTTP LAN có ticket ngắn hạn cho ESP. `DAKT_AUDIO_BASE_URL` phải là `http://IP_LAN_PI:8001`, không phải localhost. ESP không thể lấy âm thanh từ localhost của Pi theo nghĩa thiết bị khác. Ưu tiên đặt DHCP reservation trên router để IP Pi ổn định; không tự thay cấu hình router. Khi IP đổi: sửa audio URL, MQTT host trong cấu hình ESP nếu đang dùng IP tĩnh, cấu hình Android và preview Windows. Hiện chưa có cơ chế tự khám phá lại ESP khi Pi đổi IP.

## 5. Chạy thủ công / Windows preview

Trên Pi, dừng service trước khi chạy backend thủ công để tránh hai chủ camera:

```bash
bash stop_deafy.sh
bash start_pi.sh
```

Lệnh này chạy một uvicorn worker và Vite, nạp backend/.env.local. Camera/inference khởi tạo khi bật camera trong UI; launcher start_deafy tự bật camera sau khi API sẵn sàng. Không chạy thêm step6_app.py cùng lúc vì sẽ tranh camera.

Nếu chỉ debug từng tiến trình trên **Pi**, sau khi đã dừng service, có thể mở hai Terminal trong gốc dự án. Không chạy đồng thời các lệnh này với start_pi/start_deafy:

```bash
# Terminal 1: backend chỉ bind loopback cho development cục bộ.
set -a
. ./backend/.env.local
set +a
backend/.venv-pi/bin/python -m uvicorn server:app --app-dir backend --host 127.0.0.1 --port 8001 --workers 1

# Terminal 2: frontend Pi
npm --prefix RaspberryPi_7inch run dev -- --port 5173 --strictPort
```

Chế độ backend loopback này không phục vụ điện thoại/ESP từ LAN; dùng launcher và cấu hình LAN có token khi thử toàn hệ thống. Kiểm tra riêng model không mở camera:

```bash
backend/.venv-pi/bin/python Deafy_AI_share_ver0/step6_app.py --checkpoint Deafy_AI_share_ver0/artifacts/step5/run_20261026T045637Z_ebe324f6/best_model.pth --check-only
```

Trên Windows, cấu hình **riêng trên Windows** `backend/.env.local`: `DAKT_PREVIEW_API=http://IP_LAN_PI:8001` và cùng DAKT_API_TOKEN. Không chép nguyên file cấu hình Windows đè lên Pi.

```powershell
npm --prefix RaspberryPi_7inch ci
npm --prefix Android_App ci
powershell -NoProfile -ExecutionPolicy Bypass -File tools/preview/start-preview.ps1 -Target all
# Khi đổi IP/cấu hình proxy:
powershell -NoProfile -ExecutionPolicy Bypass -File tools/preview/start-preview.ps1 -Target all -Restart
powershell -NoProfile -ExecutionPolicy Bypass -File tools/preview/check-preview.ps1
```

Windows chỉ chạy frontend ở 5173/5174. Không chạy start_backend/uvicorn riêng để cấp AI cho Android. `start_backend.bat` chỉ kiểm tra Pi. APK thật nhập IP LAN/token trong Cài đặt, không dùng localhost. API/WebSocket của preview đi qua proxy có token phía Node, token Gemini/MQTT không vào bundle.

## 6. Log, chẩn đoán và tự khởi động tùy chọn

```bash
hostname -I
ss -ltn | grep -E ':8001|:5173|:1883'
curl -f http://127.0.0.1:8001/api/health
curl -f http://127.0.0.1:5173/api/state
tail -n 80 .tools/deafy-logs/system.log
systemctl --user status signassist-connected.service --no-pager
systemctl status mosquitto --no-pager
lsusb
arecord -l
amixer -c WebCamera sget Mic
```

- 401/WS1008: kiểm tra token và origin; không tắt xác thực/CORS để lách lỗi.
- Không có camera/micro: kiểm tra dây USB/nguồn, lsusb, ALSA. Không tự đổi sang micro MAX9814; nguồn thu chính là WebCamera.
- Chữ chưa hiện: chờ trạng thái Đang nghe, nói câu ngắn rồi im lặng; VAD dừng sau khoảng 0,8 giây im lặng. Có thể sửa câu rồi Xác nhận; không tự gửi AI.
- MQTT nối nhưng không có DONE: kiểm tra ESP, Wi-Fi 2.4GHz, topic/epoch/đồng hồ; không tự gửi lại lệnh có thể đã thực thi.
- Cổng bận: dùng start_deafy để tái sử dụng service, không kill toàn bộ Python/Node. Lỗi được ghi trong log và hộp thoại nếu có desktop.
- Model sai thời lượng: giữ cửa sổ 3 giây theo checkpoint hiện tại; không sửa preprocessing để ép model không tương thích chạy.

**Chưa bật tự khởi động mới.** Service của Pi hiện tại đã enabled từ phiên làm việc trước; launcher giữ nguyên lựa chọn đó. Trên Pi mới, chỉ khi muốn mở cả UI sau đăng nhập:

```bash
mkdir -p "$HOME/.config/autostart"
cp "$(xdg-user-dir DESKTOP)/Deafy AI.desktop" "$HOME/.config/autostart/Deafy AI.desktop"
```

Muốn chỉ backend chạy theo phiên đăng nhập, sau lần chạy launcher đầu tiên có thể dùng `systemctl --user enable signassist-connected.service`. Không chạy các lệnh tùy chọn này nếu không muốn autostart. Chưa kiểm tra cold boot trước đăng nhập; không tự bật linger.

## 7. Development và production

Launcher hiện là chế độ **demo/development** đã chạy thực tế: Vite cục bộ, FastAPI một worker, SQLite và broker dùng chung. Phù hợp trình diễn trong LAN tin cậy. `npm run build` tạo static web assets; chưa triển khai production server. Production cần phục vụ static qua gateway/reverse proxy, HTTPS/WSS có chứng chỉ tin cậy và chính sách vận hành riêng; không đưa backend secret vào static assets. Không tự triển khai production trong lượt này.

Kiểm thử source: `backend/.venv-pi/bin/python -m pytest backend/tests -q`. Bài UI dùng `tools/qa/ui_fixture.py` trên Windows là backend mock tạm, chỉ bind loopback8002, database tạm và xóa biến credential khỏi process; dừng fixture khi thử xong. Xem báo cáo cuối tại `docs/release/TEST_REPORT.md` và hướng dẫn APK tại `docs/setup/android.md`.
# Cập nhật tự tìm Pi khi đổi mạng

Hệ thống đã có DNS-SD để Pi dùng DHCP mà ESP và Android không phụ thuộc IP cố định. Xem quy trình hotspot, cài dependency client Windows, ghép nối một lần và các giới hạn kiểm thử trong [hướng dẫn tự tìm Pi](../setup/pi.md). Phần hướng dẫn IP thủ công bên dưới vẫn dùng được làm dự phòng.

