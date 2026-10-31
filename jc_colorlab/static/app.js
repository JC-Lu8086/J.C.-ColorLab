'use strict';
const $=id=>document.getElementById(id), token=document.querySelector('meta[name="lab-token"]').content;
let state,mode='calibrate',view='source',uploadRole='source',bitmap=null,selected=-1,excluded=new Set(),manualCorners=null,dragging=false,dirty=false,toastTimer,objectURL;
const canvas=$('canvas'),ctx=canvas.getContext('2d');
const spaceNames={'srgb':'sRGB','adobe-rgb':'Adobe RGB (1998)','display-p3':'Display P3','prophoto-rgb':'ProPhoto RGB','acescg':'ACEScg'};
function chartQuery(){return 'levels='+state.levels+'&target_space='+state.target_space;}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,9000);}
async function api(path,options={}){const headers={'X-Lab-Token':token,...options.headers};if(options.body&&!(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}const r=await fetch('/api/'+path,{...options,headers});if(!r.ok){let e;try{e=await r.json();}catch{e={error:r.statusText};}throw Error(e.error||'处理失败');}return r;}
async function job(label,fn){$('busy-text').textContent=label;$('busy').hidden=false;try{return await fn();}catch(e){toast(e.message);return null;}finally{if($('busy'))$('busy').hidden=true;}}
async function refresh(){state=await(await api('state')).json();renderState();await loadView();}
function activeRole(){return view==='after'?(state.images.test&&mode==='apply'?'test':'source'):view;}
function isEditable(){return view!=='after'&&view!=='test'&&Boolean(state?.images[view]);}
function hasModel(){return state?.has_model&&!dirty&&(mode==='apply'||!state.report?.mode||state.report.mode===mode);}
function patch(){return state?.manifest.patches[selected];}
function renderState(){
 $('density').value=String(state.levels);$('target-space').value=state.target_space;$('working-space').value=state.working_space;$('working-badge').textContent=spaceNames[state.working_space];$('space-note').textContent=(state.target_space==='srgb'?'色卡是 sRGB 参考。':'色卡要求屏幕覆盖 '+spaceNames[state.target_space]+'；请选择有效显示 ICC。')+(state.working_space==='acescg'?' ACEScg 当前仅支持线性 0–1，不包含 HDR / ACES 显示变换。':state.working_space!==state.target_space?' 较大的工作色域不会扩展色卡的校准覆盖。':' 预览统一转换到 sRGB，导出保留工作色域。');if(state.manifest.working_gamut_excluded_count)$('space-note').textContent+=` ${state.manifest.working_gamut_excluded_count} 个参考色超出工作范围，校色时会自动排除。`;$('export-space-note').textContent='CUBE / TIFF：'+spaceNames[state.working_space]+(state.working_space==='acescg'?'。XMP 转换到 sRGB，超出 sRGB 的颜色会裁切；保留宽色域请用 CUBE。':'。XMP：对应原色的 32³ LUT，适用于已显影图像。');$('patch-count').textContent=`${state.manifest.patch_count.toLocaleString()} 个数字参考色`;
 for(const role of ['source','target','test']){$(role+'-name').textContent=state.images[role]?.name||(role==='source'?'选择 RAW / TIFF / PNG / JPG':role==='target'?'选择风格 JPG':'选择应用照片');}
 $('target-section').hidden=mode!=='style';$('target-tab').hidden=mode!=='style';$('test-section').hidden=mode!=='apply';$('test-tab').hidden=mode!=='apply';$('fit').hidden=mode==='apply';$('fit-step').parentElement.hidden=mode==='apply';$('fit-note').hidden=mode==='apply';
 $('source-label').textContent=mode==='style'?'导入基准色卡照片':'导入色卡照片';
 $('source-help').textContent=mode==='style'?'固定显影的基准照片，与风格 JPG 配对':'相机 JPG，或固定流程显影的 RAW / TIFF';
 $('fit').firstChild.textContent=mode==='style'?'提取风格映射 ':'生成校色映射 ';
 $('fit-step').textContent=mode==='style'?'3':'2';
 $('after-tab').disabled=!hasModel();
 for(const b of document.querySelectorAll('[data-export]'))b.disabled=!hasModel()||(b.dataset.export==='tiff'&&!state.images[mode==='apply'?'test':'source']);
 $('export-baseline').disabled=!state.images[mode==='apply'?'test':'source'];
 $('fit').disabled=!state.images.source?.points||(mode==='style'&&!state.images.target?.points);
 const r=state.report,m=r?.model;
 $('metric-train').textContent=hasModel()&&m?.training_after?m.training_after.mean.toFixed(2):'—';
 $('metric-validation').textContent=hasModel()&&m?.validation?.after?m.validation.after.mean.toFixed(2):'—';
 $('result-status').textContent=dirty?'待重新拟合':hasModel()?(r?.mode==='style'?'风格映射':'校色映射'):'等待拟合';
 $('result-caption').textContent=hasModel()?`使用 ${r?.used_patches??m?.sample_count??'—'} 个色块。留出 ${m?.validation?.count??'—'} 个色块验证；这些误差只反映本次图像与数字参考的匹配。`:'训练误差与留出误差分开报告，避免把拟合结果当成真实精度。';
 const warnings=hasModel()?[...(m?.warnings||[]),...(r?.source_sampling?.warnings||[]),...(r?.target_sampling?.warnings||[])]:[];
 for(const role of ['source',...(mode==='style'?['target']:[])]){const im=state.images[role];if(im)warnings.push(...(im.warnings||[]),...(im.detection?.warnings||[]));}
 $('warnings').textContent=[...new Set(warnings)].join(' · ');
 $('density-note').textContent=state.levels===17?'4,978 色仅供实验；15 英寸 4K 上色块很小，容易受 JPG 压缩、失焦和摩尔纹影响。建议改用 376 色。':state.levels===9?'762 色要求清晰的高质量照片；JPG 仍优先推荐 376 色。避免反光、摩尔纹、失焦与过曝。':'15 英寸 4K 建议使用 376 色；JPG 使用最高画质。相近色分散排列，黑边隔离，只取中央区域；灰条用于白平衡取样。';
 updateSelection();
}
async function loadView(){
 const role=activeRole(),entry=state.images[role];
 let blob;if(entry){blob=await(await api('image/'+role+(view==='after'?'?after=1':''))).blob();}else{blob=await(await fetch('/chart.png?'+chartQuery())).blob();}
 if(objectURL)URL.revokeObjectURL(objectURL);objectURL=URL.createObjectURL(blob);
 bitmap=new Image();await new Promise((resolve,reject)=>{bitmap.onload=resolve;bitmap.onerror=()=>reject(Error('预览加载失败'));bitmap.src=objectURL;});
 $('empty-badge').hidden=Boolean(entry);$('image-info').textContent=entry?`${entry.name} · ${entry.width} × ${entry.height} · ${spaceNames[state.working_space]} → sRGB 预览`:'原创 '+spaceNames[state.target_space]+' 色卡 · 拍摄请使用全屏页';
 $('point-info').textContent=entry?(entry.points?`${entry.points.length} 个取样点 · ${entry.detection.method==='aruco-homography'?'标记自动识别':'手动定位'}`:'未定位 · 请指定四角'):'四角标记定位 · 黑色间隔';
 for(const id of ['redetect','manual','reset-points'])$(id).disabled=!isEditable();
 document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('selected',b.dataset.view===view));
 draw();
}
function draw(){
 if(!bitmap)return;const wrap=$('canvas-wrap'),zoom=Number($('zoom').value);
 canvas.width=bitmap.naturalWidth;canvas.height=bitmap.naturalHeight;
 const fitted=Math.min(wrap.clientWidth-44,(wrap.clientHeight-44)*canvas.width/canvas.height);canvas.style.width=Math.max(100,fitted*zoom)+'px';canvas.style.height='auto';
 ctx.drawImage(bitmap,0,0);const points=isEditable()?state.images[view]?.points:null;
 const factor=canvas.width/canvas.getBoundingClientRect().width;
 if(points&&$('show-points').checked){const radius=state.levels===17?1.8:3.1;for(let i=0;i<points.length;i++){const [nx,ny]=points[i],x=nx*(canvas.width-1),y=ny*(canvas.height-1);ctx.beginPath();ctx.arc(x,y,(i===selected?7:radius)*factor,0,Math.PI*2);ctx.strokeStyle=excluded.has(i)?'#ef8c68':i===selected?'#ffffff':'#e5efc4aa';ctx.lineWidth=(i===selected?2:1)*factor;ctx.stroke();ctx.beginPath();ctx.arc(x,y,.8*factor,0,Math.PI*2);ctx.fillStyle='#0b100a';ctx.fill();if(excluded.has(i)){ctx.beginPath();ctx.moveTo(x-3*factor,y-3*factor);ctx.lineTo(x+3*factor,y+3*factor);ctx.stroke();}}}
 if(manualCorners){ctx.strokeStyle='#d5f0ae';ctx.lineWidth=2*factor;manualCorners.forEach(([x,y],i)=>{x*=canvas.width;y*=canvas.height;ctx.beginPath();ctx.arc(x,y,7*factor,0,Math.PI*2);ctx.stroke();ctx.font=`${14*factor}px sans-serif`;ctx.fillStyle='#e4f7cb';ctx.fillText(String(i+1),x+10*factor,y);});}
}
function updateSelection(){const p=patch();$('exclude').disabled=!p||!isEditable();$('exclude').checked=excluded.has(selected);$('selected-title').textContent=p?`${p.id} · ${p.kind==='gray'?'灰阶':'色彩'}`:'选择取样点';$('selected-value').textContent=p?`参考 ${spaceNames[state.target_space]} ${p.rgb.map(x=>Math.round(x*255)).join(' / ')}${p.EV_from_white!==undefined?` · ${p.EV_from_white===null?'黑':p.EV_from_white.toFixed(2)+' EV'}`:''}`:'在预览上单击或拖动；方向键微调';$('sample-swatch').style.background=p?`rgb(${(p.preview_rgb||p.rgb).map(x=>Math.round(x*255)).join(',')})`:'';}
function normalized(e){const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];}
function markDirty(){dirty=true;renderState();}
canvas.addEventListener('pointerdown',async e=>{
 if(!isEditable())return;$('canvas-wrap').focus();const p=normalized(e);
 if(manualCorners){manualCorners.push(p);draw();if(manualCorners.length===4){const corners=manualCorners;manualCorners=null;await job('根据四角定位色块…',async()=>{await api('corners',{method:'POST',body:{role:view,corners}});dirty=false;await refresh();});$('locate-hint').textContent='逐点检查；可拖动取样点微调位置';}else $('locate-hint').textContent=`下一角：${['左上','右上','右下','左下'][manualCorners.length]}（色卡图像外边缘）`;return;}
 const points=state.images[view]?.points;if(!points)return;const rect=canvas.getBoundingClientRect();let best=-1,dist=20;
 points.forEach((pt,i)=>{const d=Math.hypot((pt[0]-p[0])*rect.width,(pt[1]-p[1])*rect.height);if(d<dist){best=i;dist=d;}});
 if(best>=0){selected=best;dragging=true;canvas.setPointerCapture(e.pointerId);updateSelection();draw();}
});
canvas.addEventListener('pointermove',e=>{if(!dragging)return;state.images[view].points[selected]=normalized(e);draw();});
async function savePoints(){await job('保存取样位置…',async()=>{await api('points',{method:'POST',body:{role:view,points:state.images[view].points}});dirty=false;await refresh();});}
canvas.addEventListener('pointerup',async()=>{if(!dragging)return;dragging=false;await savePoints();});
canvas.addEventListener('pointercancel',()=>{dragging=false;});
$('canvas-wrap').addEventListener('keydown',async e=>{if(selected<0||!isEditable()||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const p=state.images[view].points[selected],image=state.images[view],amount=e.shiftKey?10:1;const axis=e.key==='ArrowLeft'||e.key==='ArrowRight'?0:1;const sign=e.key==='ArrowLeft'||e.key==='ArrowUp'?-1:1;p[axis]=Math.max(0,Math.min(1,p[axis]+sign*amount/(axis===0?image.width:image.height)));draw();await savePoints();});
document.querySelectorAll('[data-mode]').forEach(button=>button.onclick=async()=>{mode=button.dataset.mode;view=mode==='apply'&&state.images.test?'test':'source';selected=-1;manualCorners=null;document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b===button));const titles={calibrate:['屏幕相对校色','让颜色，有据可依。','以当前屏幕为相对参考，建立可复用的相机色彩映射。'],style:['相机风格提取','留住你喜欢的色彩。','从基准照片与风格 JPG 中，估计可复用的全局色彩映射。'],apply:['应用与导出','把映射，带入作品。','使用一致的显影流程预览，再导出色彩配置与 16 位图像。']};[$('crumb').textContent,$('page-title').textContent,$('page-description').textContent]=titles[mode];await job('切换工作空间…',refresh);});
document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>job('加载预览…',async()=>{view=button.dataset.view;selected=-1;manualCorners=null;updateSelection();await loadView();}));
for(const role of ['source','target','test'])$('upload-'+role).onclick=()=>{uploadRole=role;$('file-input').value='';$('file-input').click();};
$('file-input').onchange=()=>{const file=$('file-input').files[0];if(!file)return;job('读取图像并识别色卡…',async()=>{const form=new FormData();form.append('role',uploadRole);form.append('file',file);await api('upload',{method:'POST',body:form});view=uploadRole;selected=-1;excluded.clear();dirty=false;await refresh();toast(state.images[uploadRole]?.points?'已识别色卡，请检查每个取样点。':uploadRole==='test'?'已加载应用照片。':'未识别完整标记，请使用「定位四角」，并确认色卡密度一致。');});};
async function changeSettings(){await job('更新色彩空间与色卡…',async()=>{try{await api('settings',{method:'POST',body:{levels:Number($('density').value),target_space:$('target-space').value,working_space:$('working-space').value}});}catch(e){await refresh();throw e;}view='source';selected=-1;excluded.clear();dirty=false;await refresh();toast('设置已更新。请重新导入照片；色卡变化时需重新拍摄。');});}
$('density').onchange=changeSettings;$('working-space').onchange=changeSettings;$('target-space').onchange=()=>{if(['srgb','display-p3','adobe-rgb'].includes($('working-space').value))$('working-space').value=$('target-space').value;changeSettings();};
$('open-chart').onclick=()=>window.open('/chart?'+chartQuery(),'jc-colorlab-chart');
async function download(path,name){const response=await api(path),blob=await response.blob();const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}
$('download-chart').onclick=()=>job('导出带对应 ICC 配置的色卡…',async()=>{const blob=await(await fetch('/chart.png?'+chartQuery())).blob();const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`JC-ColorLab-${state.manifest.patch_count}-${state.target_space}.png`;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);});
$('download-manifest').onclick=()=>job('导出参考值…',()=>download('export/manifest','JC-ColorLab-chart.json'));
for(const id of ['redetect','reset-points'])$(id).onclick=()=>job('重新识别四角标记…',async()=>{await api('detect',{method:'POST',body:{role:view}});selected=-1;dirty=false;await refresh();});
$('manual').onclick=()=>{manualCorners=manualCorners?null:[];$('locate-hint').textContent=manualCorners?'请依次点击色卡图像外边缘：左上 → 右上 → 右下 → 左下（再次点击按钮取消）':'已取消手动四角定位';draw();};
$('exclude').onchange=()=>{if(selected<0)return;$('exclude').checked?excluded.add(selected):excluded.delete(selected);markDirty();draw();};
$('radius').oninput=()=>{$('radius-value').textContent=$('radius').value+'%';markDirty();};
$('show-points').onchange=draw;$('zoom').onchange=draw;addEventListener('resize',draw);
$('fit').onclick=()=>job('取样、拟合映射并计算留出误差…',async()=>{await api('fit',{method:'POST',body:{mode,fraction:Number($('radius').value)/100,excluded:[...excluded],title:$('profile-name').value,notes:$('capture-notes').value}});dirty=false;await refresh();toast('映射已生成。请检查留出误差，并用独立照片评估实际效果。');});
document.querySelectorAll('[data-export]').forEach(button=>button.onclick=()=>job('正在生成导出文件…',async()=>{const kind=button.dataset.export,role=mode==='apply'&&state.images.test?'test':'source';const ext={cube:'cube',xmp:'xmp',tiff:'tif',model:'json',report:'json'}[kind];await download(`export/${kind}?size=${$('lut-size').value}&role=${role}`,`JC-ColorLab-${kind}-${state.working_space}.${ext}`);}));
$('export-baseline').onclick=()=>job('导出未应用映射的显影原片…',()=>download(`export/baseline-tiff?role=${mode==='apply'&&state.images.test?'test':'source'}`,`JC-ColorLab-baseline-${state.working_space}.tif`));
$('demo').onclick=()=>job('准备合成示例并自动定位…',async()=>{await api('demo',{method:'POST',body:{}});dirty=false;selected=-1;excluded.clear();view='source';await refresh();toast('已载入合成示例。这仅演示功能，不代表相机或屏幕的实测色准。');});
$('import-model').onclick=()=>{$('model-input').value='';$('model-input').click();};
$('model-input').onchange=()=>{const file=$('model-input').files[0];if(!file)return;job('打开已保存的映射…',async()=>{const form=new FormData();form.append('file',file);await api('import-model',{method:'POST',body:form});dirty=false;selected=-1;excluded.clear();view='source';await refresh();$('profile-name').value=state.title;document.querySelector('[data-mode="apply"]').click();toast('映射已恢复，可在「应用与导出」中导入新照片。');});};
$('help').onclick=()=>$('help-dialog').showModal();$('close-help').onclick=()=>$('help-dialog').close();
$('quit').onclick=()=>job('关闭本地服务…',async()=>{await api('quit',{method:'POST',body:{}});document.body.replaceChildren();const p=document.createElement('p');p.textContent='JC ColorLab 已退出。现在可以关闭此网页。';p.style.padding='40px';document.body.appendChild(p);});
job('打开色彩工作空间…',refresh);
