"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (value, digits=3) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("en-US", {maximumFractionDigits:digits, minimumFractionDigits:digits}) : "—";
const labels = {balanced:"均衡", power:"低功耗", area:"小面積", latency:"低延遲"};
const metricNames = {power:"Power", area:"Area", latency:"Latency"};
const strategies = {single:"Single", output_channel:"Output channel", input_channel:"Input channel"};
const kinds = {dependency_transfer:"Block 間傳輸", input_distribution:"輸入分配", internal_redistribution:"Block 內重分配", partial_output_reduction:"Partial sum reduction", identity_shortcut_gather:"Identity gather"};
let config, job, activeModel, currentResult, renderedKey="", token="", pollTimer;
const emptyInitial = $("empty-state").innerHTML;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json","X-DSE-Token":token},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function weights() {
  const name = document.querySelector('input[name="preference"]:checked').value;
  const [l,a,p] = config.preferences[name];
  $("weight-note").textContent = `Power ${fmt(p,2)} / Area ${fmt(a,2)} / Latency ${fmt(l,2)}`;
}
function requestData() {
  return {models:[...document.querySelectorAll('input[name="model"]:checked')].map(e=>e.value),
    preference:document.querySelector('input[name="preference"]:checked').value,
    limits:{power_w:Number($("power").value),area_mm2:Number($("area").value),latency_ms:Number($("latency").value)},
    strict:Object.fromEntries(["power","area","latency"].map(m=>[m,$("strict-"+m).checked])),
    budget:Number($("budget").value),seed:Number($("seed").value)};
}
function loadRequest(data) {
  $("power").value=data.limits.power_w; $("area").value=data.limits.area_mm2; $("latency").value=data.limits.latency_ms;
  ["power","area","latency"].forEach(m=>$("strict-"+m).checked=data.strict[m]);
  document.querySelectorAll('input[name="preference"]').forEach(e=>e.checked=e.value===data.preference);
  document.querySelectorAll('input[name="model"]').forEach(e=>e.checked=data.models.includes(e.value));
  $("budget").value=data.budget; $("seed").value=data.seed; weights();
}
function busy(value) {
  $("inputs").disabled=value; $("run").disabled=value;
  $("run").textContent=value?"正在探索…":"開始探索 ↗";
  $("cancel").hidden=!value; $("cancel").disabled=!!job?.cancel;
  $("cancel").textContent=job?.cancel?"正在取消…":"取消搜尋";
}
async function start(event) {
  event.preventDefault();
  $("form-error").textContent="";
  const data=requestData();
  if (!data.models.length) {$("form-error").textContent="請至少選擇一個模型。";return;}
  busy(true);
  try {
    const next=await api("/api/jobs",data);
    job=next; activeModel=null; currentResult=null; renderedKey="";
    $("result-content").hidden=true; $("comparison").hidden=true; $("model-tabs").replaceChildren();
    $("exports").hidden=true; $("empty-state").innerHTML=emptyInitial; $("empty-state").hidden=false;
    $("job-note").hidden=true;
    localStorage.setItem("chipletLabJob",job.id);
    updateJob(); schedulePoll();
  } catch(error) {$("form-error").textContent=error.message;busy(false);}
}
function schedulePoll() {clearTimeout(pollTimer);pollTimer=setTimeout(poll,900);}
async function poll() {
  if(!job)return;
  const id=job.id;
  try {
    const next=await api(`/api/jobs/${id}`);
    if(job.id!==id)return;
    job=next; $("connection").textContent="本機已連線"; updateJob();
    if(job.status==="running")schedulePoll();
  } catch(error) {
    $("connection").textContent="連線中斷";
    $("job-note").hidden=false;$("job-note").className="notice warning";
    $("job-note").textContent=`無法更新進度：${error.message}。正在重試；可確認 GUI 伺服器仍在執行。`;
    schedulePoll();
  }
}
function modelLabel(name) {return config.models.find(m=>m.name===name)?.label || name;}
function updateJob() {
  const running=job.status==="running", p=job.progress;
  busy(running); $("progress-box").hidden=false;
  $("progress").max=p.budget||job.request.budget; $("progress").value=p.evaluations||0;
  $("progress-text").textContent=`${modelLabel(p.model||job.request.models[0])} · ${running?(p.phase==="preparing"?"建立合法動作":"搜尋中"):"搜尋已結束"}`;
  $("progress-number").textContent=`${p.evaluations||0} / ${p.budget||job.request.budget}`;
  $("result-heading").textContent=running?`探索中 · ${job.results.length} / ${job.request.models.length} 個模型完成`:job.status==="cancelled"?"搜尋已取消":"探索結果";
  $("exports").hidden=!job.download_ready;
  $("export-json").href=`/api/jobs/${job.id}/results.json`;
  $("export-csv").href=`/api/jobs/${job.id}/summary.csv`;
  const key=job.id+":"+job.results.length+":"+job.status;
  if(key!==renderedKey){
    renderedKey=key;
    if(!job.results.some(r=>r.model===activeModel))activeModel=job.results[0]?.model;
    renderTabs();renderResult();renderComparison();
  }
  if(job.errors.length){
    $("job-note").hidden=false;$("job-note").className="notice warning";
    $("job-note").textContent=job.errors.map(e=>`${modelLabel(e.model)}：${e.message}`).join("；");
  } else if(!running){
    $("job-note").hidden=false;$("job-note").className="notice";
    const strict=Object.entries(job.request.strict).filter(([,v])=>v).map(([m])=>metricNames[m]);
    $("job-note").textContent=`${job.status==="cancelled"?"搜尋已取消，保留已完成模型的結果。":"本次探索已完成。"} 嚴格遵守：${strict.join("、")||"無（三項均為軟限制）"}。偏好：${labels[job.request.preference]}。`;
  }else{$("job-note").hidden=true;}
}
function renderTabs(){
  $("model-tabs").replaceChildren();
  job.results.forEach(r=>{
    const b=document.createElement("button");b.type="button";b.className="model-tab";b.role="tab";
    b.textContent=modelLabel(r.model)+(r.best_candidate?"":" · 無符合設計");
    b.setAttribute("aria-selected",String(r.model===activeModel));
    b.onclick=()=>{activeModel=r.model;renderTabs();renderResult();};$("model-tabs").append(b);
  });
}
function row(label,value,total=false){return `<div class="value-row${total?" total-row":""}"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;}
function renderResult(){
  currentResult=job?.results.find(r=>r.model===activeModel);
  if(!currentResult)return;
  const r=currentResult,c=r.best_candidate,b=r.best_breakdown;
  $("result-content").hidden=!c;$("empty-state").hidden=!!c;
  if(!c){
    const violations=r.policy_rollout.reward?.hard_violations||[];
    $("empty-state").innerHTML=`<div class="empty-icon">∅</div><h2>本次預算內，沒有找到符合嚴格限制的設計。</h2><p>${esc(modelLabel(r.model))} · 已評估 ${r.unique_evaluations} 個不同設計，${r.episodes} episodes。</p><p>嚴格超標設計已排除，不會顯示成推薦配置。<br>可提高搜尋預算、調整限制，或取消對應的嚴格選項。</p><p class="hint">這不代表整個設計空間無解。${violations.length?"學得路徑的拒絕原因："+esc(violations.join("、")):""}</p>`;
    return;
  }
  $("result-status").className="pill "+(b.feasible?"good":"warning");
  $("result-status").textContent=b.feasible?"三項 PPA 均達標":"可接受 · 含軟限制超標";
  $("result-subtitle").textContent=`${c.selected_chiplets} chiplets · ${r.unique_evaluations} 個設計 · backend: ${c.backend}`;
  const metrics=[{key:"power",label:"Power（Batch-1 平均）",value:c.total_power_w,limit:r.preference.max_power_w,unit:"W"},
    {key:"area",label:"Area（配置外框）",value:c.total_area_mm2,limit:r.preference.max_area_mm2,unit:"mm²"},
    {key:"latency",label:"Batch-1 Latency",value:c.avg_latency_ns/1e6,limit:r.preference.max_latency_ns/1e6,unit:"ms"}];
  $("metrics").innerHTML=metrics.map(m=>{
    const over=m.value>m.limit;return `<div class="metric"><div class="metric-label"><span>${m.label}</span><span>${r.preference["strict_"+m.key]?"嚴格":"軟限制"}</span></div><div class="metric-value${over?" over":""}">${fmt(m.value)}<small>${m.unit}</small></div><div class="metric-note${over?" over":""}">上限 ${fmt(m.limit,2)} · ${over?"超出":"餘裕"} ${fmt(Math.abs(m.value/m.limit-1)*100,1)}%</div></div>`;
  }).join("");
  $("graph-caption").textContent=`${c.topology} · ${c.connection_graph.physical_links.length} 實體 links · 座標及 die 尺寸以 mm 表示`;
  $("zoom").value=100;$("placement-svg").style.width="100%";
  $("event-select").innerHTML='<option value="physical">僅實體連線</option><option value="all">整次推論 · 累積 traffic（非同時傳輸）</option>'+
    c.communication_events.map((e,i)=>`<option value="${i}">#${e.event_id} ${esc(kinds[e.kind]||e.kind)} · ${esc(e.tensor)}</option>`).join("");
  $("chiplet-info").textContent="點選 chiplet 查看配置、座標與工作量。";
  drawGraph();
  $("power-area-breakdown").innerHTML=row("Batch-1 平均功率",fmt(c.power_avg_batch1_w,6)+" W",true)+
    row("Energy / inference",fmt(c.energy_per_inference_j*1e3,6)+" mJ")+
    row("Static energy",fmt(c.static_energy_j*1e3,6)+" mJ")+
    row("Compute dynamic energy",fmt(c.compute_dynamic_energy_j*1e3,6)+" mJ")+
    row("Link dynamic energy",fmt(c.link_dynamic_energy_j*1e6,3)+" µJ")+
    row("Batch-1 observation window",fmt(c.power_observation_window_s*1e3,6)+" ms")+
    row("Static power（chiplet／PHY／links／router）",fmt(c.static_power_w,6)+" W")+
    row("Fixed-utilization hardware power estimate",fmt(c.power_fixed_utilization_w,6)+" W")+
    row("Die 面積總和",fmt(c.total_chiplet_area_mm2,3)+" mm²")+
    row("配置外框（PPA Area）",fmt(c.total_area_mm2,3)+" mm²");
  $("latency-breakdown").innerHTML=row("Compute",fmt(c.e2e_compute_latency_ns/1e6)+" ms")+
    row("Link serialization",fmt(c.e2e_communication_serialization_ns/1e6)+" ms")+
    row("Path delay",fmt(c.e2e_communication_path_latency_ns/1e6,6)+" ms")+
    row("Batch-1 E2E",fmt(c.avg_latency_ns/1e6)+" ms",true)+row("Pipeline FPS（僅輸出）",fmt(c.achieved_fps));
  $("reward-breakdown").innerHTML=row("Base reward",fmt(b.base_reward,5))+row("Bonus", "+ "+fmt(b.bonus,5))+
    row("Penalty","− "+fmt(b.penalty,5))+row("Reward",fmt(b.reward,5),true)+
    row("軟限制超標",b.violated_constraints.map(m=>metricNames[m]||m).join("、")||"無");
  $("mapping-table").innerHTML=c.mapping_plan.groups.map(g=>`<tr><td>G${g.group_index}</td><td class="wrap">${esc(c.block_graph.nodes.slice(g.start_block,g.end_block).map(n=>n.name).join(" → "))}</td><td>${g.chiplets}</td><td>${esc(strategies[g.strategy])}</td><td>${fmt(g.memory_per_chiplet_mb,2)} / ${fmt(c.effective_hardware.chiplet.sram_mb,0)} MiB</td></tr>`).join("");
  const m=r.model_metadata;
  const stopping={evaluation_budget:"已用完評估預算",episode_limit:"已達 episode 上限",design_space_exhausted:"已評估全部合法設計"};
  $("audit-details").innerHTML=`<p>${esc(m.description)}</p><p>參數 ${fmt(m.parameters,0)} · FP32 權重 ${fmt(m.fp32_weights_mib,3)} MiB · Conv/Linear MAC ${fmt(m.macs_g,6)} G · ${m.blocks} blocks</p><p>PyTorch ${esc(m.calibration.torch)} / torchvision ${esc(m.calibration.torchvision)}；實際 CPU forward 已校驗，未載入預訓練權重，未評量準確率。<a href="${esc(m.calibration.source)}" target="_blank" rel="noopener">官方架構來源 ↗</a></p><p>停止原因：${esc(stopping[r.stopping_reason]||r.stopping_reason)} · ${r.episodes} episodes · seed ${r.seed}<br>搜尋空間 ${fmt(r.design_space_size,0)}；已評估 ${r.unique_evaluations}。${r.global_optimum_certified?"已完整枚舉此受限空間。":"結果為已評估設計中的最佳值，不保證全域最佳。"}<br>Q greedy policy 與最佳已評估 reward：${r.policy_rollout.matches_best_reward?"相符":"不同"}。固定 mesh 座標；RL 未搜尋任意拓撲或擺放。</p><p>權重、利用率、mapping 效率與記憶體為分析模型。Power 使用 Batch-1 能量／觀測時間；active time 依 assigned OPS 與 mapping efficiency 推估，非實測。75% utilization 僅用於 active compute。PHY 視為常駐；FPS 不參與功率或 reward。</p>`;
}
function svgNode(tag,attrs={},text){
  const e=document.createElementNS("http://www.w3.org/2000/svg",tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));
  if(text!==undefined)e.textContent=text;return e;
}
function drawGraph(){
  const c=currentResult?.best_candidate;if(!c)return;
  const svg=$("placement-svg"),graph=c.connection_graph,w=c.effective_hardware.chiplet.width_mm;
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),groupOf=new Map();let cursor=0;
  c.mapping_plan.groups.forEach(g=>{for(let j=0;j<g.chiplets;j++)groupOf.set(cursor++,g);});
  const maxX=Math.max(...graph.nodes.map(n=>n.x))+w,maxY=Math.max(...graph.nodes.map(n=>n.y))+w,margin=1.1;
  svg.replaceChildren();svg.setAttribute("viewBox",`${-margin} ${-margin} ${maxX+2*margin} ${maxY+2*margin}`);
  svg.append(svgNode("title",{},`${modelLabel(currentResult.model)}：${nodes.size} chiplets，真實座標 (mm)`));
  const defs=svgNode("defs"),marker=svgNode("marker",{id:"arrow",viewBox:"0 0 10 10",refX:8,refY:5,markerWidth:5,markerHeight:5,orient:"auto-start-reverse"});
  marker.append(svgNode("path",{d:"M 0 0 L 10 5 L 0 10 z",fill:"#2d59d0"}));defs.append(marker);svg.append(defs);
  graph.nodes.forEach(n=>{
    const g=groupOf.get(n.id),rect=svgNode("rect",{x:n.x,y:n.y,width:w,height:w,rx:.18,class:`die g${g.group_index%6}`,tabindex:0,role:"button","aria-label":`Chiplet ${n.id}, group ${g.group_index}`});
    rect.append(svgNode("title",{},`C${n.id} · G${g.group_index} · (${fmt(n.x,4)}, ${fmt(n.y,4)}) mm\n${n.stage}`));
    const inspect=()=>{$("chiplet-info").textContent=`C${n.id} · G${g.group_index} · ${strategies[g.strategy]} · 座標 (${fmt(n.x,4)}, ${fmt(n.y,4)}) mm · 尺寸 ${fmt(w,4)} × ${fmt(w,4)} mm · ${fmt(n.ops/1e9,4)} Gops · SRAM ${fmt(g.memory_per_chiplet_mb,3)} MiB。Blocks：${n.stage}`;};
    rect.addEventListener("click",inspect);rect.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();inspect();}});svg.append(rect);
  });
  const point=id=>{const n=nodes.get(id);return [n.x+w/2,n.y+w/2];};
  graph.physical_links.forEach(e=>{
    const [x1,y1]=point(e.source),[x2,y2]=point(e.target);
    const line=svgNode("line",{x1,y1,x2,y2,class:"physical","pointer-events":"none"});
    line.append(svgNode("title",{},`C${e.source} ↔ C${e.target} · ${fmt(e.length_mm,4)} mm`));svg.append(line);
  });
  const selection=$("event-select").value;
  let flows=[],event=null;
  if(selection==="all")flows=graph.routed_traffic.map(f=>({...f,bits:f.mb*8*1024**2}));
  else if(selection!=="physical"){event=c.communication_events[Number(selection)];flows=event?.flows||[];}
  flows.forEach(f=>{
    const path=svgNode("polyline",{points:f.path.map(id=>point(id).join(",")).join(" "),class:"traffic","marker-end":"url(#arrow)","pointer-events":"none"});svg.append(path);
  });
  graph.nodes.forEach(n=>{
    const [cx,cy]=point(n.id);svg.append(svgNode("circle",{cx,cy,r:.10,class:"port","pointer-events":"none"}));
    svg.append(svgNode("text",{x:n.x+.65,y:n.y+1.35,class:"die-label"},`C${n.id}`));
    svg.append(svgNode("text",{x:n.x+.65,y:n.y+w-1.35,class:"die-sub"},`G${groupOf.get(n.id).group_index} · ${groupOf.get(n.id).strategy==="single"?"Single":groupOf.get(n.id).strategy==="output_channel"?"OC":"IC"}`));
    svg.append(svgNode("text",{x:n.x+.65,y:n.y+w-.60,class:"die-sub"},`${fmt(n.x,2)}, ${fmt(n.y,2)} mm`));
  });
  $("group-legend").innerHTML='<span class="physical-key">實體 link（中心 PHY）</span>'+c.mapping_plan.groups.map(g=>`<span class="g${g.group_index%6}">G${g.group_index} · ${g.chiplets} chiplets</span>`).join("");
  if(selection==="physical")$("route-info").textContent="外框為實際 die 尺寸；線段連接中心 PHY。選擇 traffic 可查看 tensor 經過的實體路徑。";
  else if(!flows.length)$("route-info").textContent="此設計所有計算與資料交換均在同一 chiplet 內，沒有跨 chiplet traffic。";
  else {
    const total=flows.reduce((s,f)=>s+f.bits,0)/(8*1024**2);
    $("route-info").textContent=`${event?`${kinds[event.kind]||event.kind} · ${event.tensor}`:"整次推論的累積流量，並非同時傳送"} · ${flows.length} 條 unicast · ${fmt(total,5)} MiB。路由：`+flows.map(f=>`${f.path.map(n=>"C"+n).join(" → ")} (${fmt(f.bits/(8*1024**2),5)} MiB)`).join("；");
  }
}
function renderComparison(){
  $("comparison").hidden=job.results.length<2;
  $("comparison-table").innerHTML=job.results.map(r=>{const c=r.best_candidate;return `<tr><td>${esc(modelLabel(r.model))}</td><td>${c?(r.best_breakdown.feasible?"均達標":"含軟超標"):"無符合設計"}</td><td>${c?.selected_chiplets??"—"}</td><td>${fmt(c?.total_power_w)}</td><td>${fmt(c?.total_area_mm2)}</td><td>${fmt(c?c.avg_latency_ns/1e6:null)}</td></tr>`;}).join("");
}
function exportSvg(){
  const a=document.createElement("a");
  a.href=`/api/jobs/${job.id}/placement.svg?model=${encodeURIComponent(currentResult.model)}&event=${encodeURIComponent($("event-select").value)}`;
  a.download=currentResult.model+"-placement.svg";document.body.append(a);a.click();a.remove();
}
async function init(){
  try{
    config=await api("/api/config");token=config.token;
    $("model-options").innerHTML=config.models.map(m=>`<label class="model-option"><input type="checkbox" name="model" value="${esc(m.name)}" ${m.name==="resnet50"?"checked":""}><span><strong>${esc(m.label)}</strong><small>${fmt(m.parameters/1e6,2)} M params · ${fmt(m.macs_g,3)} G MAC<br>${esc(m.description)}</small></span></label>`).join("");
    loadRequest({models:["resnet50"],preference:"balanced",limits:config.limits,strict:config.strict,budget:config.budget,seed:config.seed});
    const h=config.hardware;
    $("hardware-values").innerHTML=Object.entries({"PE / chiplet":`${h.chiplet.pe_rows} × ${h.chiplet.pe_cols}`,"Frequency":`${fmt(h.chiplet.frequency_hz/1e6,0)} MHz`,"SRAM":`${h.chiplet.sram_mb} MiB`,"Utilization":`${h.chiplet.utilization*100}%`,"Chiplet upper bound":h.max_chiplets,"Link bandwidth":`${h.network.link_bandwidth_bits_per_cycle} bits/cycle/direction`,"Chiplet fixed-utilization power":`${fmt(h.power.chiplet_static_w+h.power.chiplet_peak_dynamic_w*h.chiplet.utilization+h.power.phy_w,4)} W`}).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
    $("connection").textContent="本機已連線";$("run").disabled=false;
    const previous=localStorage.getItem("chipletLabJob");
    if(previous){try{job=await api(`/api/jobs/${previous}`);loadRequest(job.request);updateJob();if(job.status==="running")schedulePoll();}catch{localStorage.removeItem("chipletLabJob");}}
  }catch(error){$("form-error").textContent=`無法載入設定：${error.message}`;$("connection").textContent="連線失敗";}
}
$("search-form").addEventListener("submit",start);
document.querySelectorAll('input[name="preference"]').forEach(e=>e.addEventListener("change",weights));
$("select-all").onclick=()=>{const nodes=[...document.querySelectorAll('input[name="model"]')],all=nodes.every(e=>e.checked);nodes.forEach(e=>e.checked=!all);};
$("cancel").onclick=async()=>{try{job=await api(`/api/jobs/${job.id}/cancel`,{});updateJob();}catch(e){$("form-error").textContent=e.message;}};
$("event-select").onchange=drawGraph;
$("zoom").oninput=()=>{$("placement-svg").style.width=$("zoom").value+"%";$("placement-svg").style.maxHeight="none";};
$("export-svg").onclick=exportSvg;
init();
