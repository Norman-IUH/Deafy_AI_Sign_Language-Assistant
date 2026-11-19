# Mã dùng chung cho hai giao diện

- `api/client.mjs`: REST, timeout 8 giây, một lần retry với cùng body/request ID và máy chủ ban đầu. HTTP lỗi không retry.
- `websocket/protocol.mjs`: URL WS/WSS và kiểm tra snapshot trước khi chuyển cho UI. Vòng đời reconnect vẫn thuộc mỗi UI.
- `styles/tokens.css`: màu light/dark và cỡ chữ giao tiếp, font Be Vietnam Pro do từng frontend bundle cục bộ.
- `ui/SignAssist.jsx`: lớp giao diện React dùng chung cho Pi và mobile. Mount một lần trước controller; giữ nguyên ID để các bộ xử lý hiện có tiếp tục quản lý DOM. Không re-render root khi nhận snapshot. React/react-dom được cài trong từng frontend và dedupe qua Vite.
- `transport.test.mjs`: chạy `node --test shared/transport.test.mjs` từ workspace.

Hai Vite config cho phép import từ workspace; build web tự bundle các module này. Khi di chuyển source cần giữ cả shared và frontend. Không có backend, database hoặc AI chạy tại đây. Dự án dùng JavaScript, chưa cần tạo thư mục types rỗng hoặc thêm TypeScript.
