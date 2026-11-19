import React from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';

const Icon = ({ name }) => <span data-icon={name} aria-hidden="true" />;

function Header() {
  return <header className="app-header">
    <a className="brand" href="#home"><span className="brand-icon"><Icon name="chat" /></span><span>Sign Assist</span></a>
    <nav aria-label="Điều hướng chính">
      {[['home', 'chat', 'Giao tiếp'], ['history', 'history', 'Lịch sử'], ['settings', 'settings', 'Cài đặt']].map(([page, icon, label]) =>
        <a key={page} href={'#' + page} data-page={page} aria-current={page === 'home' ? 'page' : undefined}><Icon name={icon} /><span>{label}</span></a>)}
    </nav>
    <div className="connection" id="connection" role="status"><span className="status-dot" /><span id="connectionText">Đang kết nối…</span></div>
  </header>;
}

function Microphone() {
  return <button id="listenBtn" className="button secondary" aria-pressed="false"><Icon name="mic" /><span>Bắt đầu nghe</span></button>;
}

function Speech({ mobile = false, pi = false }) {
  return <section className="speech-panel" aria-labelledby="speechHeading">
    <div className="speech-label"><Icon name="mic" /><div><h2 id="speechHeading">Người đối diện</h2><span id="speechHint" role="status" /></div><span className="speech-mode">Lời nói thành chữ</span></div>
    <p id="transcript" aria-live="polite" hidden={pi}>Chưa có lời nói</p>
    <textarea id="micTranscript" aria-label="Lời nói nhận dạng, có thể chỉnh sửa" placeholder="Lời nói từ micro camera sẽ hiện ở đây…" maxLength="2000" hidden={!pi} /><button id="confirmSpeech" className="button secondary" disabled hidden={!pi}>Xác nhận</button><button id="useSpeechDraft" className="button secondary" disabled>Dùng làm câu của bạn</button>
    {!mobile && <Microphone />}
  </section>;
}

