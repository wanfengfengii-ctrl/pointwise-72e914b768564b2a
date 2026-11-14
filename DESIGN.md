# 固定快照超阈暴露查询的索引设计

本文给出 `build(lake,snapshot)` / `query(handle,station,L,R,H)` 的设计（本轮不实现索引），
并用 `文件名:行号` 标注现状调用链。记 `N` 为指定快照的文件数与物理采样行数之和（墓碑载荷计入），
`M` 为 SQLite 目录 snapshots/files/tombstones/head 四表覆盖全部历史的总记录数，`ℓ=log2(N+2)`。

## 1. 现状：读取与分析调用链

写入侧（不要求修改）：`Lake.seed`（lake.py:10）经 `Objects.put`（objects.py:13）写入不可变 JSON 行文件
（内容冲突报 IMMUTABLE_CONFLICT，objects.py:23-26），再 `Catalog.commit`（catalog.py:48）追加 snapshots/
files/tombstones 行并推进 head（catalog.py:53-57）。`Lake.delete`（lake.py:27）与
`Lake.rewrite`（lake.py:68，经 prepare lake.py:39 与 publish lake.py:56）只新增快照，历史快照一直可读。

读取与分析链：查询方调用 `analyse`（analysis_ref.py:11）→ `lake.read()`（analysis_ref.py:14）→
`Lake.read`（lake.py:18）→ `Catalog.state`（catalog.py:39）：存在性点查（catalog.py:41，未知快照报
NO_SNAPSHOT，catalog.py:42）、按 sid 取 files（catalog.py:43）与 tombstones（catalog.py:44-45）两段范围定位；
随后 `Lake.read` 按文件名排序遍历（lake.py:21），逐文件 `Objects.get` 解析载荷（lake.py:22 → objects.py:30-32），
过滤位置墓碑（lake.py:23）。`analyse` 再按 `(t,id)` 排序（analysis_ref.py:15-17）、取同刻 id 最小胜者
（analysis_ref.py:18-21）、仅对两端有效且间隔 `gap > G` 不成立的相邻胜者插值（analysis_ref.py:23-26，
`G=10` 见 analysis_ref.py:4），窗口裁剪后梯形积分（analysis_ref.py:27-34）。
`SnapshotView`（exposure_probe.py:21-26）只把该全量参照绑定到历史快照，没有分析索引。

现状成本：每次查询全量读快照 O(N) 加排序 O(N·log N)，且不支持阈值 H。这就是要替代的基线。

## 2. 口径与边界规则（与参照一致）

- 同站同刻先取可见 id 最小的行，再判 valid；无效胜者是断点，不得用同刻有效候选顶替
  （与 analysis_ref.py:18-21 的“排序后取首行”等价）。
- 仅时间相邻、两端有效、间隔 ≤10 的胜者之间线性插值；不跨断点、不外推（analysis_ref.py:23-26）。
  孤立有效点不构成曲线，时长为零。
- 查询窗口 `[L,R)`，严格超阈 `y(t)>H`：`duration` 为超阈总时长，`excess` 为 `∫max(y(t)-H,0)dt`。
  单点测度为零，故严格与否只影响“平段恰好等于 H”这类水平边界。
- 结果分数约分、分母为正、零写 `[0,1]`；空窗（含 `L==R`）、无覆盖、未知站点返回两项零；
  `L>R` 抛 `ValueError("BAD_WINDOW")`（同 analysis_ref.py:12-13 的窗口校验先于读取）；
  未知快照抛 `ValueError("NO_SNAPSHOT")`（catalog.py:42）。

## 3. 推荐方案甲：分站时间有序线段树 + 节点阈值剖面

### 3.1 索引状态（内存态，不写回 SQLite）

```
Handle  = { snapshot: int,                 # 构建快照号，答案里的 "snapshot"
            stations: [str],               # 升序站点表，供查询期二分定位
            per_station: { str -> StationIndex } }
StationIndex = {
    segs: [(t0,y0,t1,y1)],                 # 胜者过滤后的插值段，按时间升序，跨度 ∈ [1,10]
    tree: [Node],                          # 以段为叶的静态平衡二叉树（堆式数组）
}
Node = Profile = {
    bp:    [int],                          # 升序阈值断点：该节点所有段的端点 reading（整数）
    slabs: [(α,β,p,q,r)],                  # 长度 len(bp)+1，全 Fraction
}   # 在 slab k 上：D(H)=α·H+β（超阈时长），E(H)=p·H²+q·H+r（超额积分）
    # slab 0 = (-∞,bp[0])；slab k = [bp[k-1],bp[k])；最上 slab 恒为零（严格超阈）
```

