# Kanhaiya 2021 (ACS Nano)：CNTFET 总剂量数据来源

## 文献

- Kanhaiya, P. S.; Yu, A.; Netzer, R.; Kemp, W.; Doyle, D.; Shulaker, M. M. *Carbon Nanotubes for Radiation-Tolerant Electronics.* ACS Nano **2021**, 15, 17310–17318.
- DOI：https://doi.org/10.1021/acsnano.1c04194
- 本地文件：`reference/literature/nn1c04194.pdf`（正文）、`nn1c04194_si_001.pdf`（补充材料）。
- 许可与数据可用性：论文与 SI 以图形式给出全部 TID 数据，未提供数据仓库。

## 器件与实验条件（已核对原文）

| 项目 | 内容 | 位置 |
| --- | --- | --- |
| 器件 | 四种 CNFET 几何：global bottom-gate、top-gate、local bottom-gate、dual-gate | Fig. 2，第 17312 页 |
| 沟道 | L = 50 nm，W = 3 µm（Fig. 3 各几何一致） | Fig. 3 caption |
| 栅介质 | EOT ≈ 7 nm（"thick"）与 ≈ 2 nm（"thin"），HfO₂ 高 k | Fig. 4 caption |
| 钝化 | bottom-gate / dual-gate 用 100 nm SiO₂ | Fig. 2 caption |
| 辐照 | Co-60 γ（0–800 krad(Si)，剂量率 56 rad(Si)/s）；LEXR X 射线（至 10 Mrad(Si)） | 第 17312–17313 页 |
| 偏置 | V_GS = −V_DD（−1.8 V），V_DS = 0 V（最坏情况） | 第 17312 页 |
| 统计 | 每种几何 256 个器件，误差棒为 95 % 置信区间 | Fig. 3e / Fig. 4 caption |

## 本项目使用的数据

`scripts/digitize_kanhaiya2021.py` 从 PDF 的**矢量内容**提取：

- **Figure 3e**：top-gate / local bottom-gate / dual-gate 的 |ΔV_T| vs TID（0–800 krad，60Co）；
- **Figure 4**：local bottom-gate 与 dual-gate 的 |ΔV_T| vs TID（0–10 Mrad，LEXR），EOT 7 nm 与 2 nm 各一条。

方法：ACS Nano 的图由填充路径构成，坐标轴刻度是贴在框线内侧的小矩形，曲线是单条填充轮廓多边形。脚本用刻度位置做线性标定（刻度数与声明不符即报错），再用多边形上下边界的**中线**还原曲线；误差棒是独立图元，不进入中线。

产物：

| 文件 | 内容 |
| --- | --- |
| `vt_shift_vs_tid.csv` | 7 条曲线 × 6–9 个剂量点 = 54 行，含几何、EOT、页码、提取方法、质量标记 |
| `digitization_report.json` | 坐标轴标定系数、PDF SHA-256、PyMuPDF 版本 |
| `results/literature/kanhaiya_overlay.png` | 复原点叠加在原图上的审计图 |

## 与 P0 紧凑模型的关系

Kanhaiya 2021 提供的是**阈值漂移本身**（mV），不需要经过 Cox 换算，因此比"电流曲线 + 反推电荷"更直接。其用途有三：

1. **交叉校验剂量律**：与 Cui 2023 的 p 型顶栅器件比对，检验"幂律指数是否可迁移"；
2. **结构对比**：同一套几何/介质工程下 50 倍的漂移差异（10 Mrad 处 441 mV vs 341 mV vs 60 mV 量级）；
3. **范围外推**：剂量覆盖到 10 Mrad，是 P0 主线（0–3 Mrad）的三倍以上。

**不提供**：n 型器件的 TID 数据（全部为 p 型或未标注极性的 CNFET），因此 P0 的 n 型对称假设仍未解除。

## 用户确认门槛

- [ ] 已核对 Figure 3e / Figure 4 的剂量单位是 krad(Si) 与 Mrad(Si)。
- [ ] 已接受"曲线中线提取"的误差量级（≈ ±5 mV，见审计图）。
- [ ] 已确认 dual-gate 数据在低剂量段低于噪声底，不参与幂律拟合。