function Camera({ pi }) {
  const subtitle = <button id="cameraSubtitle" type="button" className="camera-subtitle" hidden disabled>
    <span aria-live="polite">Chờ ký hiệu mới</span><small />
  </button>;
  const toggle = <button id="cameraBtn" className="camera-toggle"><Icon name="camera" /><span>Bật camera{pi ? '' : ' Pi'}</span></button>;
  const diagnostics = <div className="camera-diagnostics"><button id="landmarksBtn" className="camera-diagnostics-toggle" aria-pressed="false">Điểm tay &amp; %</button><output id="recognitionTiming" hidden>Đang chờ camera</output><output id="recognitionScore" hidden title="Điểm của mô hình, chưa phải xác suất chính xác đã hiệu chuẩn">Chưa có dự đoán</output></div>;
  return <section className="camera-panel" aria-label="Camera và nhận diện ký hiệu">
    {!pi && <label className="checkbox-row preview-choice"><input id="mobileCameraPreview" type="checkbox" defaultChecked aria-label="Xem camera Raspberry Pi" /><span>Camera Pi</span></label>}
    <div className="camera-view">
      {pi && <div className="immersive-toolbar"><div className="immersive-brand"><strong>SignAssist<span> / LIVE</span></strong><span id="immersiveStatus" role="status">Camera chưa bật</span></div><button id="exitImmersive" className="button secondary"><Icon name="expand" />Thu nhỏ</button></div>}
      <img id="cameraImage" alt="Hình trực tiếp từ camera máy chủ" hidden />
      <div className="camera-empty" id="cameraEmpty"><Icon name="camera" /><strong id="cameraEmptyTitle">Camera chưa bật</strong><p id="cameraEmptyHint" /></div>
      <span className="camera-source"><span className="status-dot" />Camera {pi ? 'nhận diện ký hiệu' : 'Pi'}</span>
      {!pi && <>{diagnostics}{toggle}</>}
    </div>
    <div className="recognition-result"><Icon name="hands" /><div><span className="field-caption">{pi ? 'Nhận diện ký hiệu' : 'Ký hiệu từ Pi'}</span><p id="prediction" role="status">Đang kiểm tra mô hình…</p></div><span className="ai-indicator" id="aiIndicator">Chưa sẵn sàng</span></div>
    {pi && <><div className="camera-course-tools">
      {diagnostics}{toggle}
      <button className="icon-button camera-expand" id="fullscreenBtn" aria-label="Phóng to camera" aria-expanded="false" title="Phóng to camera"><Icon name="expand" /></button>
    </div><div id="learningFeedback" className="learning-feedback" hidden>
      <p id="learningPrediction" role="status" />
      <button type="button" className="button" id="learningCorrect">Đúng · Lưu mẫu</button>
      <button type="button" className="button" id="learningWrong">Sai · Sửa nhãn</button>
      <button type="button" className="icon-button" id="learningDismiss" aria-label="Ẩn mẫu này"><Icon name="close" /></button>
    </div>
    <dialog id="learningCorrection" aria-labelledby="learningCorrectionTitle">
      <h2 id="learningCorrectionTitle">Sửa nhãn ký hiệu</h2>
      <p className="helper" id="learningFrozen"></p>
      <div className="learning-dialog-content">
        <label htmlFor="learningLabel">Chọn nhãn đúng</label>
        <select id="learningLabel" />
        <div className="speaker-actions">
          <button type="button" className="button primary" id="learningSave">Lưu mẫu đã sửa</button>
          <button type="button" className="button secondary" id="learningCancel">Hủy</button>
        </div>
      </div>
      <p className="helper" id="learningNotice" role="status" />
    </dialog></>}
    {pi ? <div className="pi-caption-row">{subtitle}
      <div className="pi-sign-controls" role="group" aria-label="Cách ghép ký hiệu">
        <select id="piSignMode" aria-label="Chế độ nhận diện"><option value="single">Từng ký hiệu</option><option value="continuous">Ghép liên tục</option></select>
        <button type="button" id="piSignPause" hidden>Tạm dừng</button>
        <button type="button" id="piSignFinish" hidden>Kết thúc</button>
        <button type="button" id="piSignUndo" hidden title="Xóa ký hiệu vừa thêm">Xóa cuối</button>
      </div>
    </div> : subtitle}
  </section>;
}

function RecognitionTools() {
  return <details id="signSuggestions" className="sign-suggestions">
    <summary id="signSuggestionToggle">Sửa nhận diện</summary>
    <div className="sign-suggestion-content">
      <p id="signCandidateHeading" className="helper" />
      <label htmlFor="signSearch">Chọn ký hiệu trong bộ nhãn hiện có</label>
      <input id="signSearch" type="search" placeholder="Tìm ký hiệu…" autoComplete="off" maxLength="100" />
      <label htmlFor="signEditAction">Thao tác với ký hiệu</label>
      <select id="signEditAction"><option value="append">Thêm ký hiệu đã chọn</option><option value="replace_last">Thay ký hiệu cuối đã chọn</option></select>
      <div id="signChoices" className="sign-choices" role="group" aria-label="Gợi ý từ ký hiệu" />
      <button id="removeLastSign" className="button secondary" disabled>Xóa ký hiệu cuối đã chọn</button>
      <p id="signSuggestionHint" role="status">Chọn từ đúng trước khi ghép câu hoặc phát loa.</p>
    </div>
  </details>;
}

function AssistantTask() {
  return <div className="assistant-task">
    <label htmlFor="assistantTask">Chọn tác vụ AI</label>
    <select id="assistantTask"><option value="auto">Tự động phân loại</option><option value="rewrite">Ghép câu</option><option value="question">Hỏi AI</option><option value="search">Tìm địa điểm</option><option value="weather">Xem thời tiết</option></select>
  </div>;
}

