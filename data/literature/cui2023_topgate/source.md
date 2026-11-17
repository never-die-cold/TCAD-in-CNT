# Cui 2023 顶栅 P 型 CNT 网络 FET 数据来源

## 文献与许可

- Ding, H.; Cui, J.; Zheng, Q.; et al. *Effect of Trapped Charge Induced by Total Ionizing Dose Radiation on the Top-Gate Carbon Nanotube Field Effect Transistors*. Electronics 2023, 12, 1000.
- DOI：https://doi.org/10.3390/electronics12041000
- 公开 PDF：https://mdpi-res.com/d_attachment/electronics/electronics-12-01000/article_deploy/electronics-12-01000.pdf
- 本地原文：`reference/literature/electronics-12-01000.pdf`（不提交 Git）。
- 许可：Creative Commons Attribution（CC BY），见论文首页。
- 数据可用性：论文第 12 页写明数据不在公共仓库，且不能应请求提供。本项目使用论文公开图表的数字化结果，来源精确标记到图号。

## 器件与实验条件（已逐项核对原文）

| 项目 | 原文信息 | 位置 |
| --- | --- | --- |
| 器件 | 顶栅 P 型 CNT-network FET，采用网络薄膜沟道 | 第 2 节，第 3 页 |
| 衬底 | 500 µm Si / 280 nm SiO2 | 第 2 节，第 3 页 |
| 沟道 | 未掺杂 CNT 网络膜，密度 15 pieces/µm | 第 2 节，第 3 页 |
| 宽/长 | 30 µm / 4 µm | 第 2 节，第 3 页 |
| 源漏 | Pd，原文称欧姆接触 | 第 2 节，第 3 页 |
| 顶栅介质 | Y2O3 与 HfO2，总厚度 10 nm；各自厚度未给出 | 第 2 节，第 3 页 |
| 辐射源 | Co-60 γ，平均能量 1.25 MeV，大气环境 | 第 2 节，第 3 页 |
| 剂量率 | 195.476 rad(Si)/s | 第 2 节，第 3 页 |
| 剂量点 | 0、200、500、1000、2000、3000 krad(Si) | 第 2 节、表 1、图 2 |
| 辐照偏置 | 器件各端浮空（floating） | 第 2 节，第 3 页 |
| 总辐照累计时间 | 255 min 47 s；分剂量点时间不用于模型输入 | 第 2 节，第 3 页 |
| 测量 | Keithley 4200SCS，室温 | 第 2 节，第 3 页 |
| 栅扫描 | 0.5 → −2 V，再 −2 → 0.5 V；步进 −0.02 V 的描述见原文 | 第 2 节，第 3–4 页 |
| 测量偏置 | VDS = −0.1 V 或 −2 V，双向扫描 | 表 1，第 4 页 |
| 每剂量点测量时间 | 小于 45 min，用于减小退火影响 | 第 2 节，第 4 页 |

## 可用于提取的图表

| 文件 | 图表 | 内容 | 用途 |
| --- | --- | --- | --- |
| `idvg_raw.csv` | 图 2，第 4 页 | VDS = −0.1 V 下 6 个剂量点的 IDS–VGS | 零剂量与多剂量曲线对比 |
| `metrics_raw.csv` | 图 3a–c，第 4–5 页 | 阈值电压、最大跨导、亚阈值摆幅随剂量变化 | 独立指标对比与剂量律检查 |
| 暂不使用 | 图 9，第 11 页 | 双向扫描迟滞 | 需要独立扫描方向和动态陷阱模型，不与图 2 混合 |

提取规则：

1. 原始 CSV 保留论文的负电压、负电流符号，不手工改成正值。
2. `source_location` 精确到图号和子图；`extraction_method` 记录软件与版本；`quality` 记录人工复核状态。
3. 使用 WebPlotDigitizer 时先校准坐标轴，确认 IDS 是对数坐标，再提取；至少抽查每条曲线三个点。
4. 图 2 未明确说明扫描方向，对应字段填 `not_reported`。
5. 图 3 未清晰给出阈值提取判据，提取方法标记为 `not_reported`。

## 与现有 baseline 的参数边界

- 本文是 4 µm 栅长的 CNT 网络器件，当前 `configs/baseline.toml` 是 50 nm 的演示紧凑模型，两套几何分别使用。
- 本文剂量单位是 rad(Si)，当前演示配置是 krad(SiO2)。文献数据保留 `krad(Si)`，剂量换算需要独立的材料依据。
- 本文亚阈值摆幅在约 0–200 krad(Si) 先下降、随后上升，采用非单调或分段模型描述。
- 论文数据用于 P 型器件；N 型器件与 CMOS 模型需要独立数据。

## 用户确认门槛

- [ ] 图 2 零剂量曲线已提取并复核。
- [ ] 至少两个非零剂量曲线已提取并复核。
- [ ] 图 3a–c 已提取，或明确只用于定性对比。
- [ ] 顶栅两层介质厚度、介电常数和 CNT 网络有效材料参数的假设已单独记录。
- [ ] 已选择扫描方向，并理解图 2 未明确报告扫描方向的限制。
