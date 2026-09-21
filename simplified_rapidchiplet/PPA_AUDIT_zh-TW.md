# 0920：對照原版 RapidChiplet 的 PPA 審核

## 結論與核對來源

使用者指定原版：`C:/Users/user/Documents/GitHub/rapidchiplet`，commit `17176f92c91eda629a25bc11bf7959d6b963a23b`。實際匯入該目錄執行，沒有修改原版。四個核心檔案逐檔比較，忽略 CRLF/LF 後與下載包使用的官方版本相同。

目前主功率已依使用者採納的建議改為 Batch-1 能量／觀測時間，固定利用率模型保留為 diagnostic。相同硬體 area 仍可相同；不同 workload 的平均 W 不要求一定不同，差異依估計活動比例與通訊決定。

重現：`python tools/audit_ppa.py --rapid-root C:/Users/user/Documents/GitHub/rapidchiplet`。外部路徑只用於此次對照；可攜包仍使用自身 `.runtime`。原始數值、原版檔案 SHA-256、人工控制變因測試見 [ppa_original_audit.json](validation/ppa_original_audit.json)。

## Power：Batch-1 平均功率與原版 diagnostic

原版 `rapidchiplet.py:162` 的 `compute_power_summary` 將輸入 chiplet power 加總，另加 active interposer router power。182–193 行計算 link power 後沒有放進回傳 total；我們既有轉接層有補回 static link power，原版原始碼未修改。

原版加上此補回項的固定模型保留為 `power_fixed_utilization_w`：

```
P_fixed = N × (0.15 + 0.85×0.75 + 0.03) + sum(length_mm × 0.005)
```

主 PPA `total_power_w` 現在改成：

```
t_active,i = assigned_OPS_i / (19.2 GOPS × mapping_efficiency_i)
P_static = N × (0.15 + 0.03) + static_link_W + static_router_W
E_compute = sum(0.85 × 0.75 × t_active,i)
E_link = sum(flow_bits × route_hops) × 0.5e-12 J
E_total = P_static × T_Batch1 + E_compute + E_link
P_avg = E_total / T_Batch1
```

Compute dynamic 不在 idle／communication／等待時間收取，PHY 暫視為每 chiplet 一項 static。所有時間沿用目前 Batch-1 模型；沒有引入 FPS、e_MAC 或額外 MAC ratio。`total_chiplet_power_w`／`total_link_power_w` 現在為同一 Batch-1 窗口下平均分項，舊 chiplet 固定項在 `chiplet_fixed_utilization_power_w`。

這是 workload-aware 解析估計，非實測平均或 peak/TDP。仍未校準 SRAM／DRAM 存取能量、clock gating、資料切換率、DVFS與溫度。延長等待時間可能稀釋平均動態 W，卻增加 static energy，故同時顯示 energy 與 latency。詳細採用方式、保留假設、測試及附件逐項對照見 [BATCH1_POWER_zh-TW.md](BATCH1_POWER_zh-TW.md)。

## Area：配置外框，不是模型大小

原版 `compute_area`（111 行）輸出兩種面積：

```
A_die_sum = sum(width_i × height_i)
A_footprint = (max(x_i + width_i) - min(x_i))
            × (max(y_i + height_i) - min(y_i))
```

目前 PPA／GUI 使用 `total_interposer_area`，即 A_footprint。另輸出 `total_chiplet_area_mm2`。每顆寬度 8.79772697916911 mm，die 面積 77.4 mm²；mesh pitch=寬度+0.15 mm。9 顆 3×3 mesh：die 總和 696.6 mm²、外框 712.525909 mm²。

這與原版幾何算法一致。不同 workload 使用同規格的 9 顆 chiplets，area 應相同；權重大小會影響 SRAM 可行性與所需 chiplet 數量，並不直接變成製造面積。

目前忽略：SRAM 容量、PE 數、PHY 數改動與 die 面積的耦合；額外 I/O die、DRAM、封裝邊界／keepout、散熱與電源網路。非完整矩形的 mesh 會把外框中的空位算進去；「最多16顆、選用9顆」目前是配置9顆的硬體設計，不是已製造16顆而只啟用9顆。面積值亦不是 die 面積和 interposer 面積相加。

## Latency：原版網路路徑與新增 Batch-1 模型

原版 `compute_latency`（292 行）只估算 inter-chiplet path。對一路徑：

```
C_path = 3 + 2 × (internal + PHY)
       + relay_count × (internal + 2 × PHY)
       + sum(ceil(link_base + link_cycles_per_mm × length_mm))
Rapid_avg = sum(flow_bits × C_path) / sum(flow_bits)
```