function AssistantTools({ showTask = true }) {
  return <section className="assistant-tools" aria-label="Tác vụ trợ lý AI">
    <p id="assistantProvider" className="helper" role="status" />
    <p id="activeLocation" className="helper" role="status" />
    <section id="weatherResult" className="weather-result" aria-label="Kết quả thời tiết" hidden />
    <p id="placesStatus" role="status" /><p id="osmAttribution" className="helper" hidden><a id="geoapifyAttribution" href="https://www.geoapify.com/" target="_blank" rel="noopener noreferrer" hidden>Geoapify · </a><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a></p><div id="placesResults" />
    {showTask && <AssistantTask />}
    <p id="assistantOriginal" /><p id="assistantProposal" />
    <div className="assistant-actions"><button id="useAIProposal" className="button secondary" disabled>Dùng câu gợi ý</button><button id="editAISentence" className="button secondary">Chỉnh sửa câu</button><button id="readAIResult" className="button secondary" disabled>Đọc kết quả qua ESP32</button></div>
    <p id="readAIHint" className="helper" role="status" />
    <a id="mapsFallback" className="button secondary" target="_blank" rel="noopener noreferrer" hidden>Tìm trực tiếp trên Google Maps (ngoài ứng dụng)</a>
  </section>;
}

function Composer({ pi }) {
  const actions = <div className="compose-bottom"><div className="primary-actions">{pi ? <><button id="askBtn" className="button primary" hidden><Icon name="send" /><span id="askLabel">Gửi</span></button><button id="speakBtn" className="button secondary" aria-label="Phát thành tiếng qua ESP32" title="Phát thành tiếng qua ESP32"><Icon name="volume" /><span id="speakLabel">Phát qua ESP32</span></button></> : <><Microphone /><button id="speakBtn" className="button primary"><Icon name="volume" /><span id="speakLabel">Phát thành tiếng</span></button><button id="mobileAskBtn" className="button primary mobile-ai-send" aria-label="Gửi câu hỏi đến AI trên Pi" hidden><span id="mobileAskLabel">Gửi</span></button></>}</div><span className="audio-note" id="speakingStatus" role="status">Âm thanh qua ESP32</span></div>;
  return <section className="compose-panel" aria-labelledby="composeHeading">
    <div className="panel-heading"><h2 id="composeHeading"><Icon name="chat" />Câu của bạn</h2><span className="subtle" id="syncStatus" role="status">Đồng bộ qua máy chủ</span></div>
    <label className="sr-only" htmlFor="sentenceInput">Nhập câu muốn chia sẻ</label>
    {pi ? <div className="sentence-field"><textarea id="sentenceInput" maxLength="2000" placeholder="Bạn muốn nói điều gì?" spellCheck="false" /><button id="clearDraftBtn" className="icon-button clear-draft" aria-label="Xóa toàn bộ bản nháp" title="Xóa toàn bộ bản nháp" disabled><Icon name="close" /></button></div>
      : <textarea id="sentenceInput" maxLength="2000" placeholder="Bạn muốn nói điều gì?" spellCheck="false" />}
    {pi && actions}
    {pi && <><p id="piModeHint" className="pi-mode-hint" role="status" /><RecognitionTools /></>}
    <details className="editing-tools"><summary aria-label="Mở công cụ chỉnh sửa câu">Sửa câu</summary><div className="edit-actions">
      <button id="spaceBtn" className="button quiet" aria-label="Thêm dấu cách" title="Thêm dấu cách">{pi ? 'Dấu cách' : 'Cách'}</button>
      <button id="backspaceBtn" className="button quiet icon-edit" aria-label="Xóa ký tự cuối" title="Xóa ký tự cuối"><Icon name="backspace" /></button>
      <button id="clearBtn" className="button quiet danger icon-edit" aria-label="Xóa hết câu" title="Xóa hết câu"><Icon name="trash" /></button>
      <button id="applyBtn" className="button secondary" aria-label="Cập nhật câu" title="Cập nhật câu trên các thiết bị"><Icon name="sync" /><span>Cập nhật</span></button>
      <button id="saveBtn" className="button quiet" aria-label="Lưu cuộc trò chuyện" title="Lưu cuộc trò chuyện"><Icon name="bookmark" /><span>Lưu</span></button>
    </div></details>
    {!pi && actions}
    {pi && <><details id="piAnswerPanel" className="pi-answer" aria-label="Câu trả lời AI" hidden>
        <summary id="piAnswerToggle"><Icon name="history" /><span id="piAnswerToggleLabel">Trợ lý AI</span></summary>
        <div className="pi-answer-drawer"><div className="pi-answer-controls"><strong>Trợ lý AI</strong><button id="piAnswerScrollUp" className="icon-button" aria-label="Cuộn trợ lý lên">↑</button><button id="piAnswerScrollDown" className="icon-button" aria-label="Cuộn trợ lý xuống">↓</button><button id="closePiAnswer" className="button secondary">Đóng</button></div>
        <AssistantTask />
        <div className="pi-answer-content" tabIndex="0" role="region" aria-labelledby="piAnswerHeading">
        <h3 id="piAnswerHeading">Câu trả lời AI</h3><p id="piQuestion" /><div id="piAnswer" />
        <AssistantTools showTask={false} />
        <p id="piAIStatus" role="status" /><p id="piSpeechStatus" role="status" />
        </div></div>
      </details><p id="piRequestStatus" className="immersive-request-status" role="status" />
    </>}
  </section>;
}

