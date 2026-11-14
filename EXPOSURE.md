# 固定快照的超阈暴露查询

## 已有链路与可运行入口

Python 标准库处理不可变行对象与精确有理数，SQLite 保存快照目录。objects.py 的 Objects() 和 catalog.py 的 Catalog() 默认均使用内存。lake.py 的 Lake.seed/read/delete/prepare/publish/rewrite 是真实业务接口；samples.py、replay.py、checks.py 保留非采样业务的原样例与断言。
analysis_ref.analyse(lake,station,L,R) 是当前 head 的全量积分参照，不支持阈值。exposure_probe.SnapshotView 只把其 read() 绑定到指定历史快照，未增加分析索引。

运行 python3 checks.py 核对原业务；python3 exposure_check.py baseline 核对新工作区；python3 exposure_probe.py all 重放公开观察，all 可换为 exposure_samples.NAMES 中的一个名称。无第三方依赖和外部服务。
初始 .pointwise-runtime.json 的 verify/demo 分别执行后两项入口。最终 verify 改为 ["python3","exposure_check.py","verify"]，demo 改为 ["python3","exposure_evidence.py"]。setup 保持空数组。

## 输入、口径与拟议接口

Lake.seed(files) 的 files 是文件名到行对象数组的映射。采样行含全局唯一正整数 id、非空字符串 station、整数 t、整数 reading、布尔 valid。id、t、reading、L、R、H 均在有符号64位范围内，布尔不当整数，输入保证合法；只有 L>R 和不存在快照需讨论错误。文件名不可变且永久唯一。快照0为空，seed 创建快照1。
Lake.read(snapshot) 返回 {"snapshot":整数,"rows":[{"file":文件名,"pos":零起行号,"value":原对象}]}，按文件名及位置排序，排除该快照的位置墓碑。未知快照报 ValueError("NO_SNAPSHOT")。delete 新增带墓碑的快照，rewrite 重排行文件并发布新快照；历史快照一直可读。不要求修改这些写入机制。
同站同刻先取可见 id 最小的行，再判断 valid；无效胜者是断点，不能替换成同刻有效候选。仅时间相邻、两端有效且间隔不超过10的胜者之间线性插值，不跨断点、不外推。物理行号和文件顺序不能充当时间顺序。

方案描述接口 build(lake,snapshot) -> handle 和 query(handle,station,L,R,H) -> result，不要求实现它们。
build 固定指定快照，未知快照报 NO_SNAPSHOT；后续 delete/rewrite 不改变原句柄的答案，允许为新快照重新构建。不要求把索引放进 SQLite，也不要求跨进程持久化。
query 分析 [L,R) 内已有插值曲线 y(t)，返回 {"snapshot":构建快照,"duration":[分子,分母],"excess":[分子,分母]}，duration 是 y(t)>H 的总时长，excess 是 ∫max(y(t)-H,0)dt。没有定义曲线的空隙不计；单个孤立点时长为零。所有分数须约分、分母为正，零写成 [0,1]。空窗、无覆盖或不存在站点返回两项零；L>R 抛 ValueError("BAD_WINDOW")。
例：有效点 (0,0)、(10,10)，[2,8)、H=4 返回 {"snapshot":1,"duration":[4,1],"excess":[8,1]}。平段等于 H 时两项均为零。下降段同样按严格超阈计算。
exposure_samples.sample(name) 返回 {"files":映射,"operations":数组,"queries":[[snapshot,station,L,R,H],...],"expected":结果数组}。expected 是公开手算锚点，不能作为证据计算器的查表答案。operations 仅供观察器构造重排与删除后的快照。fraction 覆盖有理交点，breaks 覆盖无效同刻胜者与大间隔，multi 覆盖跨多个片段的时间截断，snapshots 覆盖重排等价及后续删除。

## 查询预算与设计范围

N 为指定快照的文件数与物理采样行数之和，墓碑载荷也计入；这样空文件的目录读取也有计费。M 为构建时 SQLite 目录中 snapshots、files、tombstones、head 四表覆盖全部历史的总记录数，不要求 M 受 N 约束。首次可完整读取指定快照并排序。Catalog.state 的快照存在性检查及两个 sid 范围定位合计计 O(log(M+2)) 次目录访问，随后指定快照的目录载荷遍历计 O(N)，不得将全局目录定位视为常数或扫描全部历史。设 ℓ=log2(N+2)：构建最多 O(Nℓ²+log(M+2)) 次索引访问与精确算术操作，索引最多 O(Nℓ) 个标量单元，查询最多 O(ℓ²) 次索引访问与精确算术操作（包括站点定位）。不得扫描窗口内部片段或预枚举全部整数阈值。哈希、二分、排序等操作成本须明确，不能把长度不定的向量当成一个标量。
上述预算采用算术操作计数，整数或有理数各占一个逻辑标量；另行说明操作数位宽、精确算术及实际字节空间的增长，不能声称任意精度运算恒时。原 Lake.read/Catalog.state 的载荷读取与目录访问须计入构建成本，查询不能隐藏调用全量参照。
只设计静态查询索引；不做删点增量维护、在线建索引、并发发布、恢复、回收、分位数或展示页面。

## 交付与可重跑证据

交付 DESIGN.md：用 文件名:行号 串起 objects.py、catalog.py、lake.py 到 analysis_ref.py 的读取与分析调用链，分清现状与建议。说明索引状态、build/query 的可执行级伪代码、阈值相等和窗口截断边界、快照绑定及上述成本；与一种替代组织比较后给出选择依据。不要求完整理论证明。
保留所提供 Python 文件及其断言；新增 exposure_evidence.py 作为小型逐段有理计算与设计证据，不开发目标查询索引。用公开锚点和自选小规模随机查询核对数值，随机检查可采用独立逐段判定或分窗可加性等性质，记录种子及重跑方式。说明推荐索引在代表查询中读取哪些路径、为何不枚举窗口内部片段；该部分是方案预测，不是基线性能实测。
exposure_probe.run(spec) 只执行真实 Lake 调用，返回 head、steps、views、queries。views 按字符串快照号保存真实 read 结果或错误；queries 按输入顺序记录 input、original、gets。original 是原 analyse 的覆盖、积分、均值，绝不是超阈查询答案；gets 是该次原参照读取的文件及物理行数，不代表索引页访问。
exposure_evidence.collect() 返回以 NAMES 为键的对象，每项含 observed、predicted、explanation。observed 必须直接来自 run(sample(name))；predicted 是按对应 queries 顺序独立计算的超阈结果数组，含约定错误；explanation 说明数值边界与推荐索引访问路径。脚本直接运行时打印 collect() 的 JSON，使 demo 展示真实快照观察与计算结果。
python3 exposure_check.py verify 会重跑原业务、新工作区回归及 collect()，核对 observed、公开锚点、约分结果及 DESIGN.md 的四个源码模块行号。独立计算、随机检查、报告与证据一致性、伪代码和复杂度由人工复核；结构检查通过不能代替设计正确性审查。