目前 internal=3 cycles、PHY=12 cycles、link_base=1、link_cycles_per_mm=0.25；最短 hop 數、同距離依 node ID 選路。一條相鄰 mesh link 長 8.947727 mm：link=ceil(3.236932)=4 cycles，整條一跳路徑=37 cycles=185 ns（200 MHz）。原版 link 長度本來依 PHY 座標計算；我們把 PHY 全設在 chiplet 中心，所以目前是中心到中心距離，不是兩顆 die 間 0.15 mm 的純封裝走線。

原版這個 avg 不含 DNN compute、不含封包／tensor serialization，也不含 traffic queueing。通訊量全數乘2時，加權平均 path latency 不會改變。原版 bandwidth 本來由 bumps 等幾何參數推導並切分方向；我們明確提供每方向 **256 bits/cycle** 的 intermediary，因此沒有使用那段推導公式，亦不再除2。

GUI／PPA latency 則是新增的 Batch-1 串行估計：

```
OPS_usable = 8 × 8 × 2 × 200 MHz × 0.75 = 19.2 GOPS/chiplet
T_compute,g = (group_MACs × 2 / chiplet_count_g) / (OPS_usable × efficiency_g)
T_serial,event = max_directed_link(sum(routed_bits)) / (256 × 200 MHz)
T_path,event = max_flow(C_path) / 200 MHz
L_Batch1 = sum_g(T_compute,g) + sum_event(T_serial,event + T_path,event)
```

同一 event 的 flow 共用 link 時 bits 會累加；相反方向分開計數。不同 event 則逐項相加。efficiency：single=1，OC=0.95、IC=0.85，再減 `min(0.15,0.01×max(0,parts−2))`；是未校準的 heuristic，並非原版 Rapid 的數據。group compute 假設平均切分，每顆工作量相同；不是逐 PE 排程的最慢實測 chiplet。

目前忽略／簡化：compute／communication overlap、分支並行（主指標採總和）、跨 event 共享 link 的時間排程、packetization／buffer／信用回傳／queueing、記憶體頻寬與權重載入、非 Conv/Linear 運算的完整 cycle 成本、IC reduction 的額外算術成本、實際資料流和工作不均。`max bits/B + max path` 是事件估計，兩個 max 未必來自同一路徑，不能宣稱 cycle-accurate 或所有情況的嚴格上界。

另有 DAG scheduler 的 `schedule_latency_ns` 用於診斷；它不會取代 GUI 的 Batch-1 sum，且也沒有完整的全網路 link 佔用排程。FPS 是 pipeline 估計輸出，不等於 `1/Batch1_latency`。

## 實際重現：相同9顆 mesh，兩種合法 mapping

| 指標 | ResNet-50 | ResNet-18 |
|---|---:|---:|
| Batch-1 平均 Power W | 3.553100 | 6.960143 |
| 舊 fixed-utilization W（diagnostic） | 7.894364 | 7.894364 |
| Energy/inference J | 0.731097 | 0.196705 |
| Footprint mm² | 712.525909 | 712.525909 |
| Compute ms | 202.582768 | 26.586007 |
| Serialization ms | 3.163440 | 1.664040 |
| Path ms | 0.016845 | 0.011545 |
| Batch-1 ms | 205.763053 | 28.261592 |
| Link dynamic energy µJ/inference | 245.260288 | 397.694976 |

這是實際重評的固定合法 mapping 對照，不是要求不同模型功率必須不同。ResNet-18 在短時間內有較多 chiplets 同時 active，故平均 W 較高，但總能量較低。原版直接計算的 area／ICI path 未改；原版 power（補回 static links）現在是 diagnostic，不是主 PPA 值。

## 此次修改

新增 `power.py` 以 assigned OPS／mapping efficiency 推估 per-chiplet active time，計算三項能量及 E/T。Evaluator、GUI、CLI／GUI CSV、constraint 與 reward 的主 power 都接到同一值；舊硬體 power 與原 link energy 欄位保留。GUI 顯示平均功率、能量分項與觀測窗；JSON 有每顆 active time。FPS 始終只是 performance diagnostic。

另外保留前次診斷改良：`e2e_latency_cycles` 與 Batch-1 ns 對應；舊 `min/avg/max_latency_cycles` 仍是 Rapid network path diagnostics。Area、Batch-1 latency、256 頻寬與偏好權重結構沒有修改。功率算法已更換，搜尋 ranking／reward 可以改變，不能沿用舊 reward 作新模型證據。
