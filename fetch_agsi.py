<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>① 限界燃料モニター</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
 body{font-family:"Segoe UI",Arial,sans-serif;background:#101623;color:#E8E8E8;margin:0;padding:18px}
 h1{font-size:19px;color:#FFF;margin:4px 0 2px;display:inline-block}
 .zones{display:inline-block;margin-left:14px;vertical-align:middle}
 .zones a{color:#9AA5B5;text-decoration:none;font-size:13px;padding:3px 10px;border:1px solid #2A3550;border-radius:6px;margin-right:6px}
 .zones a.on{color:#FFF;background:#22304A}
 .sub{color:#9AA5B5;font-size:12px;margin-bottom:14px}
 .card{background:#1A2334;border:1px solid #2A3550;border-radius:10px;padding:14px 16px;margin-bottom:14px}
 .ct{font-size:14px;font-weight:600;color:#DCE4F2;margin-bottom:8px}
 .note{font-size:11px;color:#8B96A8;margin-top:6px}
 .warn{color:#E8A838}
 .ribbon{display:flex;height:34px;border-radius:4px;overflow:hidden;margin:6px 0}
 .ribbon div{flex:1;position:relative}
 .ribbon div.unres::after{content:"";position:absolute;bottom:0;left:0;right:0;height:6px;background:rgba(255,255,255,.75)}
 .legend{font-size:11px;color:#B8C2D2;display:flex;gap:14px;flex-wrap:wrap;margin-top:4px}
 .sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle}
 .grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
 @media(max-width:900px){.grid2{grid-template-columns:1fr}}
 table{border-collapse:collapse;font-size:12px;width:100%}
 td,th{border:1px solid #2A3550;padding:4px 8px;text-align:center}
 th{background:#22304A;color:#DCE4F2}
 select{background:#22304A;color:#DCE4F2;border:1px solid #2A3550;border-radius:6px;padding:3px 8px;font-size:12px}
</style>
</head>
<body>
<h1>① 限界燃料モニター</h1>
<span class="zones" id="zones"></span>
<div class="sub" id="sub">読込中…</div>

<div class="card">
 <div class="ct">🔬 DA価格 vs SRMC帯 — コマ別 <select id="daySel"></select></div>
 <canvas id="priceChart" height="90"></canvas>
 <div class="note" id="bandNote"></div>
</div>

<div class="card">
 <div class="ct">🎯 限界燃料リボン — コマ別ラベル</div>
 <div class="ribbon" id="ribbon"></div>
 <div class="legend" id="legend"></div>
 <div class="note">下端の白帯 = <span class="warn">UNRESOLVED</span> (帯内だが該当機非稼働・輸入収斂も不成立)。</div>
</div>

<div class="grid2">
 <div class="card">
  <div class="ct">📊 日次 限界燃料シェア — 積み上げ</div>
  <canvas id="shareChart" height="180"></canvas>
 </div>
 <div class="card">
  <div class="ct">🧾 日次サマリー</div>
  <table id="sumTable"></table>
  <div class="note">データ: docs/data/marginal_fuel_daily_{zone}.json (GitHub Actionsが毎朝更新)</div>
 </div>
</div>

<script>
const COLOR = {res_surplus:"#2E9E6F", lignite:"#8B5E3C", ccgt:"#E8A838", coal:"#7A7A7A", ocgt:"#C0504D", scarcity:"#A32D2D", import_set:"#4A90D9"};
const JP = {res_surplus:"再エネ余剰", lignite:"褐炭", ccgt:"CCGT", coal:"石炭", ocgt:"OCGT", scarcity:"逼迫", import_set:"輸入連動"};
const ZONES_UI = ["DE_LU","GB"];
const zone = new URLSearchParams(location.search).get("zone") || "DE_LU";
const CUR = zone === "GB" ? "GBP/MWh" : "EUR/MWh";
let charts = [];

document.getElementById("zones").innerHTML = ZONES_UI.map(z =>
  `<a href="?zone=${z}" class="${z===zone?'on':''}">${z.replace("_","-")}</a>`).join("");

async function load(){
  let D = null;
  try{
    const r = await fetch(`data/marginal_fuel_daily_${zone}.json`, {cache:"no-store"});
    if(r.ok) D = await r.json();
  }catch(e){ console.warn(e); }
  if(!D || !D.days || !D.days.length){
    document.getElementById("sub").textContent =
      "データ未生成: GitHub Actions (daily-fetch-label) を一度実行してください。実行後このページに反映されます。";
    return;
  }
  const fa = D.fuel_assumptions||{};
  document.getElementById("sub").textContent =
    `${D.zone} ｜ SRMCラダー2段判定 + 輸入収斂 ｜ 燃料前提: TTF ${fa.ttf} / API2 ${fa.api2} / EUA ${fa.eua}` +
    (zone==="GB"?` / UKA ${fa.uka}+CPS18`:"") + ` (${fa.note||""}) ｜ 出典: energy-charts.info・SMARD (CC BY 4.0)・Elexon ｜ 【欧州電力分析】`;

  const sel = document.getElementById("daySel");
  sel.innerHTML = D.days.map((d,i)=>`<option value="${i}" ${i===D.days.length-1?"selected":""}>${d.date}</option>`).join("");
  sel.onchange = ()=>renderDay(D, +sel.value);
  renderDay(D, D.days.length-1);
  renderShares(D);
  renderTable(D);
}

function renderDay(D, idx){
  charts.forEach(c=>c.destroy()); charts = charts.filter(c=>c.canvas.id!=="priceChart");
  const d0 = D.days[idx];
  const hrs = d0.qh.price.map((_,i)=>i);
  const perHour = Math.round(d0.qh.price.length/24) || 1;
  const bandDS = Object.entries(D.bands).flatMap(([n,[lo,hi]])=>[
   {label:n+" 帯", data:hrs.map(()=>hi), fill:"+1", backgroundColor:(COLOR[n]||"#999")+"22", borderWidth:0, pointRadius:0},
   {label:"_", data:hrs.map(()=>lo), fill:false, borderWidth:0, pointRadius:0}]);
  const pc = new Chart(priceChart,{type:"line",
   data:{labels:hrs, datasets:[
    {label:"DA価格 (実)", data:d0.qh.price, borderColor:"#FFFFFF", borderWidth:1.8, pointRadius:0, fill:false},
    {label:"余剰上限", data:hrs.map(()=>15), borderColor:"#2E9E6F", borderDash:[5,4], borderWidth:1, pointRadius:0, fill:false},
    ...bandDS]},
   options:{animation:false, plugins:{legend:{labels:{color:"#B8C2D2", filter:i=>!i.text.startsWith("_")}}},
    scales:{x:{ticks:{color:"#8B96A8", maxTicksLimit:13, callback:(v,i)=> i%(perHour*2)==0? (i/perHour)+"時":""}, grid:{color:"#232D44"}},
            y:{title:{display:true,text:CUR,color:"#8B96A8"}, ticks:{color:"#8B96A8"}, grid:{color:"#232D44"}}}}});
  charts.push(pc);
  document.getElementById("bandNote").textContent =
    "帯 = 効率レンジ由来 (CCGT η0.47-0.58 等)。緑破線 = 余剰上限 15/MWh。表示日: " + d0.date;

  const rb = document.getElementById("ribbon"); rb.innerHTML = "";
  d0.qh.label.forEach((l,i)=>{const s=document.createElement("div");
   s.style.background=COLOR[l]||"#999"; if(d0.qh.unresolved[i]) s.className="unres";
   s.title=(i/perHour).toFixed(2)+"h  "+d0.qh.price[i]+"  "+(JP[l]||l); rb.appendChild(s);});
  document.getElementById("legend").innerHTML =
   Object.keys(COLOR).filter(k=>d0.qh.label.includes(k)||["import_set","scarcity"].includes(k))
   .map(k=>`<span><span class="sw" style="background:${COLOR[k]}"></span>${JP[k]}</span>`).join("");
}

function renderShares(D){
  const labels = D.days.map(d=>d.date);
  const fuels = [...new Set(D.days.flatMap(d=>Object.keys(d.shares)))];
  charts.push(new Chart(shareChart,{type:"bar",
   data:{labels, datasets:fuels.map(f=>({label:JP[f]||f, data:D.days.map(d=>(d.shares[f]||0)*100), backgroundColor:COLOR[f]||"#999"}))},
   options:{animation:false, plugins:{legend:{labels:{color:"#B8C2D2"}}},
    scales:{x:{stacked:true,ticks:{color:"#8B96A8", maxTicksLimit:16},grid:{color:"#232D44"}},
            y:{stacked:true,max:100,title:{display:true,text:"%",color:"#8B96A8"},ticks:{color:"#8B96A8"},grid:{color:"#232D44"}}}}}));
}

function renderTable(D){
  const tail = D.days.slice(-14).reverse();
  sumTable.innerHTML = "<tr><th>日付</th><th>DA平均</th><th>最小</th><th>最大</th><th>UNRESOLVED率</th></tr>" +
   tail.map(d=>`<tr><td>${d.date}</td><td>${d.stats.da_avg}</td><td>${d.stats.da_min}</td><td>${d.stats.da_max}</td><td class="warn">${(d.stats.unresolved_rate*100).toFixed(0)}%</td></tr>`).join("");
}

load();
</script>
</body>
</html>