function Conversation({ pi }) {
  return <section id="page-home" className="page home-page" aria-label="Giao tiếp">
    <div className="home-heading"><h1>Cuộc trò chuyện</h1>{!pi && <button className="icon-button" id="fullscreenBtn" aria-label="Bật toàn màn hình" title="Toàn màn hình"><Icon name="expand" /></button>}</div>
    {!pi && <p hidden id="platformNotice" className="platform-notice" />}
    {pi && <div className="pi-mode-bar" hidden><span id="piModeStatus" role="status">Giao tiếp AI</span></div>}
    {pi ? <div className="communication-grid"><Camera pi /><Composer pi /><Speech pi /></div> : <div className="mobile-conversation">
      <section className="mobile-pi-controls" aria-label="Chế độ dùng chung với Pi">
        <div className="mobile-mode-buttons"><span id="mobilePiStatus" role="status">Đang kết nối Pi…</span></div>
        <details id="mobileAIResult"><summary>Trợ lý AI · Ghép câu, tìm kiếm, sửa ký hiệu</summary><div className="mobile-ai-content"><AssistantTools /><RecognitionTools /><p id="mobileAIQuestion" /><p id="mobileAIAnswer" /><p id="mobileTransport" role="status" /></div></details>
      </section>
      <div className="conversation-timeline" aria-label="Dòng hội thoại" tabIndex="0">
        <div className="conversation-start"><h2>Bắt đầu cuộc trò chuyện</h2><p>Chạm micro để nhận lời nói, hoặc nhập điều bạn muốn chia sẻ.</p></div><div id="timelineHistory" /><Speech mobile /><div id="timelineOutgoing" />
      </div>
      <Camera pi={false} /><Composer pi={false} />
    </div>}
  </section>;
}

function History() { return <section id="page-history" className="page content-page" aria-labelledby="historyHeading" hidden>
        <div className="page-title"><div><h1 id="historyHeading">Lịch sử</h1></div><button id="refreshHistory" className="button secondary"><span data-icon="sync"></span>Làm mới</button></div>
        <div className="search-field"><span data-icon="search"></span><label className="sr-only" htmlFor="historySearch">Tìm trong lịch sử</label><input id="historySearch" type="search" maxLength="200" placeholder="Tìm nội dung cuộc trò chuyện…" /></div>
        <p id="historyStatus" className="subtle" role="status"></p><div id="historyList" className="history-list"></div><button id="moreHistory" className="button secondary" hidden>Xem thêm</button>
      </section>; }
