#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 日报 HTML 看板生成器（bankon 新粗野主义风格）

用法:
    python build.py data/2026-09-21.json -o output.html
    python build.py data/2026-09-21.json            # 默认输出 <json 同名>.html

数据格式见 data/today.json：date / weekday / title / subtitle / tagline /
stats[] / footerSource / sections[]。只需改 JSON，无需动本脚本。

设计要点（改样式前务必先读）：
  1. 卡片入场动画挂在 `html.js-ready` 下（见 CSS 的 .reveal）。
     若 JS 未执行（脚本报错 / 被拦 / 打印），卡片必须仍然可见，
     否则整页 36 张卡全部 opacity:0 —— 这是最容易踩的坑。
  2. 刷新按钮有两个（顶栏 + 首屏），都靠 [data-refresh] 绑定同一套逻辑。
  3. 刷新是「服务端重新抓取」（POST /api/refresh + 轮询 /api/status），
     不是浏览器刷新；离线双击打开时优雅降级为提示语。
"""

import argparse
import datetime
import html
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- 样式

CSS = r"""
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --paper:#F2F1EC;
  --paper-2:#E9E7E0;
  --card:#F8F7F3;
  --white:#FFFFFF;
  --ink:#0B0B0B;
  --muted:#5C5B54;
  --muted-2:#6E6D66;
  --muted-3:#8A8980;
  --accent:#F2704F;
  --accent-deep:#EE5A3C;
  --accent-ink:#210C05;
  --hair:rgba(11,11,11,.14);
  --r-xl:26px; --r-lg:20px; --r-md:13px; --r-pill:999px;
  --sh:4px 4px 0 var(--ink);
  --sh-sm:3px 3px 0 var(--ink);
  --ff:"Inter","Segoe UI Variable Display","Segoe UI",-apple-system,BlinkMacSystemFont,
       "HarmonyOS Sans SC","MiSans","PingFang SC","Microsoft YaHei","微软雅黑",
       system-ui,sans-serif;
}
html{-webkit-text-size-adjust:100%}
body{
  background:var(--paper);color:var(--ink);
  font-family:var(--ff);font-size:15px;font-weight:400;line-height:1.55;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
  font-variant-numeric:tabular-nums;
}
a{color:inherit}
.wrap{width:100%;max-width:1240px;margin:0 auto;padding:0 24px}

/* ---------- 顶栏 ---------- */
.topnav{
  position:sticky;top:0;z-index:60;
  background:rgba(242,241,236,.86);
  -webkit-backdrop-filter:saturate(1.5) blur(12px);
  backdrop-filter:saturate(1.5) blur(12px);
  border-bottom:2px solid var(--ink);
}
.topnav-in{max-width:1240px;margin:0 auto;padding:13px 24px;display:flex;align-items:center;gap:26px}
.brand{display:flex;align-items:center;gap:9px;font-size:15px;font-weight:700;letter-spacing:-.02em;white-space:nowrap}
.brand .mark{position:relative;width:20px;height:20px;border-radius:50%;background:var(--ink);flex:0 0 auto}
.brand .mark::after{content:"";position:absolute;left:6px;top:7px;width:8px;height:8px;border-radius:50%;background:var(--accent)}
.nav-links{display:flex;align-items:center;gap:2px;flex:1 1 0;min-width:0;overflow-x:auto;scrollbar-width:none}
.nav-links::-webkit-scrollbar{display:none}
.nav-links a{
  position:relative;font-size:13px;font-weight:500;color:var(--muted);
  text-decoration:none;padding:7px 12px;border-radius:var(--r-pill);
  white-space:nowrap;transition:color .18s,background .18s;
}
.nav-links a:hover{color:var(--ink);background:var(--paper-2)}
.nav-links a.on{color:var(--ink);font-weight:600}
.nav-links a.on::after{content:"";position:absolute;left:50%;bottom:0;margin-left:-2.5px;width:5px;height:5px;border-radius:50%;background:var(--accent)}
.nav-right{display:flex;align-items:center;gap:14px;flex:0 0 auto}
.nav-date{font-size:12px;font-weight:500;color:var(--muted);letter-spacing:.02em;white-space:nowrap}

