const controls=document.getElementById('chart-controls');
function dimensions(){document.getElementById('display-size').textContent=`当前显示区域约 ${Math.round(innerWidth*devicePixelRatio)} × ${Math.round(innerHeight*devicePixelRatio)} 像素（含系统缩放估算） · 推荐全屏 3840 × 2160`;}
dimensions();addEventListener('resize',dimensions);
document.getElementById('fullscreen').onclick=async()=>{try{await document.documentElement.requestFullscreen();controls.hidden=true;}catch(e){document.getElementById('display-size').textContent='浏览器不允许网页全屏，请使用浏览器菜单进入全屏后，再单击画面隐藏提示。';}};
document.getElementById('target').onclick=()=>{controls.hidden=!controls.hidden;};
document.addEventListener('fullscreenchange',()=>{controls.hidden=Boolean(document.fullscreenElement);dimensions();});