function LocationPanel(){return <section className="settings-section" aria-label="Vị trí dùng chung với Pi"><h2>Vị trí của tôi</h2>
  <p id="sharedLocationSummary" className="helper" role="status">Chưa có vị trí được chia sẻ</p>
  <label htmlFor="sharedLocationLabel">Tên khu vực do bạn chọn</label><input id="sharedLocationLabel" maxLength="200" placeholder="Ví dụ: khu vực trường của bạn" />
  <button id="searchLocationName" className="button secondary">Tìm khu vực theo tên</button><p className="helper">Tra tên quận/thành phố qua Open-Meteo / GeoNames. Bạn xác nhận kết quả trước khi lưu; không phải vị trí GPS.</p><div id="locationSearchResults" className="location-results" role="group" aria-label="Chọn vị trí tham chiếu" />
  <button id="shareCurrentLocation" className="button primary">Sử dụng / cập nhật vị trí hiện tại</button>
  <p className="helper">Chia sẻ một lần với Pi và các giao diện đã ghép nối; không theo dõi nền. GPS hiệu lực 15 phút, sai số tối đa 500 m. HTTPS phải được thiết bị tin cậy.</p>
  <details><summary>Vị trí nâng cao</summary><label className="checkbox-row"><input id="useManualReference" type="checkbox" />Dùng vị trí tham chiếu thay GPS cho tìm kiếm và thời tiết</label><div className="location-coordinates"><label>Vĩ độ<input id="manualLocationLat" type="number" min="-90" max="90" step="any" /></label><label>Kinh độ<input id="manualLocationLon" type="number" min="-180" max="180" step="any" /></label></div><button id="saveManualLocation" className="button secondary">Lưu vị trí tham chiếu</button></details>
  <button id="clearSharedLocation" className="button secondary">Ngừng chia sẻ / xóa vị trí đã lưu</button><p id="sharedLocationError" className="helper" role="status" />
</section>;}
function Settings({ pi }) { return <section id="page-settings" className="page content-page" aria-labelledby="settingsHeading" hidden>
        <div className="page-title"><div><h1 id="settingsHeading">Cài đặt</h1></div></div>
        <div className="settings-grid">
          {pi && <section className="settings-section" id="learningSettings" hidden>
            <h2>AI học từ người dùng</h2>
            <label className="checkbox-row"><input type="checkbox" id="learningEnabled" />Bắt đầu phiên thu mẫu</label>
            <p className="helper">Chỉ lưu điểm bàn tay khi bạn xác nhận. Dữ liệu nằm trên Pi và có thể xuất để huấn luyện trên laptop.</p>
            <p className="helper" id="learningModel" />
            <div className="speaker-actions">
              <button type="button" className="button secondary" id="learningRefresh">Xem kho mẫu</button>
              <button type="button" className="button secondary" id="learningExport">Xuất mẫu đã duyệt</button>
              <button type="button" className="button secondary" id="learningBackup">Sao lưu toàn bộ mẫu</button>
            </div>
            <p className="helper" id="learningSettingsNotice" role="status" />
            <p className="helper" id="learningCounts" />
            <details id="courseTraining">
              <summary>Huấn luyện trên laptop</summary>
              <p className="helper" id="trainingData" />
              <details><summary>Mẫu đã duyệt theo ký hiệu</summary><ul id="trainingCoverage" /></details>
              <p id="trainingJob" role="status" />
              <progress id="trainingProgress" aria-label="Số vòng huấn luyện đã xong" hidden />
              <div className="speaker-actions">
                <button className="button secondary" type="button" id="trainingPrepare" disabled>Chuẩn bị huấn luyện</button>
                <button className="button primary" type="button" id="trainingStart" disabled>Bắt đầu huấn luyện</button>
                <button className="button secondary" type="button" id="trainingDownload" disabled>Tải gói dữ liệu</button>
                <button className="button secondary" type="button" id="trainingReset" hidden>Đặt lại lượt</button>
              </div>
              <label htmlFor="trainingImport">Nhập gói model ZIP</label>
              <input id="trainingImport" type="file" accept=".zip,application/zip" disabled />
              <label htmlFor="trainingVersion">Phiên bản model</label>
              <select id="trainingVersion" disabled />
              <div className="speaker-actions">
                <button className="button secondary" type="button" id="trainingEvaluation" disabled>Kết quả đánh giá</button>
                <button className="button secondary" type="button" id="trainingCheck" disabled>Kiểm tra trên Pi</button>
                <button className="button primary" type="button" id="trainingActivate" disabled>Áp dụng model mới</button>
                <button className="button secondary" type="button" id="trainingRollback" disabled>Khôi phục model cũ</button>
              </div>
              <p className="helper" id="trainingNotice" role="status" />
              <div id="trainingReport" hidden />
            </details>
            <ul id="learningItems" />
            <div className="speaker-actions" id="learningPages" hidden>
              <button type="button" className="button secondary" id="learningPrevious">Trang trước</button>
              <button type="button" className="button secondary" id="learningNext">Trang sau</button>
            </div>
          </section>}
          <LocationPanel />
          <section className="settings-section"><h2>Kết nối Raspberry Pi</h2><form id="connectionForm"><label htmlFor="serverUrl">Địa chỉ máy chủ</label><input id="serverUrl" type="url" placeholder="http://raspberrypi.local:8001" aria-describedby="serverHelp" /><p id="serverHelp" className="helper">Dùng IP Wi-Fi hoặc hostname của Pi. Để trống khi web chạy trực tiếp trên Pi.</p><label htmlFor="apiToken">Mã truy cập <span className="subtle">(nếu máy chủ yêu cầu)</span></label><input id="apiToken" type="password" autoComplete="off" /><button type="submit" className="button primary"><span data-icon="sync"></span>Lưu và kiểm tra kết nối</button><p id="connectionResult" role="status" className="helper"></p></form></section>
          <section className="settings-section" id="speakerControls">
            <h2>Điều khiển âm thanh</h2>
            <fieldset disabled>
              <legend className="speaker-legend">Loa ESP32</legend>
              <label htmlFor="speakerVolume">Âm lượng <output id="speakerVolumeValue">60%</output></label>
              <div className="speaker-volume">
                <button type="button" id="speakerLower" aria-label="Giảm âm lượng 5%">−</button>
                <input id="speakerVolume" type="range" min="0" max="100" step="1" defaultValue="60" />
                <button type="button" id="speakerRaise" aria-label="Tăng âm lượng 5%">+</button>
              </div>
              <label htmlFor="speakerGain">Gain kỹ thuật số <output id="speakerGainValue">0 dB</output></label>
              <input id="speakerGain" type="range" min="-12" max="6" step="1" defaultValue="0" />
              <div className="speaker-actions">
                <button type="button" id="speakerMute">Tắt tiếng</button>
                <button type="button" id="speakerReset">Mặc định</button>
              </div>
            </fieldset>
            <fieldset id="voiceControls" hidden disabled>
              <legend className="speaker-legend">Giọng nói AI</legend>
              <label htmlFor="speakerVoice">Chọn giọng tiếng Việt</label>
              <select id="speakerVoice"></select>
              <label htmlFor="speakerSpeed">Tốc độ đọc <output id="speakerSpeedValue">1.00×</output></label>
              <input id="speakerSpeed" type="range" min="80" max="120" step="5" defaultValue="100" />
              <div className="speaker-actions">
                <button type="button" id="speakerPreview">Nghe thử</button>
                <button type="button" id="speakerSaveVoice">Lưu giọng</button>
                <button type="button" id="speakerResetVoice">Mặc định</button>
              </div>
              <p className="helper">Nghe thử Aoede hoặc Kore trước khi lưu. Tốc độ Gemini là mức đề nghị.</p>
              <p className="helper" id="speakerSavedVoice"></p>
              <p className="helper" id="speakerActualVoice"></p>
              <div id="speakerOfflineControls" hidden>
                <p className="helper" id="speakerTtsAvailability"></p>
                <label className="checkbox-row"><input id="speakerAllowOffline" type="checkbox" />Cho phép giọng ngoại tuyến khi Gemini lỗi</label>
                <div className="speaker-actions">
                  <button type="button" id="speakerTestTone">Kiểm tra loa</button>
                  <button type="button" id="speakerTestOffline">Nghe thử giọng ngoại tuyến</button>
                </div>
              </div>
              <p className="helper" id="speakerVoiceNotice" role="status"></p>
            </fieldset>
            <p className="helper">Mức đã lưu áp dụng từ lượt phát tiếp theo. Gain 0 dB giữ nguyên mức tín hiệu.</p>
            <p className="helper" id="speakerNotice" role="status"></p>
          </section>
          <section className="settings-section"><h2>Hiển thị & giọng nói</h2><label htmlFor="fontSize">Cỡ chữ giao tiếp</label><select id="fontSize"><option value="normal">Tiêu chuẩn</option><option value="large">Lớn</option><option value="extra">Rất lớn</option></select><label htmlFor="theme">Giao diện</label><select id="theme"><option value="light">Sáng</option><option value="dark">Tối</option><option value="system">Theo thiết bị</option></select><label className="checkbox-row"><input id="ttsEnabled" type="checkbox" />Cho phép đọc văn bản thành tiếng</label><p className="helper">Giọng nói tiếng Việt được tạo trên Pi và phát qua ESP32. Câu gợi ý chỉ phát khi bạn xác nhận. Kết quả tìm địa điểm thật được đọc một lần sau khi bạn bấm Tìm kiếm.</p></section>
          <section className="settings-section status-section"><h2>Thiết bị của bạn</h2><dl><div><dt>Máy chủ</dt><dd id="serverStatus">Đang kiểm tra</dd></div><div><dt>Camera</dt><dd id="cameraStatus">Chưa bật</dd></div><div><dt>Micro Pi</dt><dd id="microphoneStatus">Chưa kiểm tra</dd></div><div><dt>Nhận diện ký hiệu</dt><dd id="modelStatus">Chưa có mô hình</dd></div><div><dt>MQTT</dt><dd id="mqttStatus">Chưa kiểm tra</dd></div><div><dt>ESP32</dt><dd id="espStatus">Chưa có phản hồi</dd></div><div hidden><dt>Phát loa</dt><dd id="smartHomeStatus">Chưa có phản hồi</dd></div>{!pi && <div><dt>AI</dt><dd id="mobileAIStatus">Đang kiểm tra backend</dd></div>}</dl></section>
        </div>
      </section>; }

