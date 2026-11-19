import {requestId} from '../api/client.mjs';

export function mountLocation({api,getState,applyState,connected}) {
  const $=id=>document.getElementById(id);let pending=false;
  const manual = $('useManualReference');
  manual.checked = localStorage.getItem('dakt.useManualReference') === 'true';
  manual.onchange = () => localStorage.setItem('dakt.useManualReference', String(manual.checked));
  function render(){
    const shared=getState()?.pi?.location,location=shared?.current;
    const summary=!connected()?'Chưa kết nối Pi':!shared?'Backend cần cập nhật vị trí dùng chung':location
      ? `${location.label || 'Vị trí đã chọn'} · ${location.source==='manual'?'vị trí tham chiếu đã lưu':location.source==='phone'?'thiết bị di động đã cấp quyền':'trình duyệt đã cấp quyền'} · cập nhật ${new Date(location.timestamp).toLocaleString('vi-VN')}${location.accuracy==null?'':` · sai số khoảng ${Math.round(location.accuracy)} m`}`
      :shared.message;
    $('sharedLocationSummary').textContent=summary;
    for(const id of ['shareCurrentLocation','saveManualLocation','clearSharedLocation','searchLocationName']) $(id).disabled=pending||!connected()||!shared;
    $('locationSearchResults').querySelectorAll('button').forEach(button=>button.disabled=pending||!connected());
    $('clearSharedLocation').disabled ||= !shared?.has_saved;
  }
  async function save(value){
    const revision=getState()?.pi?.location?.revision;
    if(revision==null)throw Error('Chưa có kết nối backend hỗ trợ vị trí.');
    applyState(await api('/api/location',{method:'POST',body:JSON.stringify({request_id:requestId(),expected_revision:revision,...value})}));
  }
  async function run(action){
    if(pending||!connected())return;pending=true;render();
    try{await action();}catch(e){$('sharedLocationError').textContent=e.message;}
    finally{pending=false;render();}
  }
  const locate=()=>run(async()=>{
    $('sharedLocationError').textContent='Đang xác định vị trí… Chỉ lấy một lần sau khi bạn cấp quyền.';
    render();
    if(!window.isSecureContext||!navigator.geolocation)throw Error('Mở Sign Assist bằng HTTPS được iPhone tin cậy để chia sẻ GPS.');
    const position=await new Promise((resolve,reject)=>navigator.geolocation.getCurrentPosition(resolve,e=>reject(Error({1:'Bạn chưa cấp quyền vị trí. Có thể bật lại trong Cài đặt Safari hoặc chọn thủ công.',2:'Thiết bị chưa xác định được vị trí. Thử lại hoặc chọn thủ công.',3:'Định vị quá thời gian chờ. Thử lại hoặc chọn thủ công.'}[e.code]||'Không lấy được vị trí.')),{enableHighAccuracy:true,timeout:12000,maximumAge:0}));
    await save({lat:position.coords.latitude,lon:position.coords.longitude,accuracy:position.coords.accuracy,timestamp:position.timestamp,
      source:/iPhone|iPad|Android/i.test(navigator.userAgent)?'phone':'browser',label:$('sharedLocationLabel').value.trim()||'Vị trí thiết bị đã cấp quyền'});
    $('sharedLocationError').textContent='Đã chia sẻ với Pi. Không theo dõi nền; hãy cập nhật khi di chuyển hoặc sau 15 phút.';
  });
  $('shareCurrentLocation').onclick=locate;
  $('sharedLocationLabel').addEventListener('input',()=>$('locationSearchResults').replaceChildren());
  $('searchLocationName').onclick=()=>run(async()=>{
    const name=$('sharedLocationLabel').value.trim();
    if(name.length<3||name.length>160)throw Error('Nhập tên khu vực từ 3 đến 160 ký tự để tra cứu.');
    $('locationSearchResults').replaceChildren();$('sharedLocationError').textContent='Đang tra khu vực…';render();
    const result=await api('/api/location/search',{method:'POST',body:JSON.stringify({name})});
    for(const item of result.items){
      const button=document.createElement('button');button.type='button';button.className='button secondary';button.textContent='Xác nhận: '+item.label;
      button.onclick=()=>run(async()=>{
        await save({...item,source:'manual',accuracy:null,timestamp:Date.now()});
        $('sharedLocationLabel').value=item.label;$('locationSearchResults').replaceChildren();
        $('sharedLocationError').textContent='Đã lưu khu vực bạn xác nhận, nguồn Open-Meteo / GeoNames; không phải GPS. Có thể dùng cho thời tiết/tìm kiếm.';
      });
      $('locationSearchResults').append(button);
    }
    $('sharedLocationError').textContent=result.message;
  });
  $('saveManualLocation').onclick=()=>run(async()=>{
    const lat=$('manualLocationLat').value,lon=$('manualLocationLon').value;
    if(!lat||!lon||!$('manualLocationLat').checkValidity()||!$('manualLocationLon').checkValidity())throw Error('Nhập đủ vĩ độ và kinh độ hợp lệ.');
    await save({lat:Number(lat),lon:Number(lon),accuracy:null,timestamp:Date.now(),source:'manual',label:$('sharedLocationLabel').value.trim()||'Vị trí tham chiếu do bạn chọn'});
    $('sharedLocationError').textContent='Đã lưu vị trí tham chiếu, dùng tối đa 30 ngày; cập nhật khi chuyển khu vực.';
  });
  $('clearSharedLocation').onclick=()=>run(async()=>{
    applyState(await api('/api/location',{method:'DELETE',body:JSON.stringify({request_id:requestId(),expected_revision:getState().pi.location.revision})}));
    $('sharedLocationError').textContent='Đã xóa vị trí chia sẻ và tham chiếu trên Pi. Không tự theo dõi hoặc cấp quyền lại.';
  });
  return {render};
}
