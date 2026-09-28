# -*- coding: utf-8 -*-
"""
生成「bankon 新粗野主义」风格的 AI 日报 UI 预览页（只读产物，不影响生产 build.py）。

用法：python tools/gen_preview_bankon.py
输出：preview/ui-preview_bankon.html
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "today.json"
OUT_DIR = ROOT / "preview"
OUT = OUT_DIR / "ui-preview_bankon.html"


def esc(s):
    return html.escape(str(s or ""), quote=True)


CSS = """
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
  transition:background .18s,color .18s,transform .18s;
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
  transition:background .18s,border-color .18s,color .18s,transform .18s;
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

/* 数据条 */
.stats{
  display:grid;grid-template-columns:repeat(4,1fr);margin-top:46px;
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
.toast .dotpy{width:7px;height:7px;border-radius:50%;background:var(--accent);flex:0 0 auto}

.badge-preview{
  position:fixed;right:22px;bottom:78px;z-index:70;
  display:flex;align-items:center;gap:8px;padding:8px 14px;
  background:var(--paper);border:1.5px dashed var(--muted-2);border-radius:var(--r-pill);
  font-size:11.5px;font-weight:600;color:var(--muted);letter-spacing:.03em;
}
.badge-preview .dotpy{width:6px;height:6px;border-radius:50%;background:var(--accent);flex:0 0 auto}

/* 入场动画 —— 关键，两处都不能省：
   ① 必须挂在 html.js-ready 下：否则 JS 一旦未执行（报错 / 被拦 / 打印环境），
      .reveal 永远停在 opacity:0，整页卡片全部不可见。
   ② .in 的生效规则也必须带 html.js-ready 前缀：
      `html.js-ready .reveal` 优先级 (0,2,1) 会压过 `.reveal.in` 的 (0,2,0)，
      少写前缀的话加了 .in 也不显示 —— 整页空白。生产 build.py 保持同一写法。 */
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
  .stats{grid-template-columns:1fr 1fr}
  .stat{border-bottom:2px solid var(--ink)}
  .stat:nth-child(2n){border-right:0}
  .stat:nth-last-child(-n+2){border-bottom:0}
  .cards{grid-template-columns:1fr;gap:12px}
  .card{padding:18px 18px 16px}
  .feature{padding:20px}
  .section{padding:44px 0 0}
  .sec-head h2{font-size:20px}
  .sec-head{gap:10px;flex-wrap:wrap}
  .badge-preview{right:16px;bottom:68px;padding:7px 12px}
  .to-top{right:16px;bottom:16px;width:42px;height:42px}
}
@media (prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important}
  html.js-ready .reveal,.reveal{opacity:1!important;transform:none!important}
}
@media print{
  .topnav,.to-top,.badge-preview,.toast{display:none!important}
  .card{break-inside:avoid}
  html.js-ready .reveal,.reveal{opacity:1!important;transform:none!important}
  body{background:#fff}
}
"""

JS = """
(function(){
  var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 回到顶部 */
  var toTop=document.querySelector('.to-top');
  if(toTop){
    window.addEventListener('scroll',function(){
      toTop.classList.toggle('show',window.scrollY>600);
    },{passive:true});
    toTop.addEventListener('click',function(){
      window.scrollTo({top:0,behavior:reduce?'auto':'smooth'});
    });
  }

  /* 导航滚动定位 + 高亮 */
  var links=[].slice.call(document.querySelectorAll('.nav-links a'));
  links.forEach(function(a){
    a.addEventListener('click',function(e){
      var id=a.getAttribute('href');
      if(!id||id.charAt(0)!=='#')return;
      var el=document.getElementById(id.slice(1));
      if(!el)return;
      e.preventDefault();
      try{el.scrollIntoView({behavior:reduce?'auto':'smooth',block:'start'});}
      catch(_){el.scrollIntoView();}
      history.replaceState(null,'',id);
    });
  });
  var secs=[].slice.call(document.querySelectorAll('section[id]'));
  function setActive(id){
    links.forEach(function(a){a.classList.toggle('on',a.getAttribute('href')==='#'+id);});
  }
  if('IntersectionObserver' in window&&secs.length){
    var ob=new IntersectionObserver(function(es){
      es.forEach(function(en){if(en.isIntersecting)setActive(en.target.id);});
    },{rootMargin:'-84px 0px -62% 0px',threshold:0});
    secs.forEach(function(s){ob.observe(s);});
  }

  /* 卡片入场 */
  var cards=[].slice.call(document.querySelectorAll('.reveal'));
  if(!reduce&&'IntersectionObserver' in window){
    var ob2=new IntersectionObserver(function(es){
      es.forEach(function(en,i){
        if(en.isIntersecting){
          var el=en.target;
          setTimeout(function(){el.classList.add('in');},Math.min(i*28,160));
          ob2.unobserve(el);
        }
      });
    },{rootMargin:'0px 0px -8% 0px',threshold:0.04});
    cards.forEach(function(c){ob2.observe(c);});
  }else{
    cards.forEach(function(c){c.classList.add('in');});
  }

  /* 刷新（预览模式下会优雅降级） */
  var toast=document.querySelector('.toast');
  var tTimer=null;
  function say(msg){
    if(!toast)return;
    toast.innerHTML='<span class="dotpy"></span><span></span>';
    toast.lastChild.textContent=msg;
    toast.classList.add('show');
    clearTimeout(tTimer);
    tTimer=setTimeout(function(){toast.classList.remove('show');},3600);
  }
  var busy=false;
  function refresh(){
    if(busy){say('正在刷新，请稍候…');return;}
    busy=true;say('正在抓取最新资讯…');
    fetch('/api/refresh',{method:'POST'})
      .then(function(r){return r.json().catch(function(){return{};}).then(function(j){return{s:r.status,j:j};});})
      .then(function(o){
        if(o.s===200||o.s===202){say('已开始更新，约 1 分钟后刷新本页');}
        else if(o.s===429){say('刚刚更新过，请稍后再试');}
        else{say('更新失败（HTTP '+o.s+'）');}
      })
      .catch(function(){say('预览模式：当前是静态文件，未连接服务');})
      .then(function(){setTimeout(function(){busy=false;},4000);});
  }
  [].slice.call(document.querySelectorAll('[data-refresh]')).forEach(function(b){
    b.addEventListener('click',refresh);
  });
})();
"""

ILLUS = """
<svg viewBox="0 0 268 196" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <clipPath id="ck3"><rect x="26" y="18" width="152" height="88" rx="14"/></clipPath>
  </defs>
  <!-- 后一张 -->
  <rect x="72" y="92" width="152" height="88" rx="14" fill="#E9E7E0" stroke="#0B0B0B" stroke-width="2.5"/>
  <path d="M92 150h58" stroke="#0B0B0B" stroke-width="2.5" stroke-linecap="round" opacity=".22"/>
  <!-- 中间一张 -->
  <rect x="49" y="55" width="152" height="88" rx="14" fill="#F8F7F3" stroke="#0B0B0B" stroke-width="2.5"/>
  <path d="M69 113h34" stroke="#0B0B0B" stroke-width="2.5" stroke-linecap="round" opacity=".22"/>
  <!-- 最前一张 -->
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


def render_card(item, idx, wide=False):
    num = "%02d" % idx
    return (
        '<article class="card reveal%s">'
        '<span class="no">%s</span>'
        '<h3>%s</h3>'
        '<div class="meta"><span class="src">%s</span>'
        '<span class="dot"></span><span>%s</span></div>'
        '<p>%s</p>'
        '<a class="link" href="%s" target="_blank" rel="noopener noreferrer">阅读全文 %s</a>'
        '</article>'
    ) % (" wide" if wide else "", num, esc(item.get("title")),
         esc(item.get("source")), esc(item.get("date")), esc(item.get("summary")),
         esc(item.get("url", "#")), ICON_ARROW)


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    sections = data.get("sections", [])
    stats = data.get("stats", [])
    date_str = data.get("date", "")
    weekday = data.get("weekday", "")
    fs = data.get("footerSource", {}) or {}

    total = sum(len(s.get("items", [])) for s in sections)

    # ---- 导航 ----
    nav = []
    for i, s in enumerate(sections, 1):
        sid = "sec%d" % i
        nav.append('<a href="#%s"%s>%s</a>' % (sid, ' class="on"' if i == 1 else "", esc(s.get("name"))))
    nav_html = "".join(nav)

    # ---- 数据条 ----
    stat_html = "".join(
        '<div class="stat"><b>%s</b><span>%s</span></div>' % (esc(s.get("num")), esc(s.get("label")))
        for s in stats
    )

    # 「收录信源」的数值，供珊瑚卡文案复用（找不到就退化为「多个中文信源」）
    src_note = "多个中文信息源"
    for s in stats:
        if "信源" in str(s.get("label", "")):
            src_note = "%s 个中文信息源" % s.get("num")
            break

    # 版本号用数据文件的实际生成时间，别硬编码
    import datetime
    mtime = datetime.datetime.fromtimestamp(DATA.stat().st_mtime)
    version = "%s %s" % (date_str, mtime.strftime("%H:%M"))

    # ---- 焦点卡片：取第一条作头条 ----
    lead = sections[0]["items"][0] if sections and sections[0].get("items") else {}
    lead_html = (
        '<div class="lead">'
        '<h3>%s</h3>'
        '<p>%s</p>'
        '<a class="link" href="%s" target="_blank" rel="noopener noreferrer">阅读全文 %s</a>'
        '</div>'
    ) % (esc(lead.get("title")), esc(lead.get("summary")), esc(lead.get("url", "#")), ICON_ARROW)

    # ---- 板块 ----
    body = []
    for i, s in enumerate(sections, 1):
        items = s.get("items", [])
        cards = "".join(
            render_card(it, j, wide=(j == 1)) for j, it in enumerate(items, 1)
        )
        body.append(
            ('<section class="section" id="sec%d">'
             '<div class="sec-head">'
             '<h2>%s</h2>'
             '<span class="chip">%d 条</span>'
             '<span class="idx">%02d / %02d</span>'
             '</div>'
             '<div class="cards">%s</div>'
             '</section>') % (i, esc(s.get("name")), len(items), i, len(sections), cards)
        )
    body_html = "".join(body)

    doc = TEMPLATE
    repl = {
        "{{CSS}}": CSS,
        "{{JS}}": JS,
        "{{NAV}}": nav_html,
        "{{DATE}}": esc(date_str),
        "{{WEEKDAY}}": esc(weekday),
        "{{TITLE}}": esc(data.get("title", "今日")),
        "{{SUBTITLE}}": esc(data.get("subtitle", "")),
        "{{TAGLINE}}": esc(data.get("tagline", "")),
        "{{STATS}}": stat_html,
        "{{LEAD}}": lead_html,
        "{{ILLUS}}": ILLUS,
        "{{BODY}}": body_html,
        "{{TOTAL}}": str(total),
        "{{NSEC}}": str(len(sections)),
        "{{FS_NAME}}": esc(fs.get("name", "")),
        "{{FS_URL}}": esc(fs.get("url", "#")),
        "{{ICON_REFRESH}}": ICON_REFRESH,
        "{{ICON_UP}}": ICON_UP,
        "{{ICON_ARROW}}": ICON_ARROW,
        "{{ICON_MINUS}}": ICON_MINUS,
        "{{ICON_PLUS}}": ICON_PLUS,
        "{{STATS_NOTE}}": src_note,
        "{{VERSION}}": version,
    }
    for k, v in repl.items():
        doc = doc.replace(k, v)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8", newline="\n")
    print("已生成预览: %s" % OUT)
    print("  字节: %d | 板块: %d | 卡片: %d" % (len(doc.encode("utf-8")), len(sections), total))


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI HOT · 日报 — UI 预览（bankon 风格）</title>
<style>{{CSS}}</style>
</head>
<body>
<script>document.documentElement.className+=' js-ready';</script>

<nav class="topnav" aria-label="板块导航">
  <div class="topnav-in">
    <div class="brand"><span class="mark"></span>AI HOT · 日报</div>
    <div class="nav-links">{{NAV}}</div>
    <div class="nav-right">
      <span class="nav-date">{{DATE}} · {{WEEKDAY}}</span>
      <button class="pill" type="button" data-refresh>{{ICON_REFRESH}}刷新</button>
    </div>
  </div>
</nav>

<header class="hero">
  <div class="wrap">
    <div class="hero-grid">
      <div class="hero-left">
        <div class="eyebrow"><span class="live"></span>{{DATE}} · {{WEEKDAY}} · 北京时间</div>
        <h1>{{TITLE}} <span class="hl">AI</span><span class="l2">{{SUBTITLE}}</span></h1>
      </div>
      <div class="hero-right">
        <p>{{TAGLINE}}</p>
        <div class="hero-cta">
          <button class="btn-dark" type="button" data-refresh>{{ICON_REFRESH}}刷新数据</button>
          <a class="btn-line" href="#sec1">浏览今日精选 {{ICON_ARROW}}</a>
        </div>
      </div>
    </div>
    <div class="stats">{{STATS}}</div>
  </div>
</header>

<main class="wrap">

  <div class="spot">
    <section class="feature reveal">
      <div class="feat-head">
        <h2>最新更新</h2>
        <span class="ver">v {{VERSION}}</span>
      </div>
      {{LEAD}}
      <div class="illus">{{ILLUS}}</div>
    </section>

    <div class="spot-right">
      <article class="accent-card reveal">
        <div class="row">
          <h3>今日收录</h3>
          <button class="circ" type="button" aria-label="查看统计" onclick="location.hash='#sec1'">{{ICON_MINUS}}</button>
        </div>
        <div>
          <div class="big">{{TOTAL}}</div>
          <p>来自 {{STATS_NOTE}}，当日精选全部由本地脚本抓取，零 AI 调用。</p>
        </div>
      </article>
      <article class="mini reveal">
        <div>
          <h3>共 {{NSEC}} 大板块</h3>
          <div class="sub">模型 · 产品 · 行业 · 研报 · 观点</div>
        </div>
        <button class="circ" type="button" aria-label="展开板块" onclick="location.hash='#sec1'">{{ICON_PLUS}}</button>
      </article>
    </div>
  </div>

  {{BODY}}

</main>

<footer class="footer">
  <div class="wrap foot">
    <div class="grp">
      <span>共 <strong>{{TOTAL}}</strong> 条</span>
      <span class="dot"></span>
      <span>{{NSEC}} 大板块</span>
      <span class="dot"></span>
      <span>{{DATE}} 北京时间</span>
    </div>
    <span>数据来自 <a href="{{FS_URL}}" target="_blank" rel="noopener noreferrer">{{FS_NAME}}</a></span>
  </div>
</footer>

<button class="to-top" type="button" aria-label="回到顶部">{{ICON_UP}}</button>
<div class="toast" role="status" aria-live="polite"></div>
<div class="badge-preview"><span class="dotpy"></span>UI 预览 · 未上线</div>

<script>{{JS}}</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
