/* Copyright 2026 J.C. Lu. MIT. Translate display strings without changing image/model state. */
'use strict';
(async()=>{
 const catalog=await(await fetch('/static/locales/catalog.json')).json();
 const key='jc-colorlab-language';
 const token=document.querySelector('meta[name="lab-token"]')?.content;
 const headers={'X-Lab-Token':token,'Content-Type':'application/json'};
 let locale='zh-CN';try{locale=localStorage.getItem(key)||locale;}catch{}
 try{const pref=await(await fetch('/api/preferences',{headers})).json();if(pref.language)locale=pref.language;}catch{}
 if(!catalog.locales.includes(locale))locale='zh-CN';
 let translate=JCTranslate.compile(catalog,locale);
 const texts=new WeakMap(),attributes=new WeakMap();
 const skipped=element=>!element||['SCRIPT','STYLE','CODE'].includes(element.tagName)||element.closest('[data-no-i18n]');
 const observer=new MutationObserver(()=>apply());
 function transform(value,previous,element){
  const source=previous&&value===previous.output?previous.source:value;
  let output=translate(source);
  if(element?.id==='image-info'){const parts=source.match(/^(.*?)( · \d+ × \d+ · .*)$/);if(parts)output=(parts[1].startsWith('合成')?translate(parts[1]):parts[1])+translate(parts[2]);}
  if(['source-name','target-name','test-name'].includes(element?.id)&&!source.startsWith('选择')&&!source.startsWith('合成'))output=source;
  return {source,output};
 }
 function apply(){
  observer.disconnect();
  document.documentElement.lang=locale;
  const walker=document.createTreeWalker(document.documentElement,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()){
   const node=walker.currentNode;if(skipped(node.parentElement)||node.parentElement.tagName==='TEXTAREA')continue;
   const entry=transform(node.nodeValue,texts.get(node),node.parentElement);texts.set(node,entry);
   if(node.nodeValue!==entry.output)node.nodeValue=entry.output;
  }
  for(const element of document.querySelectorAll('[aria-label],[title],[placeholder],[alt]')){
   if(skipped(element))continue;
   const saved=attributes.get(element)||{};
   for(const name of ['aria-label','title','placeholder','alt']){
    if(!element.hasAttribute(name))continue;
    const entry=transform(element.getAttribute(name),saved[name]);saved[name]=entry;
    if(element.getAttribute(name)!==entry.output)element.setAttribute(name,entry.output);
   }
   attributes.set(element,saved);
  }
  observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['aria-label','title','placeholder','alt']});
 }
 function select(value,persist=true){
  if(!catalog.locales.includes(value))return;
  locale=value;translate=JCTranslate.compile(catalog,locale);
  const selector=document.getElementById('language-select');if(selector)selector.value=locale;
  if(persist){
   try{localStorage.setItem(key,locale);}catch{}
   fetch('/api/preferences',{method:'POST',headers,body:JSON.stringify({language:locale})}).then(r=>{if(!r.ok)console.warn('Language preference could not be saved');}).catch(()=>console.warn('Language preference could not be saved'));
  }
  apply();
 }
 document.getElementById('language-select')?.addEventListener('change',e=>select(e.target.value));
 addEventListener('storage',e=>{if(e.key===key)select(e.newValue,false);});
 select(locale,false);
})().catch(error=>console.error('Language catalog could not be loaded',error));
