# 标定数据

将实测或 TCAD 曲线转换为 `calibration_template.csv` 的列格式。原始文件建议放入不随仓库发布的本地归档，仓库仅保存可公开的数据与来源说明。

必需约定：

- `polarity` 只能是 `n` 或 `p`；
- `vgs_v`、`vds_v` 使用正的端电压幅值，p 器件分别表示 `|Vsg|`、`|Vsd|`；
- `id_a` 使用正的电流幅值；
- `dose_value` 与 `dose_unit` 成对填写，不混用 rad(Si) 和 rad(SiO2)；
- `bias_condition` 记录辐照偏置，而不是测量偏置；
- `source` 应能定位到实验批次、文献图表或 TCAD 运行目录。

后续标定器应使用训练剂量点拟合，并保留独立剂量点验证；不能把全数据拟合误差当作预测误差。