function SignAssist({ pi }) {
  return <><div className="app-shell"><Header /><div id="errorBanner" className="error-banner" role="alert" hidden />
    <main><Conversation pi={pi} /><History /><Settings pi={pi} /></main>
    <footer className="sr-only"><span id="footerStatus">Dữ liệu được lưu trên máy chủ của bạn.</span></footer>
  </div><div id="toast" role="status" className="toast" hidden /><dialog id="historyDialog"><div className="dialog-heading"><h2>Chi tiết cuộc trò chuyện</h2><button id="closeDialog" className="icon-button" aria-label="Đóng chi tiết"><span data-icon="close"></span></button></div><p id="detailTime" className="subtle"></p><p id="detailText" className="detail-text"></p><p id="detailTranscript" className="detail-text"></p></dialog></>;
}

export function mountSignAssist(device) {
  document.documentElement.dataset.device = device;
  // shortcut: mount once; existing controllers own live DOM until a separate state migration is requested.
  flushSync(() => createRoot(document.getElementById('root')).render(<SignAssist pi={device === 'pi'} />));
  if (device === 'pi') {
    const compact = matchMedia('(max-height: 520px)');
    const adapt = () => { document.querySelector('.editing-tools').open = !compact.matches; };
    adapt(); compact.addEventListener('change', adapt);
  }
}