句柄是纯 Python 对象，构建时把 `lake.read` 的结果复制出来后不再触碰 lake。

### 3.2 build 伪代码（可执行级）

```
def build(lake, snapshot):
    view = lake.read(snapshot)          # lake.py:18；目录定位见 §3.6，未知快照在此抛 NO_SNAPSHOT
    groups = 按 row["value"]["station"] 分组(view["rows"])          # 一趟 O(N)
    handle = Handle(snapshot=view["snapshot"], stations=sorted(groups), per_station={})
    for st in handle.stations:
        pts  = groups[st] 按 (t, id) 排序                            # 全站合计 O(N·log N)
        wins = 每个 t 取首行                                          # 同刻最小 id 胜者
        segs = [(a.t, a.reading, b.t, b.reading)
                for 相邻胜者 a,b if a.valid and b.valid and b.t-a.t <= 10]
        tree = 以 segs 为叶建平衡二叉树
        for node in 自底向上遍历 tree:
            node.profile = leaf_profile(叶段)            若叶
                         = merge(左子.profile, 右子.profile)  若内部节点
        handle.per_station[st] = StationIndex(segs, tree)
    return handle

def leaf_profile(seg):                  # 段 (t0,y0)-(t1,y1)，len=t1-t0，d=|y1-y0|
    if y0 == y1:                        # 平段：断点即其高度，严格超阈在上侧为零
        bp = [y0]
        slabs = [(0, len, 0, -len, len*y0),   # H<y0：D=len，E=len·(y0-H)
                 (0, 0, 0, 0, 0)]             # H≥y0：零
    else:
        lo, hi = min(y0,y1), max(y0,y1)
        area = Fraction((y0+y1)*len, 2)       # 段下方面积
        bp = [lo, hi]
        slabs = [(0, len, 0, -len, area),                       # H<lo：整段计入
                 (Fraction(-len,d), Fraction(len*hi,d),         # lo≤H<hi：线性/二次过渡
                  Fraction(len,2*d), Fraction(-len*hi,d), Fraction(len*hi*hi,2*d)),
                 (0, 0, 0, 0, 0)]                               # H≥hi：零
    return Profile(bp, slabs)

def merge(P1, P2):                      # 节点段集 = 左右子段集之并 ⇒ 剖面相加
    bp = 归并排序后的 P1.bp 与 P2.bp（去重）          # 双指针 O(m1+m2)
    for 每个新区间 slab:                 # 每个新 slab 必落在 P1、P2 各自的某个 slab 内
        slabs[k] = P1.对应slab系数 + P2.对应slab系数   # 逐分量 Fraction 相加
    return Profile(bp, slabs)
```

### 3.3 query 伪代码（可执行级）

```
def query(handle, station, L, R, H):
    if type(L) is not int or type(R) is not int or L > R:
        raise ValueError("BAD_WINDOW")              # 先于任何索引访问
    st = 二分(handle.stations, station)              # O(ℓ)；未命中 → 返回两项零
    S = st.segs
    i = 第一个满足 S[i].t1 > L 的下标                 # 两次二分 O(ℓ)
    j = 最后一个满足 S[j].t0 < R 的下标
    D = E = Fraction(0)
    if i <= j:
        D,E += clip(S[i], L, R, H)                   # 边界叶裁剪 O(1)，见 §3.4
        if j > i: D,E += clip(S[j], L, R, H)
        for node in 规范分解(st.tree, i+1 .. j-1):    # ≤ 2⌈log2(|S|+1)⌉ 个节点，递归收集
            k = bisect_right(node.bp, H)             # O(ℓ)；左闭 slab ⇒ 阈值相等取上侧
            (α,β,p,q,r) = node.slabs[k]
            D += α*H + β;  E += p*H*H + q*H + r      # O(1) 精确算术
    return {"snapshot": handle.snapshot,
            "duration": ratio(D), "excess": ratio(E)} # Fraction 自动约分、分母为正、零=[0,1]
```

