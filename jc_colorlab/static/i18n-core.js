/* Copyright 2026 J.C. Lu. MIT. Pure catalog compiler, also tested in Node. */
(function(root){
'use strict';
const escape=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
function compile(catalog,locale){
 const index=catalog.locales.indexOf(locale);
 if(index<1)return text=>String(text);
 const rows=catalog.entries.slice().sort((a,b)=>b[0].length-a[0].length);
 let offset=1;
 const rules=rows.map(row=>{
  let count=0,vars=[],cursor=0,pattern='';
  for(const match of row[0].matchAll(/\{(\d+)\}/g)){
   pattern+=escape(row[0].slice(cursor,match.index));
   pattern+=match.index===0?'([\\d., —]+)':'([^\\n]+?)';
   vars.push(Number(match[1]));count++;cursor=match.index+match[0].length;
  }
  pattern+=escape(row[0].slice(cursor));
  if(/\{\d+\}$/.test(row[0]))pattern+='$';
  const rule={offset,count,vars,text:row[index],pattern:'('+pattern+')'};
  offset+=count+1;return rule;
 });
 const expression=new RegExp(rules.map(r=>r.pattern).join('|'),'gu');
 function translate(text,depth=0){
  return String(text).replace(expression,(...args)=>{
   const rule=rules.find(r=>args[r.offset]!==undefined);
   return rule.text.replace(/\{(\d+)\}/g,(_,key)=>{
    const value=args[rule.offset+1+rule.vars.indexOf(Number(key))]??'';
    return depth<1?translate(value,depth+1):value;
   });
  });
 }
 return translate;
}
root.JCTranslate={compile};
if(typeof module!=='undefined')module.exports=root.JCTranslate;
})(typeof window==='undefined'?globalThis:window);
