# 标定数据

将实测或 TCAD 曲线转换为 `calibration_template.csv` 的列格式。原始文件建议放入不随仓库发布的本地归档，仓库仅保存可公开的数据与来源说明。

必需约定：

- `polarity` 只能是 `n` 或 `p`；
- `vgs_v`、`vds_v` 使用正的端电压幅值，p 器件分别表示 `|Vsg|`、`|Vsd|`；
- `id_a` 使用正的电流幅值；
- `dose_value` 与 `dose_unit` 成对填写，不混用 rad(Si) 和 rad(SiO2)；
- `bias_condition` 记录辐照偏置，而不是测量偏置；
- `source` 应能定位到实验批次、文献图表或 TCAD 运行目录。

训练剂量点用于拟合，独立剂量点用于验证，分别报告拟合误差和预测误差。

Cui 2023 顶栅 P 型 CNT 网络器件的文献核对、图表位置和待填数据见 `literature/cui2023_topgate/`。该数据保留原始 `krad(Si)` 单位，不与默认的 `krad(SiO2)` 演示配置混用；SWB 操作见 `../docs/tcad-user-guide.md`。
