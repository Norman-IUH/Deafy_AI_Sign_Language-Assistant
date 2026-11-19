# Build Android APK của Sign Assist

RC8 đóng gói Model 2 để nhận diện tại chỗ. Build từ source sạch cần export checkpoint được phép phân phối và chuẩn bị tài nguyên MediaPipe theo README. Kết nối Pi dùng cho dịch vụ mạng; camera Android thật vẫn chờ nghiệm thu.

Chạy `npm --prefix Android_App run android:sync` từ gốc repo sau khi cấu hình JDK 21 và SDK 36. Để kiểm tra APK sau build, chạy `python scripts/verify_android_apk.py` từ gốc workspace. Script so khớp asset hiện tại, plugin, credential đang cấu hình và lint; không in giá trị bí mật.

## Project đúng

Ứng dụng hiện là **Vite/React + Capacitor 8**, giữ nguyên native Android/Gradle hiện có. Không dùng Expo/React Native. Mở thư mục `Android_App/android` trong Android Studio; không mở bản `App_Android_APK/android_legacy_20261028` hoặc thư mục Pi.

Đợt này đã build debug và chạy lint thành công. APK:

```text
Android_App/android/app/build/outputs/apk/debug/app-debug.apk
```

Application ID `vn.edu.signassist`, minSdk24 (Android7), target/compileSdk36. Bản build đã kiểm tra bằng JDK21, Gradle8.14.3 và Android Gradle Plugin8.13.0. Không cần đổi phiên bản chỉ vì Android Studio gợi ý mới hơn.

## Chuẩn bị và đồng bộ web

Cài Android Studio từ nguồn chính thức, dùng SDK Manager cài Android SDK Platform36, Build Tools36 và Platform Tools. Chọn Gradle JDK21 trong Settings → Build Tools → Gradle. SDK path là cấu hình **local.properties của từng máy**, không commit đường dẫn máy phát triển. Android Studio thường tự tạo file này. Với Windows, dấu hai chấm trong file Java properties phải escape, ví dụ `sdk.dir=D\:/Android/Sdk`.

Từ gốc workspace Windows:

```powershell
npm --prefix Android_App ci
cd Android_App
npm run android:sync
npm run android:open
```

`android:sync` chạy web build rồi đồng bộ assets/plugin native. Không chạy `cap add android` vì project đã tồn tại. Không chỉnh tay thư mục assets generated để sửa UI; sửa src/shared rồi sync lại.

## Build trong Android Studio

1. Open → chọn `Android_App/android`.
2. Chờ Gradle Sync; chọn Gradle JDK21 và SDK36 nếu IDE hỏi. Không nâng cấp framework tự động trong lúc kiểm tra.
3. Build Variants → chọn `debug`.
4. Build → Generate App Bundles or APKs → Build APKs (tên menu có thể khác nhẹ theo phiên bản Studio).
5. Mở APK tại `app/build/outputs/apk/debug/app-debug.apk`.

Tương đương bằng Terminal trong Android_App/android:

```powershell
.\gradlew.bat assembleDebug lintDebug
```

Nếu Java chưa có trong PATH, đặt JAVA_HOME thành JDK21 cục bộ trước khi chạy; không dùng đường dẫn JDK của người khác. APK debug dùng khóa debug của công cụ Android. Không tạo/thay khóa ký release trong lượt này.

## Cài và kết nối Pi

```powershell
adb devices
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Điện thoại cần bật Developer options/USB debugging và chấp nhận máy tính nếu cài qua ADB. Để cài thủ công, mở `Deafy-v1.0.0-rc7-debug.apk` từ thư mục bàn giao trên Android hoặc cài qua chức năng nhập APK của giả lập. Nếu Android báo xung đột chữ ký, sao lưu câu quan trọng trước khi cân nhắc gỡ bản cũ.

Trên Pi chạy Deafy, xem IP bằng `hostname -I`. Trong app → Cài đặt → Kết nối Raspberry Pi:

- Mã truy cập: DAKT_API_TOKEN từ cấu hình backend Pi.
- Mặc định bật **Tự tìm Raspberry Pi trên Wi-Fi**, để trống địa chỉ và bấm **Lưu và kiểm tra kết nối**. Có thể dùng **Tìm thiết bị Deafy** hoặc **Kết nối lại** từ cùng màn hình.
- Nếu Wi-Fi chặn tìm thiết bị, có thể tắt tự tìm và nhập `http://IP_LAN_PI:8001` từ kết quả `hostname -I` trên Pi.
- Điện thoại và Pi cùng LAN, không bật Wi-Fi client isolation. Pi phải bind LAN, cổng8001 được phép trên mạng đó.

App đã chặn localhost/127.x/::1 cho backend native và hỗ trợ đổi địa chỉ rồi reconnect. Không có IP LAN cố định, Gemini key hay MQTT password được nhúng sẵn trong APK. Bản quét APK đã build không tìm thấy các credential cấu hình hiện tại.

APK xin quyền camera điện thoại khi bấm **Bật camera** và quyền micro khi bắt đầu nghe. MediaPipe và Model 2 chạy trên điện thoại. Trợ lý AI và loa ESP32 cần kết nối Pi. Giọng tiếng Việt trên điện thoại dùng dịch vụ TTS của Android, cần kiểm tra gói giọng trên máy thật.

## Chẩn đoán trên Android

