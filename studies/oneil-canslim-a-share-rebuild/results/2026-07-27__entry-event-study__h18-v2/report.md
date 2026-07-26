# h18 候选池入场事件研究

候选池和排名完全冻结，只比较入场时点。所有枢轴与均量都排除信号日，信号出现后
下一交易日开盘进入；事件收益尚未扣交易成本，不能直接当作组合回测结果。

| 阶段 | 入场 | 期限 | 事件数 | 覆盖 | 平均超额 | 中位超额 | 正超额 | 5%尾部 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| development | direct | 60 | 2479 | 96.8% | 2.54% | -0.29% | 49.3% | -25.20% |
| development | direct | 120 | 2359 | 96.8% | 3.17% | -0.52% | 49.3% | -35.71% |
| development | new-high-20 | 60 | 1051 | 42.5% | 1.97% | -1.25% | 47.5% | -27.77% |
| development | new-high-20 | 120 | 1005 | 42.5% | 1.24% | -3.09% | 45.0% | -38.46% |
| development | new-high-55 | 60 | 539 | 22.0% | 1.85% | -1.44% | 46.4% | -27.80% |
| development | new-high-55 | 120 | 492 | 22.0% | -0.64% | -5.34% | 41.3% | -39.32% |
| development | new-high-55-volume-1.4 | 60 | 431 | 17.6% | 1.51% | -2.11% | 44.3% | -28.59% |
| development | new-high-55-volume-1.4 | 120 | 400 | 17.6% | -1.48% | -6.15% | 39.5% | -39.90% |
| development | structured-base-breakout | 60 | 87 | 4.0% | 2.25% | -0.46% | 48.3% | -30.32% |
| development | structured-base-breakout | 120 | 83 | 4.0% | -0.45% | -6.77% | 42.2% | -39.12% |
| development | vcp-breakout | 60 | 30 | 1.2% | -4.97% | -8.43% | 30.0% | -33.51% |
| development | vcp-breakout | 120 | 30 | 1.2% | -8.17% | -9.67% | 33.3% | -41.52% |
| selection-validation | direct | 60 | 1367 | 99.6% | 3.64% | 0.41% | 51.1% | -28.78% |
| selection-validation | direct | 120 | 1278 | 99.6% | 5.82% | 0.01% | 50.0% | -40.19% |
| selection-validation | new-high-20 | 60 | 710 | 51.9% | 2.81% | -0.28% | 49.4% | -30.17% |
| selection-validation | new-high-20 | 120 | 674 | 51.9% | 6.67% | 1.08% | 50.4% | -42.07% |
| selection-validation | new-high-55 | 60 | 453 | 32.4% | 3.49% | -0.03% | 49.9% | -30.10% |
| selection-validation | new-high-55 | 120 | 427 | 32.4% | 8.94% | 4.96% | 54.3% | -41.61% |
| selection-validation | new-high-55-volume-1.4 | 60 | 307 | 21.7% | 2.13% | -1.73% | 45.6% | -29.69% |
| selection-validation | new-high-55-volume-1.4 | 120 | 289 | 21.7% | 7.23% | 1.93% | 51.6% | -40.89% |
| selection-validation | structured-base-breakout | 60 | 100 | 7.3% | 7.30% | 4.05% | 57.0% | -26.01% |
| selection-validation | structured-base-breakout | 120 | 99 | 7.3% | 14.29% | 14.96% | 66.7% | -41.78% |
| selection-validation | vcp-breakout | 60 | 24 | 1.7% | 5.75% | 6.63% | 66.7% | -28.87% |
| selection-validation | vcp-breakout | 120 | 24 | 1.7% | 19.22% | 20.44% | 75.0% | -39.07% |