查询只读句柄内的索引，不调用 `lake.read` 或 `analyse`，不存在隐藏的全量参照调用。

### 3.4 阈值相等与窗口截断

- 阈值相等：`y>H` 严格。非平段的剖面在断点处连续，取哪侧相同；平段在 `H==y` 处必须为零，
  因此求值统一用 `bisect_right` 取**左闭上侧 slab**（H 恰等于断点 c 时落入 `[c,下一断点)`），
  与 leaf_profile 中平段上侧零系数一致。`flat` 样例（H=4 得零、H=3 整段计入）锁定该边界。
- 窗口截断：至多两个边界段被 `[L,R)` 切断，直接 O(1) 裁剪：
  `lo=max(L,t0)`、`hi=min(R,t1)`，`lo>=hi` 则跳过；端点超出量 `e=y-H` 为线性，
  异号时交点 `t*=lo+(hi-lo)·e_lo/(e_lo-e_hi)` 为精确 Fraction，超阈半区间长度与三角形面积精确可得。
  内部段被窗口完整覆盖，已由节点剖面整体计入，绝不逐段扫描。

### 3.5 快照绑定

`build` 经一次 `lake.read(snapshot)`（lake.py:18）把该快照全部载荷复制进句柄后，句柄不再持有 lake。
历史快照的行内容不可变（objects.py:23-26 的 IMMUTABLE_CONFLICT 保证同名字文件内容不可改写），
`delete`（lake.py:27）与 `rewrite`（lake.py:68）只经 `Catalog.commit`（catalog.py:48）产生更新 sid，
不回写旧快照目录行（catalog.py:53-56 全是 INSERT），故原句柄答案不受后续删除/重排影响；
需要新快照时允许重新 `build`。`snapshots` 样例验证：重排后快照 2 答案同快照 1（物理行序不影响
`(t,id)` 排序），删除后快照 3 只剩孤立点，快照 0 为空，99 报 NO_SNAPSHOT。

### 3.6 成本核算（算术操作计数）

- 目录定位：`Catalog.state` 的存在性点查（catalog.py:41）与 files/tombstones 两次 sid 前缀范围定位
  （catalog.py:43-45）走 SQLite 主键 B 树（表结构 catalog.py:10-16），合计 O(log(M+2)) 次目录访问；
  随后指定快照的目录载荷遍历与 JSON 解析（lake.py:21-24、objects.py:30-32）计 O(N)。
  不把全局目录定位当常数，也不扫描全部历史。
- 构建：分组 O(N) + 排序 O(N·log N) + 胜者/段过滤 O(N) + 自底向上 merge（每层合计 O(N)，共 O(ℓ) 层）
  = O(N·ℓ + log(M+2))，在预算 O(N·ℓ² + log(M+2)) 之内。
- 空间：每段进入 O(ℓ) 个祖先节点，每节点断点数 ≤ 2·段数，故 Σ|bp| = O(N·ℓ)；
  每 slab 存 5 个有理系数，索引总计 O(N·ℓ) 个标量单元（向量逐标量计数，不把剖面当一个标量）。
- 查询：站点二分 O(ℓ) + 叶定位 O(ℓ) + 至多 2 个边界叶 O(1) + 至多 2⌈log2(|S|+1)⌉ 个规范节点
  ×（断点二分 O(ℓ) + 求值 O(1)）= O(ℓ²) 次索引访问与精确算术操作，含站点定位。
- 排序、二分成本如上明示；设计不使用哈希（站点定位用有序数组二分，避免期望/最坏情形之争）。
  不扫描窗内片段（内部段由规范节点整体作答），不预枚举整数阈值（H 在断点表上二分定位）。

### 3.7 位宽与精确算术

预算是逻辑标量计数；实际位宽另行说明，不声称任意精度恒时。输入为 64 位整数；
段跨度 ≤10（analysis_ref.py:4），故斜率分母 ≤10，剖面系数是分子分母各 O(64+log N) 位的有理数
（每节点至多累加 N 段）；查询求值引入 H² 项，中间量 O(128+log N) 位；跨 O(ℓ) 节点求和再增 O(log ℓ) 位。
最终约分是对该位宽整数的一次 gcd。即每个“标量”占 O((64+log N)/64) 个机器字、
索引实际字节空间 O(N·ℓ·(64+log N)/8)，算术运算的比特成本随位宽增长而非恒时。