Trong **Giao tiếp**, bật camera và **Hiện đường tay**, cuộn xuống **Chẩn đoán AI** rồi bật **Số thứ tự điểm khớp**. Đưa tay phải vào khung và thực hiện một ký hiệu khoảng 4 giây. Chạm Vietsub nếu xuất hiện, thử lại với camera sau và xoay máy. Chọn **Sao chép báo cáo chẩn đoán** để gửi số liệu. Báo cáo chỉ gồm trạng thái, phiên bản, nhãn dự đoán và số đo, không chứa ảnh, tọa độ GPS hay mã truy cập.

Khi ứng dụng nhận sai, hạ tay sau khi đã có top-3. Chọn đúng ký hiệu thực hiện tại **Nhãn đúng của mẫu vừa làm** rồi bấm **Sao chép mẫu kiểm thử**. Lưu nội dung thành JSON nếu muốn gửi để đối chiếu. Đây là tensor keypoints được chọn chủ động, tách khỏi báo cáo trạng thái và dữ liệu học. Bạn có thể thực hiện cả hai thao tác offline.

Nếu ứng dụng nhầm **tay phải** thành **tay trái**, giữ riêng lòng bàn tay phải hướng vào ống kính và bấm **Hiệu chỉnh tay phải** trong **Chẩn đoán AI**. Sau khi thấy xác nhận, thử từng tay rồi thử hai tay. Hiệu chỉnh riêng cho camera gặp lỗi. Khi camera cung cấp mã thiết bị, app lưu cấu hình cho nguồn đó trên máy; nếu thiếu mã thì hiệu chỉnh có hiệu lực trong lượt mở camera.

Nút **Tay phải bị báo trái?** cũng xuất hiện trực tiếp cạnh camera khi MediaPipe chỉ xác nhận slot trái. Nếu hiệu chỉnh chưa giúp, mở **Chẩn đoán AI → Đổi hướng ảnh nguồn**, giữ nguyên tay phải và quan sát `MediaPipe` cùng `Slot đầu vào`. Bấm lại để quay về hướng ban đầu. Phần `Tensor` cho biết tiến độ 30 vị trí lấy mẫu và lý do đang chờ suy luận. Các bước này chạy offline.

Nếu tiến độ quay về 0, xem **Số lần lấy mẫu lại** và nguyên nhân gần nhất. RC7 bỏ qua frame mất dấu thoáng qua trong giới hạn 200 ms giữa hai frame hợp lệ. Nếu khoảng cách vượt 200 ms, ứng dụng lấy lại mẫu để bảo đảm nhịp đầu vào của Model 2.

**Cài đặt → Thông tin AI** hiển thị phiên bản, nguồn checkpoint, ngày đóng gói và runtime thực tế sau khi bật camera. Mục đối chiếu chỉ báo khớp hash và nhãn sau khi nhận phiên bản đã nạp từ Pi.

Khi build cho một Pi cụ thể, đặt `DAKT_MOBILE_CHECKPOINT_SHA256` bằng hash tin cậy của model Pi trước `npm run android:sync`. Script staging kiểm tra hash ONNX và GRU theo manifest. Chỉ khi đổi checkpoint mới cần chạy exporter với đường dẫn checkpoint và `--expected-sha256`.

Nếu đang cắm ADB, có thể lấy số liệu thiết bị khi camera hoạt động:

```powershell
adb shell dumpsys meminfo vn.edu.signassist
adb shell dumpsys cpuinfo | Select-String 'vn.edu.signassist|webview|sandboxed_process'
```

## HTTP/HTTPS và môi trường

APK đóng gói web assets cục bộ; không trỏ server.url tới Vite. Cấu hình Android hiện cho HTTP LAN/mixed content để truy cập Pi trong mạng thử nghiệm; token HTTP không được mã hóa trên đường truyền. Chỉ dùng LAN tin cậy cho demo. Khi production có HTTPS/WSS hợp lệ, nhập origin HTTPS và kiểm tra lại chính sách cleartext/mixed content; không bỏ kiểm tra chứng chỉ hoặc thêm CORS `*` để chữa lỗi.

Backend cho origin WebView `https://localhost`/`capacitor://localhost` và origin preview hiện có. Token API gửi qua Authorization và frame xác thực WebSocket, không đặt trong URL. Gemini/MQTT credential chỉ ở backend/ESP cấu hình riêng, không được đặt vào capacitor.config.json, www hoặc assets.

## Release và signing

Sau khi nghiệm thu điện thoại, dùng Build → Generate Signed App Bundle / APK → APK, chọn **keystore release của người dùng**, chọn variant release. Nếu chưa có keystore, người dùng tự tạo và quản lý, sao lưu an toàn; không gửi mật khẩu/keystore vào chat hoặc Git. Không dùng debug key phát hành. Tăng versionCode trước bản cập nhật phát hành; giữ applicationId nếu muốn nâng cấp app cũ. Lệnh `assembleRelease` hiện tạo bản chưa ký nếu chưa cấu hình signing; không coi nó là bản sẵn sàng phát hành.

Ký release và nghiệm thu điện thoại thật đang chờ xác nhận. Lint debug còn cảnh báo không chặn build; xem `Android_App/android/app/build/reports/lint-results-debug.html`.
# Cập nhật Android tự tìm Pi

Bản debug hiện có plugin NSD `PiDiscovery`. Kết nối điện thoại Android cùng Wi-Fi deafy, giữ **Tự tìm Raspberry Pi trên Wi-Fi** bật trong Cài đặt và nhập mã truy cập Pi một lần. Xem [hướng dẫn discovery và kết quả nghiệm thu](../setup/pi.md). iPhone không cài được APK; Android NSD trên điện thoại thật hiện chưa được kiểm chứng.

