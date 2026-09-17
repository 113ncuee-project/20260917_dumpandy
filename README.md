# RapidChiplet 專題資料

這個 repository 放的是 RapidChiplet 相關專題檔案，主要可執行版本在 `simplified_rapidchiplet/`。

目前上傳版本是新的 block-level preference-aware DSE 實作，不是
`260815_cnn-e2e-constrained-ppa` 的小幅修改版。本版本只移植 0815 專案的
Batch=1 analytical E2E latency 定義，其他 block、mapping、DAG scheduler、
preference RL 與專案結構都以本 repository 自己的實作為主。

## 下載後怎麼跑

```powershell
cd .\simplified_rapidchiplet
.\scripts\run_demo.ps1
```

或直接用 Python：

```powershell
cd .\simplified_rapidchiplet
python .\run.py --models shufflenet_v2_x1_0 --ppa-goal balanced --workload-search pareto-dp --dp-top-k 12 --out .\results\demo
```

詳細中文說明請看：

```text
simplified_rapidchiplet/README_zh-TW.md
```

## 主要資料夾

- `simplified_rapidchiplet/`：簡化版 DNN chiplet 評估工具，可直接執行。
- `presentation_work/`：簡報草稿、素材與投影片整理。
- `rapidchiplet.pdf`：RapidChiplet 相關參考資料。

新版 block-level preference-aware DSE 入口：

```powershell
cd .\simplified_rapidchiplet
py -3 .\preference_dse.py --models resnet50 --preference balanced --budget 64 --min-fps 15
```

它會依照 ResNet-50 的原生階層建立 18 個 semantic blocks，允許任意 block group 使用多顆 chiplet，並以 user preference 產生 constraint-first RL reward。詳細說明請看 `simplified_rapidchiplet/README_zh-TW.md`。

目前內建 6 個可直接拿來跑 DSE 的 CNN workload：

- `resnet18`：legacy stage metadata，作為較小的殘差網路基準。
- `resnet50`：18 個原生 Bottleneck semantic blocks。
- `shufflenet_v2_x1_0`、`shufflenet_v2_x2_0`：不同寬度的 channel-shuffle 網路。
- `mobilenet_v2`：由 Stem、InvertedResidual 與 Head 組成。
- `efficientnet_b0`：由 Stem、MBConv 與 Head 組成。

不指定 `--models` 時，preference DSE 會對這 6 個模型全部執行；也可以指定其中數個，例如：

```powershell
python .\preference_dse.py --models resnet18 resnet50 mobilenet_v2 efficientnet_b0 --preference latency --budget 8 --min-fps 15
```

這些模型目前是由 `configs/models.json` 提供的 analytical workload metadata，不需要安裝 PyTorch 或下載權重；因此適合先驗證 block/mapping/chiplet 搜尋流程。若之後要對接真實 ONNX/PyTorch graph，再將相同欄位替換成模型匯出的資料即可。

目前 `avg_latency_ns` 已改成 Batch=1 analytical end-to-end latency：
`sum(group compute) + sum(boundary/mapping communication service)`。RapidChiplet
的 traffic-weighted ICI latency 會另外輸出為 `rapid_avg_latency_ns`，不再直接
拿來當 inference latency。

## 上傳 GitHub 注意事項

`simplified_rapidchiplet/results/` 是執行後產生的結果檔，檔案可能很大，不建議整包上傳。此 repository 已加入 `.gitignore`，用 Git 指令上傳時會自動排除結果檔、Python cache 與瀏覽器暫存檔。