## 4. 替代方案乙：持久化前缀剖面（阈值轴线段树）

状态：把每站全部段端点 reading 坐标压缩为 ≤2N 个阈值坐标；在此阈值轴上建可持久化线段树，
节点存该阈值区间上多项式系数和 (α,β,p,q,r)。每加入一个时间相邻的段，相当于对阈值轴做两次
区间加（`(-∞,lo)` 加常数/线性、`[lo,hi)` 加线性/二次），路径复制产生新版本根；
`roots[k]` 对应前 k 段的前缀剖面。另存段数组供边界裁剪。

```
build: 坐标压缩 O(N·log N)；逐段两次持久化区间加，各 O(ℓ) 新节点 ⇒ 构建 O(N·ℓ)、空间 O(N·ℓ)
query: t_i = 首个 ≥L 的段界，t_j = 最后 ≤R 的段界
       D,E = 点查询(roots[j], H) - 点查询(roots[i], H)   # 各 O(ℓ)，沿根到叶累加系数
             + clip(含 L 的边界段) + clip(含 R 的边界段)    # 各 O(1)
```

取舍：乙的查询为 O(ℓ)，优于甲的 O(ℓ²)，构建与空间同为 O(N·ℓ) 级；但乙引入阈值坐标压缩、
路径复制持久化与双版本差分三件额外机制，实现与人工复核成本显著更高，每次区间加的分配常数更大，
且前缀差分要求两版本系数逐项相减，精确算术操作数约为甲单节点求值的两倍。
既定预算只要求查询 O(ℓ²)，甲用普通静态数组即可满足，故选甲；
若未来预算收紧到 O(ℓ)，乙是现成升级路径（甲亦可经 fractional cascading 把逐节点二分降为均摊 O(1)）。
纯数组加逐段裁剪（analysis_ref 式）查询 O(窗内段数)，√N 分块查询 O(√N·ℓ) 且边界仍需扫段，
均违反查询预算与“不得扫描窗口内部片段”，仅作对照，不予采用。

## 5. 代表查询的索引访问路径（方案预测，非基线实测）

- `rise [2,8) H=4`：站点表二分 1 次命中 A；叶定位 2 次二分得唯一段 `[0,10)`；该段被窗口切断，
  按 §3.4 边界叶裁剪，交点 t*=4，duration=4、excess=8；未触及内部节点。
- `multi [-1,13) H=4`：3 段全被覆盖，无边界裁剪；叶区间整体分解为 ≤2⌈log2 4⌉ 个规范节点，
  每节点在断点表上二分 H=4 所属 slab 后 O(1) 求值相加，得 duration=6、excess=18；
  窗内 3 段不逐个出现，这就是不枚举窗内片段的方式。
- `snapshots` 快照 3：该快照索引只有孤立点、无段叶，叶定位直接为空，返回两项零；
  快照 99 在 build 期即由 catalog.py:42 抛 NO_SNAPSHOT。

以上路径是对推荐索引的推演说明；基线实测数据（真实 Lake 调用、原参照积分、载荷读取计数）
见 exposure_evidence.py 的 `observed`，两者严格分开。

## 6. 证据与重跑

- `python3 checks.py`：原业务回归（保留未动）。
- `python3 exposure_check.py baseline`：原业务 + 观察器重放基线。
- `python3 exposure_check.py verify`：以上全部 + `exposure_evidence.collect()`，
  核对 observed 与实测一致、predicted 与公开锚点一致、分数约分规范、本文四个源码模块行号有效。
- `python3 exposure_evidence.py`（demo）：打印 collect() 的 JSON，展示真实快照观察与独立计算结果。
- 独立计算：`exposure_evidence.expose` 逐段精确有理计算（非目标索引，不查表 sample 的 expected）。
- 随机检查：种子 20261114、300 轮共 900 条随机小查询，与独立的“打碎-中点判定”路径互验，
  并验证分窗可加性 `Q(L,R)=Q(L,M)+Q(M,R)`；随 collect() 每次重跑，结果打印到 stderr。