/* 药丸按钮（描边） */
.pill{
  display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 16px;
  border:1.5px solid var(--ink);border-radius:var(--r-pill);background:transparent;
  color:var(--ink);font-family:var(--ff);font-size:13px;font-weight:600;line-height:1;
  cursor:pointer;text-decoration:none;white-space:nowrap;
  transition:background .18s,color .18s,transform .18s,opacity .18s;
}
.pill:hover{background:var(--ink);color:#fff;transform:translateY(-1px)}
.pill svg{width:14px;height:14px;flex:0 0 auto}

/* ---------- 首屏 ---------- */
.hero{padding:62px 0 0}
.hero-grid{display:grid;grid-template-columns:1.34fr .86fr;gap:52px;align-items:end}
.eyebrow{
  display:inline-flex;align-items:center;gap:9px;margin-bottom:24px;
  font-size:11.5px;font-weight:600;letter-spacing:.11em;color:var(--muted);text-transform:uppercase;
}
.eyebrow .live{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px rgba(242,112,79,.18)}
h1{font-size:clamp(44px,7.2vw,88px);line-height:.96;letter-spacing:-.022em;font-weight:800}
h1 .l2{display:block}
h1 .hl{color:var(--accent)}
.hero-right p{max-width:38ch;font-size:14px;color:var(--muted);line-height:1.68}
.hero-cta{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}

.btn-dark{
  display:inline-flex;align-items:center;gap:8px;padding:13px 21px;
  background:var(--ink);color:#fff;border:2px solid var(--ink);border-radius:var(--r-md);
  font-family:var(--ff);font-size:13px;font-weight:600;line-height:1;cursor:pointer;
  transition:background .18s,border-color .18s,color .18s,transform .18s,opacity .18s;
}
.btn-dark:hover{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);transform:translateY(-1px)}
.btn-line{
  display:inline-flex;align-items:center;gap:8px;padding:13px 21px;
  background:transparent;color:var(--ink);border:2px solid var(--ink);border-radius:var(--r-md);
  font-family:var(--ff);font-size:13px;font-weight:600;line-height:1;cursor:pointer;
  text-decoration:none;transition:background .18s,color .18s,transform .18s;
}
.btn-line:hover{background:var(--ink);color:#fff;transform:translateY(-1px)}
.btn-dark svg,.btn-line svg{width:14px;height:14px;flex:0 0 auto}

/* 刷新按钮的忙碌态（两个按钮共用） */
.pill[disabled],.btn-dark[disabled]{cursor:default;opacity:.72;transform:none}
.pill.spinning svg,.btn-dark.spinning svg{animation:spin .9s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* 数据条：列数 = stats 条目数（由内联 --sn 给出） */
.stats{
  display:grid;grid-template-columns:repeat(var(--sn,4),1fr);margin-top:46px;
  border:2px solid var(--ink);border-radius:var(--r-xl);overflow:hidden;background:var(--card);
}
.stat{padding:20px 22px;border-right:2px solid var(--ink)}
.stat:last-child{border-right:0}
.stat b{display:block;font-size:32px;font-weight:800;letter-spacing:-.035em;line-height:1}
.stat span{display:block;margin-top:9px;font-size:11.5px;font-weight:500;color:var(--muted);letter-spacing:.05em}

/* ---------- 焦点区 ---------- */
.spot{display:grid;grid-template-columns:1.58fr 1fr;gap:16px;margin-top:16px}
.feature{
  display:grid;grid-template-columns:1.24fr .76fr;gap:30px;align-items:center;
  background:var(--card);border:2px solid var(--ink);border-radius:var(--r-xl);padding:24px 28px 28px;
}
.feat-head{
  grid-column:1/-1;display:flex;align-items:baseline;justify-content:space-between;gap:16px;
  padding-bottom:15px;border-bottom:1.5px solid var(--hair);
}
.feat-head h2{font-size:22px;font-weight:700;letter-spacing:-.02em}
.feat-head .ver{font-size:11.5px;font-weight:500;color:var(--muted-3);letter-spacing:.06em}
.lead h3{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font-size:20px;font-weight:700;line-height:1.38;letter-spacing:-.018em;margin-bottom:12px}
.lead p{
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;
  font-size:13px;color:var(--muted);line-height:1.68;margin-bottom:16px;
}
.link{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;text-decoration:none}
.link svg{width:13px;height:13px;flex:0 0 auto;transition:transform .2s}
.link:hover{color:var(--accent-deep)}
.link:hover svg{transform:translate(2px,-2px)}
.illus{display:grid;place-items:center}
.illus svg{width:100%;max-width:214px;height:auto;display:block}

.spot-right{display:grid;grid-template-rows:1.25fr 1fr;gap:16px}
.accent-card{
  display:flex;flex-direction:column;justify-content:space-between;gap:18px;
  background:linear-gradient(158deg,#F58A67 0%,#EE5A3C 100%);
  border:2px solid var(--ink);border-radius:var(--r-xl);padding:24px 26px;box-shadow:var(--sh);
  transition:transform .2s cubic-bezier(.2,.7,.3,1),box-shadow .2s;
}
.accent-card:hover{transform:translate(-2px,-2px);box-shadow:6px 6px 0 var(--ink)}
.accent-card .row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.accent-card h3{font-size:21px;font-weight:700;letter-spacing:-.02em;color:var(--accent-ink)}
.accent-card .big{font-size:56px;font-weight:800;letter-spacing:-.045em;line-height:1;color:var(--accent-ink)}
.accent-card p{font-size:12.5px;line-height:1.6;color:#33150C}
.circ{
  width:34px;height:34px;flex:0 0 auto;display:grid;place-items:center;
  border:2px solid var(--accent-ink);border-radius:50%;background:transparent;
  color:var(--accent-ink);cursor:pointer;transition:background .18s,color .18s;
}
.circ:hover{background:var(--accent-ink);color:var(--accent)}
.circ svg{width:15px;height:15px}

.mini{
  display:flex;align-items:center;justify-content:space-between;gap:14px;
  background:var(--card);border:2px solid var(--ink);border-radius:var(--r-xl);padding:20px 24px;
  transition:transform .2s cubic-bezier(.2,.7,.3,1),box-shadow .2s;
}
.mini:hover{transform:translate(-2px,-2px);box-shadow:var(--sh-sm)}
.mini h3{font-size:17px;font-weight:700;letter-spacing:-.015em}
.mini .sub{margin-top:6px;font-size:11.5px;font-weight:500;color:var(--muted);letter-spacing:.02em}
.mini .circ{border-color:var(--ink);color:var(--ink)}
.mini:hover .circ{background:var(--ink);color:#fff}

/* ---------- 板块 ---------- */
.section{padding:58px 0 0;scroll-margin-top:80px}
.sec-head{
  display:flex;align-items:center;gap:14px;margin-bottom:20px;
  padding-bottom:14px;border-bottom:2px solid var(--ink);
}
.sec-head h2{font-size:23px;font-weight:700;letter-spacing:-.02em;white-space:nowrap}
.sec-head .chip{
  flex:0 0 auto;border:1.5px solid var(--ink);border-radius:var(--r-pill);
  padding:3px 11px;font-size:11.5px;font-weight:600;color:var(--muted);letter-spacing:.04em;
}
.sec-head .idx{margin-left:auto;flex:0 0 auto;font-size:11.5px;font-weight:600;color:var(--muted-3);letter-spacing:.1em}

.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(292px,1fr));gap:14px}
.card{
  position:relative;display:flex;flex-direction:column;
  background:var(--card);border:2px solid var(--ink);border-radius:var(--r-lg);
  padding:20px 22px 18px;
  transition:transform .2s cubic-bezier(.2,.7,.3,1),box-shadow .2s;
}
.card:hover{transform:translate(-2px,-3px);box-shadow:var(--sh)}
.card .no{
  position:absolute;right:16px;top:16px;width:28px;height:28px;
  display:grid;place-items:center;border:1.5px solid var(--ink);border-radius:50%;
  font-size:11px;font-weight:700;letter-spacing:-.02em;color:var(--muted);
  transition:border-color .18s,color .18s;
}
.card:hover .no{border-color:var(--accent);color:var(--accent)}
.card h3{
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
  padding-right:38px;margin-bottom:11px;
  font-size:14.5px;font-weight:600;line-height:1.5;letter-spacing:-.01em;
}
.meta{display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:11px;font-weight:500;color:var(--muted-2);letter-spacing:.03em}
.meta .src{color:var(--muted);font-weight:600}
.meta .dot{width:3px;height:3px;border-radius:50%;background:var(--muted-2);flex:0 0 auto}
.card p{
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;
  flex:1;margin-bottom:16px;font-size:12.5px;color:var(--muted);line-height:1.64;
}
.card .link{font-size:12px}
@media (min-width:900px){
  .card.wide{grid-column:span 2}
  .card.wide h3{-webkit-line-clamp:2}
  .card.wide p{-webkit-line-clamp:3}
}

/* ---------- 页脚 ---------- */
.footer{margin-top:66px;border-top:2px solid var(--ink);padding:26px 0 44px}
.foot{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:14px;
  font-size:12px;font-weight:500;color:var(--muted)}
.foot .grp{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.foot .dot{width:3px;height:3px;border-radius:50%;background:var(--muted-2)}
.foot strong{color:var(--ink);font-weight:700}
.foot a{color:var(--ink);font-weight:600;text-decoration:none;border-bottom:1.5px solid var(--accent);padding-bottom:1px}

/* ---------- 浮层 ---------- */
.to-top{
  position:fixed;right:22px;bottom:22px;z-index:70;width:46px;height:46px;
  display:grid;place-items:center;background:var(--card);color:var(--ink);
  border:2px solid var(--ink);border-radius:50%;cursor:pointer;
  opacity:0;transform:translateY(10px);pointer-events:none;transition:opacity .25s,transform .25s,background .18s,color .18s;
}
.to-top.show{opacity:1;transform:none;pointer-events:auto}
.to-top:hover{background:var(--ink);color:#fff}
.to-top svg{width:18px;height:18px}

.toast{
  position:fixed;left:50%;bottom:26px;z-index:80;transform:translate(-50%,14px);
  display:flex;align-items:center;gap:9px;padding:12px 18px;
  background:var(--ink);color:#fff;border-radius:var(--r-pill);
  font-size:12.5px;font-weight:600;letter-spacing:.01em;
  opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;
  max-width:calc(100vw - 40px);
}
.toast.show{opacity:1;transform:translate(-50%,0)}
.toast.err{background:#7A2113}
.toast .dotpy{width:7px;height:7px;border-radius:50%;background:var(--accent);flex:0 0 auto}

/* 入场动画 —— 关键，两处都不能省：
   ① 必须挂在 html.js-ready 下：否则 JS 一旦未执行（报错 / 被拦 / 打印环境），
      .reveal 永远停在 opacity:0，整页卡片全部不可见。
   ② .in 的生效规则也必须带 html.js-ready 前缀：
      `html.js-ready .reveal` 的优先级是 (0,2,1)，而 `.reveal.in` 只有 (0,2,0)。
      少写前缀的话前者压过后者，加了 .in 也不显示 —— 整页空白。 */
html.js-ready .reveal{opacity:0;transform:translateY(14px)}
html.js-ready .reveal.in{opacity:1;transform:none}
.reveal.in{transition:opacity .45s ease,transform .45s cubic-bezier(.2,.7,.3,1)}

/* ---------- 响应式 ---------- */
@media (max-width:1080px){
  .hero-grid{grid-template-columns:1fr;gap:30px;align-items:start}
  .hero-right p{max-width:56ch}
  .spot{grid-template-columns:1fr}
  .feature{grid-template-columns:1fr}
  .illus svg{max-width:180px}
}
@media (max-width:860px){
  .nav-date{display:none}
}
@media (max-width:720px){
  .wrap{padding:0 18px}
  .topnav-in{padding:12px 18px;gap:14px}
  .nav-links a{padding:6px 9px;font-size:12.5px}
  .hero{padding:40px 0 0}
  h1{letter-spacing:-.02em}
  /* 数据条：偶数条两列、奇数条一列，避免边框线错位 */
  .stats.even{grid-template-columns:1fr 1fr}
  .stats.even .stat{border-bottom:2px solid var(--ink)}
  .stats.even .stat:nth-child(2n){border-right:0}
  .stats.even .stat:nth-last-child(-n+2){border-bottom:0}
  .stats.odd{grid-template-columns:1fr}
  .stats.odd .stat{border-right:0;border-bottom:2px solid var(--ink)}
  .stats.odd .stat:last-child{border-bottom:0}
  .cards{grid-template-columns:1fr;gap:12px}
  .card{padding:18px 18px 16px}
  .feature{padding:20px}
  .section{padding:44px 0 0}
  .sec-head h2{font-size:20px}
  .sec-head{gap:10px;flex-wrap:wrap}
  .to-top{right:16px;bottom:16px;width:42px;height:42px}
}
@media (prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important}
  html.js-ready .reveal,.reveal{opacity:1!important;transform:none!important}
}
@media print{
  .topnav,.to-top,.toast{display:none!important}
  .card{break-inside:avoid}
  html.js-ready .reveal,.reveal{opacity:1!important;transform:none!important}
  body{background:#fff}
}
"""

# ---------------------------------------------------------------- 脚本

JS = r"""
(function(){
  var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 回到顶部 ---------- */
  var toTop=document.querySelector('.to-top');
  if(toTop){
    window.addEventListener('scroll',function(){
      toTop.classList.toggle('show',window.scrollY>600);
    },{passive:true});
    toTop.addEventListener('click',function(){
      try{window.scrollTo({top:0,behavior:reduce?'auto':'smooth'});}catch(_){window.scrollTo(0,0);}
    });
  }

  /* ---------- 导航：点击定位 + 滚动高亮 ---------- */
  var links=[].slice.call(document.querySelectorAll('.nav-links a'));
  function setActive(id){
    links.forEach(function(a){a.classList.toggle('on',a.getAttribute('href')==='#'+id);});
  }
  links.forEach(function(a){
    a.addEventListener('click',function(e){
      var href=a.getAttribute('href');
      if(!href||href.charAt(0)!=='#')return;
      var el=document.getElementById(href.slice(1));
      if(!el)return;
      e.preventDefault();
      setActive(el.id);
      try{el.scrollIntoView({behavior:reduce?'auto':'smooth',block:'start'});}
      catch(_){el.scrollIntoView(true);}
      if(history.replaceState)history.replaceState(null,'',href);
    });
  });
  var secs=[].slice.call(document.querySelectorAll('main section[id]'));
  if('IntersectionObserver' in window&&secs.length){
    var spy=new IntersectionObserver(function(es){
      es.forEach(function(en){if(en.isIntersecting)setActive(en.target.id);});
    },{rootMargin:'-84px 0px -62% 0px',threshold:0});
    secs.forEach(function(s){spy.observe(s);});
  }

  /* ---------- 卡片入场 ---------- */
  var revs=[].slice.call(document.querySelectorAll('.reveal'));
  if(!reduce&&'IntersectionObserver' in window){
    var io=new IntersectionObserver(function(es){
      es.forEach(function(en,i){
        if(!en.isIntersecting)return;
        var el=en.target;
        setTimeout(function(){el.classList.add('in');},Math.min(i*28,160));
        io.unobserve(el);
      });
    },{rootMargin:'0px 0px -8% 0px',threshold:0.04});
    revs.forEach(function(c){io.observe(c);});
  }else{
    revs.forEach(function(c){c.classList.add('in');});
  }

  /* ---------- 服务端刷新 ----------
     注意：这是「服务器端重新抓取」，不是浏览器刷新。
     只有通过 HTTP 打开（server.js 提供）时才可用；
     本地双击打开的静态文件会走到 catch 分支，优雅降级。 */
  var toast=document.querySelector('.toast'),tTimer=null;
  function say(msg,isErr){
    if(!toast)return;
    toast.classList.toggle('err',!!isErr);
    var m=toast.querySelector('.msg');
    if(m)m.textContent=msg;
    toast.classList.add('show');
    clearTimeout(tTimer);
    tTimer=setTimeout(function(){toast.classList.remove('show');},4200);
  }

  var btns=[].slice.call(document.querySelectorAll('[data-refresh]'));
  var busy=false;
  function setBusy(b,label){
    busy=!!b;
    btns.forEach(function(x){
      x.disabled=!!b;
      x.classList.toggle('spinning',!!b);
      var sp=x.querySelector('.rl');
      if(!sp)return;
      if(!x.getAttribute('data-orig'))x.setAttribute('data-orig',sp.textContent);
      sp.textContent=label||x.getAttribute('data-orig');
    });
  }

  async function pollRefresh(){
    var t0=Date.now();
    while(Date.now()-t0<5*60*1000){
      await new Promise(function(r){setTimeout(r,2500);});
      var j;
      try{
        var r=await fetch('/api/status',{cache:'no-store'});
        j=await r.json();
      }catch(_){
        continue;   /* 网络抖动，继续轮询 */
      }
      if(j.state==='running'){setBusy(true,'刷新中');continue;}
      if(j.state==='ok'){
        setBusy(true,'已更新');
        say('已更新，正在重新载入…');
        setTimeout(function(){location.reload();},700);
        return;
      }
      if(j.state==='error'){
        setBusy(false);
        say('刷新失败：'+(j.lastError||'未知错误'),true);
        return;
      }
      break;
    }
    setBusy(false);
    say('刷新超时，请稍后重试',true);
  }

  btns.forEach(function(b){
    b.addEventListener('click',async function(){
      if(busy){say('正在刷新，请稍候…');return;}
      setBusy(true,'刷新中');
      say('正在抓取最新资讯，约需 1 分钟…');
      try{
        var r=await fetch('/api/refresh',{method:'POST'});
        var j=await r.json().catch(function(){return {};});
        if(r.status===202){
          pollRefresh();
        }else if(r.status===429){
          setBusy(false);
          if(j.reason==='busy')say('已有刷新在进行中，请稍候');
          else say('刚刷新过，请 '+(j.retryAfter||60)+' 秒后再试');
        }else{
          setBusy(false);
          say('无法触发刷新：'+(j.reason||j.error||r.status),true);
        }
      }catch(e){
        setBusy(false);
        say('离线打开：当前是本地文件，未连接服务器');
      }
    });
  });

  /* 页面载入时同步一次服务器状态（例如别的访客正在刷新） */
  (async function(){
    if(!btns.length||location.protocol==='file:')return;
    try{
      var r=await fetch('/api/status',{cache:'no-store'});
      var j=await r.json();
      if(j.state==='running'){setBusy(true,'刷新中');pollRefresh();}
    }catch(_){/* 离线打开，忽略 */}
  })();
})();
"""

# ---------------------------------------------------------------- 图标 / 插画

ICON_REFRESH = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/>'
                '<path d="M21 3v6h-6"/></svg>')
ICON_UP = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
           'stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>')
ICON_ARROW = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
              'stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7"/>'
              '<path d="M8 7h9v9"/></svg>')
ICON_MINUS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" '
              'stroke-linecap="round"><path d="M6 12h12"/></svg>')
ICON_PLUS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" '
             'stroke-linecap="round"><path d="M12 6v12M6 12h12"/></svg>')

ILLUS = """
<svg viewBox="0 0 268 196" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <clipPath id="ck3"><rect x="26" y="18" width="152" height="88" rx="14"/></clipPath>
  </defs>
  <rect x="72" y="92" width="152" height="88" rx="14" fill="#E9E7E0" stroke="#0B0B0B" stroke-width="2.5"/>
  <path d="M92 150h58" stroke="#0B0B0B" stroke-width="2.5" stroke-linecap="round" opacity=".22"/>
  <rect x="49" y="55" width="152" height="88" rx="14" fill="#F8F7F3" stroke="#0B0B0B" stroke-width="2.5"/>
  <path d="M69 113h34" stroke="#0B0B0B" stroke-width="2.5" stroke-linecap="round" opacity=".22"/>
  <g clip-path="url(#ck3)">
    <rect x="26" y="18" width="152" height="88" fill="#FFFFFF"/>
    <rect x="26" y="70" width="152" height="36" fill="#F2704F"/>
    <rect x="42" y="80" width="30" height="9" rx="2" fill="#0B0B0B"/>
    <rect x="42" y="93" width="18" height="5" rx="2.5" fill="#0B0B0B" opacity=".45"/>
    <rect x="126" y="79" width="36" height="12" rx="6" fill="#FFFFFF" stroke="#0B0B0B" stroke-width="2"/>
  </g>
  <rect x="26" y="18" width="152" height="88" rx="14" fill="none" stroke="#0B0B0B" stroke-width="2.5"/>
  <path d="M45 42h44" stroke="#0B0B0B" stroke-width="2.5" stroke-linecap="round" opacity=".22"/>
  <path d="M45 54h26" stroke="#0B0B0B" stroke-width="2.5" stroke-linecap="round" opacity=".22"/>
</svg>
"""


# ---------------------------------------------------------------- 渲染

def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def render_card(idx, item, wide=False):
    """渲染单张卡片。idx 为从 1 开始的全局编号。"""
    meta = f'<span class="src">{esc(item.get("source", ""))}</span>'
    stamp = item.get("date")           # RSS 数据带采集时间，手工数据可省略
    if stamp:
        meta += f'<span class="dot"></span><span>{esc(stamp)}</span>'
    return (
        f'<article class="card reveal{" wide" if wide else ""}">'
        f'<span class="no">{idx:02d}</span>'
        f'<h3 class="card-title">{esc(item.get("title", ""))}</h3>'
        f'<div class="meta">{meta}</div>'
        f'<p>{esc(item.get("summary", ""))}</p>'
        f'<a class="link" href="{esc(item.get("url", "#"))}" target="_blank" rel="noopener noreferrer">'
        f'阅读全文 {ICON_ARROW}</a>'
        f'</article>'
    )


def render_section(sec, start_idx, sec_no, sec_total):
    """渲染单个板块。返回 (html, 下一个全局编号)。"""
    items = sec["items"]
    cards = "".join(
        render_card(start_idx + i, it, wide=(i == 0)) for i, it in enumerate(items)
    )
    return f'''
<section class="section" id="{esc(sec["id"])}">
  <div class="sec-head">
    <h2>{esc(sec["name"])}</h2>
    <span class="chip">{len(items)} 条</span>
    <span class="idx">{sec_no:02d} / {sec_total:02d}</span>
  </div>
  <div class="cards">{cards}
  </div>
</section>
''', start_idx + len(items)


def build(data, version=""):
    sections = data.get("sections", [])
    stats = data.get("stats", [])
    total = sum(len(s["items"]) for s in sections)
    nsec = len(sections)

    # ---- 导航（第一个板块默认高亮） ----
    nav_parts = []
    for i, s in enumerate(sections):
        cls = ' class="on"' if i == 0 else ""
        nav_parts.append(f'<a href="#{esc(s["id"])}"{cls}>{esc(s["name"].split(" / ")[0])}</a>')
    nav_buttons = "".join(nav_parts)

    # ---- 数据条 ----
    stat_cards = "".join(
        f'<div class="stat"><b>{esc(st["num"])}</b><span>{esc(st["label"])}</span></div>'
        for st in stats
    )
    stats_cls = "even" if len(stats) % 2 == 0 else "odd"
    stats_style = f' style="--sn:{len(stats)}"' if stats else ""

    # 「收录信源」的数值，供珊瑚卡文案复用（找不到就退化成泛称）
    src_note = "多个中文信息源"
    for st in stats:
        if "信源" in str(st.get("label", "")):
            src_note = f'{st["num"]} 个中文信息源'
            break

    # ---- 焦点卡：取第一个非空板块的头条 ----
    lead = {}
    for s in sections:
        if s.get("items"):
            lead = s["items"][0]
            break
    lead_html = (
        '<div class="lead">'
        f'<h3>{esc(lead.get("title", ""))}</h3>'
        f'<p>{esc(lead.get("summary", ""))}</p>'
        f'<a class="link" href="{esc(lead.get("url", "#"))}" target="_blank" rel="noopener noreferrer">'
        f'阅读全文 {ICON_ARROW}</a>'
        '</div>'
    )

    # ---- 板块正文 ----
    body, idx = "", 1
    for i, s in enumerate(sections, 1):
        chunk, idx = render_section(s, idx, i, nsec)
        body += chunk

    fs = data.get("footerSource", {}) or {}
    date_str = data.get("date", "")
    weekday = data.get("weekday", "")
    sec_hint = " · ".join(s["name"].split(" / ")[0] for s in sections)
    first_id = sections[0]["id"] if sections else ""

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 日报 · {esc(date_str)}</title>
<script>document.documentElement.className+=' js-ready';</script>
<style>{CSS}</style>
</head>
<body>

<nav class="topnav" aria-label="板块导航">
  <div class="topnav-in">
    <div class="brand"><span class="mark"></span>AI HOT · 日报</div>
    <div class="nav-links">{nav_buttons}</div>
    <div class="nav-right">
      <span class="nav-date">{esc(date_str)} · {esc(weekday)}</span>
      <button class="pill" type="button" data-refresh aria-label="刷新资讯" title="让服务器重新抓取最新资讯">{ICON_REFRESH}<span class="rl">刷新</span></button>
    </div>
  </div>
</nav>

<header class="hero">
  <div class="wrap">
    <div class="hero-grid">
      <div class="hero-left">
        <div class="eyebrow"><span class="live"></span>{esc(date_str)} · {esc(weekday)} · 北京时间</div>
        <h1>{esc(data.get("title", "今日"))} <span class="hl">AI</span> <span class="l2">{esc(data.get("subtitle", ""))}</span></h1>
      </div>
      <div class="hero-right">
        <p>{esc(data.get("tagline", ""))}</p>
        <div class="hero-cta">
          <button class="btn-dark" type="button" data-refresh>{ICON_REFRESH}<span class="rl">刷新数据</span></button>
          <a class="btn-line" href="#{esc(first_id)}">浏览今日精选 {ICON_ARROW}</a>
        </div>
      </div>
    </div>
    <div class="stats {stats_cls}"{stats_style}>{stat_cards}</div>
  </div>
</header>

<main class="wrap">

  <div class="spot">
    <section class="feature reveal">
      <div class="feat-head">
        <h2>最新更新</h2>
        <span class="ver">v {esc(version) if version else esc(date_str)}</span>
      </div>
{lead_html}
      <div class="illus">{ILLUS}</div>
    </section>

    <div class="spot-right">
      <article class="accent-card reveal">
        <div class="row">
          <h3>今日收录</h3>
          <a class="circ" href="#{esc(first_id)}" aria-label="查看统计">{ICON_MINUS}</a>
        </div>
        <div>
          <div class="big">{total}</div>
          <p>来自 {esc(src_note)}，当日精选全部由本地脚本抓取，零 AI 调用。</p>
        </div>
      </article>
      <article class="mini reveal">
        <div>
          <h3>共 {nsec} 大板块</h3>
          <div class="sub">{esc(sec_hint)}</div>
        </div>
        <a class="circ" href="#{esc(first_id)}" aria-label="展开板块">{ICON_PLUS}</a>
      </article>
    </div>
  </div>
{body}
</main>

<footer class="footer">
  <div class="wrap foot">
    <div class="grp">
      <span>共 <strong>{total}</strong> 条</span>
      <span class="dot"></span>
      <span>{nsec} 大板块</span>
      <span class="dot"></span>
      <span>{esc(date_str)} 北京时间</span>
    </div>
    <span>数据来自 <a href="{esc(fs.get("url", "#"))}" target="_blank" rel="noopener noreferrer">{esc(fs.get("name", ""))}</a></span>
  </div>
</footer>

<button class="to-top" type="button" aria-label="回到顶部">{ICON_UP}</button>
<div class="toast" role="status" aria-live="polite"><span class="dotpy"></span><span class="msg"></span></div>

<script>{JS}</script>
</body>
</html>
'''


def main():
    ap = argparse.ArgumentParser(description="AI 日报 HTML 看板生成器")
    ap.add_argument("data", help="日报数据 JSON 文件路径")
    ap.add_argument("-o", "--output", help="输出 HTML（默认与 JSON 同名 .html）")
    args = ap.parse_args()

    src = Path(args.data)
    if not src.exists():
        print(f"[x] 找不到数据文件: {src}", file=sys.stderr)
        return 1

    with src.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # 版本戳用数据文件的实际生成时间，别硬编码
    mtime = datetime.datetime.fromtimestamp(src.stat().st_mtime)
    version = f'{data.get("date", "")} {mtime.strftime("%H:%M")}'

    out = Path(args.output) if args.output else src.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(data, version), encoding="utf-8", newline="\n")

    sections = data.get("sections", [])
    total = sum(len(s["items"]) for s in sections)
    print(f"[v] 已生成 {out}  ({data.get('date')}, {len(sections)} 板块, {total} 条)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
