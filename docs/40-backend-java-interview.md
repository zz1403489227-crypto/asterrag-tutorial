# 第 40 章：从运行句柄出发，学会 Java 的核心追问

> 第二部分 · 基础追问。第一部分告诉你项目做了什么，本部分解释这些选择背后的通用原理。重点对应面经中的集合、并发、线程池异常、JVM 和类加载。

## 40.1 ArrayList、LinkedList，为什么不是“增删就选链表”

**短答：** ArrayList 基于可扩容数组，按下标读取快，连续遍历局部性好；LinkedList 基于链表，只有已经定位到节点时，附近插入删除才不需要搬动后续元素。先按下标找到链表第 k 个位置，通常仍要遍历。

例如本轮 Agent 轨迹按顺序追加，结束时整体遍历生成快照。它主要是尾部追加与顺序读取，并不频繁在已知节点中间插入，ArrayList 很合适。尾部追加摊销 O(1)，偶尔扩容复制；中间插入和删除通常 O(n)。不要只背“数组查询快、链表增删快”，遗漏定位成本和对象内存开销。

**回到项目：** 释放钩子是 ArrayList，受到锁保护；不是因为 ArrayList 自己线程安全，而是访问方式和外部同步满足要求。

**再追问：** List 和 Set 的区别？前者表示有序序列、允许重复；后者表达去重集合。Map 表达键到值的映射。在检索里，候选排名要保留顺序，chunk 去重要表达身份，二者常需要配合而非二选一。

## 40.2 HashMap 为什么快，为什么并发时不够

HashMap 用键的哈希值定位桶，再在桶内判断键是否相等。哈希分布好时，get/put 平均接近 O(1)，但碰撞、扩容和键分布影响成本。`equals` 相等的对象必须有相等的 `hashCode`；反过来不成立，哈希相同仍要比较 equals。

因此当自定义复合键用于 chunk 去重时，应让 equals/hashCode 表达同一套身份规则；放入 Map 后再修改参与哈希的字段，会使后续查找难以定位。`LinkedHashMap` 在哈希映射之外维护顺序，适合需要稳定遍历的映射。[Java 17 HashMap 契约](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/HashMap.html)

ConcurrentHashMap 支持并发访问和原子复合方法，但别把“线程安全容器”理解为“容器里所有业务对象都线程安全”。

```java
// 教学反例：即使 map 本身支持并发，下面仍是两个步骤。
if (!map.containsKey(taskId)) {
    map.put(taskId, new TaskState());
}
```

两个线程可以同时通过判断。应按需要使用 `putIfAbsent`、`computeIfAbsent` 等原子操作；里面的计算也要短，避免把慢网络调用放进去。同时 `TaskState` 自己的多个字段更新仍需协调。[ConcurrentHashMap API](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/concurrent/ConcurrentHashMap.html)

**回到项目：** 任务管理使用 Guava Cache，不要把它说成一个裸 ConcurrentHashMap；但“容器并发安全不等于 value 的复合动作安全”这个原则仍然适用，因此任务内部还有 AtomicBoolean 和 volatile 字段。

## 40.3 volatile、CAS、锁：分别回答三个问题

从一个错误写法开始：

```java
// 教学反例：volatile 不会把这两步合成原子操作。
if (!settled) {
    settled = true;
    finish();
}
```

线程 A 和 B 都可能先看见 false，再分别 finish。可见性只保证读写之间的规定关系，不保证一段代码不能交错。

| 工具 | 核心能力 | 项目对应 |
|---|---|---|
| volatile | 发布新值、建立规定的可见性和顺序关系 | Provider 的缓存引用、运行句柄的取消函数引用 |
| CAS | 对一个状态做条件性的原子更新 | settled 从 false 到 true 争取收尾资格 |
| synchronized | 同一监视器下互斥执行复合操作，并提供可见性 | 缓冲区快照、释放钩子集合与 released 状态 |

Java 内存模型的 happens-before 是理解它们的关键：同一监视器的解锁先于后续加锁；对 volatile 的写先于后续相应读等规则，决定跨线程能依赖什么。不是背“变量强制从主内存读”就足够。[JLS：线程与内存模型](https://docs.oracle.com/javase/specs/jls/se17/html/jls-17.html)

CAS 还有 ABA 问题：如果值从 A 变 B 又变回 A，比较者只看当前值可能以为从未变过。项目 settled 只从 false 到 true、不回退，重点不是 ABA；但版本更新或可复用状态机需要考虑版本号。CAS 失败后一直自旋也有 CPU 成本，不是所有业务都适合无锁。

## 40.4 synchronized 和 ReentrantLock 怎么选

两者都能实现可重入互斥。“可重入”意味着持锁线程可以再次进入同一把锁保护的代码，不会因为自己已经持锁而卡住。[ReentrantLock API](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/concurrent/locks/ReentrantLock.html)

synchronized 结构简单，退出块时自动释放；ReentrantLock 提供显式加解锁、可中断等待、尝试获取、可选公平性和多个 Condition 等控制，需要在 finally 中释放。

项目对短小的状态快照用 synchronized，容易看清临界区。不要为了背高级 API，就建议把锁替换成 ReentrantLock；要先说明需要新增哪种控制。更不要持着本机锁去等一次几十秒的模型调用，否则同锁下的取消或收尾也可能被阻塞。

**死锁怎么形成？** A 拿锁甲等乙，B 拿乙等甲。四个必要条件常概括为互斥、持有并等待、不可抢占、循环等待。工程上统一加锁顺序、减少嵌套、缩短持锁范围，必要时设置可恢复的超时。只有“加个超时”却不处理半完成状态，不算完整方案。

## 40.5 线程、线程状态、sleep/wait 与取消

进程是资源隔离单位；同一进程的线程共享堆等资源，但各有执行栈。Java 常见任务表达方式包括 Runnable、Callable，线程池负责执行，不应把每种提交 API 都说成一种底层线程。

Java 线程状态有 NEW、RUNNABLE、BLOCKED、WAITING、TIMED_WAITING、TERMINATED。等待 synchronized 监视器与主动等待条件不是同一种状态；RUNNABLE 也不等于此刻一定占用 CPU。`sleep` 不释放已经持有的监视器，`wait` 要在持有对应监视器时调用并释放它，醒来后还要重新取得锁并检查条件。[Java Thread API](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/lang/Thread.html)

线程中断是一种协作信号，不是安全的强制杀死。阻塞 API 可能抛 InterruptedException，计算循环需要检查信号，外部调用是否响应又由其实现决定。项目取消里 dispose 和 Agent interrupt 也应按各自契约解释，不能声称它们会撤销所有工具操作。

## 40.6 线程池的七个参数，怎样真正连起来

七个参数是核心线程数、最大线程数、空闲存活时间、时间单位、任务队列、线程工厂、拒绝策略。只会列名字还不够，关键是接到一个任务时的决策：

```text
当前工作线程少于 core → 尝试新建线程
否则 → 尝试入队
入队失败且线程数少于 max → 尝试再建线程
仍不能接收 → 拒绝策略
```

所以无界队列可能使任务长期积压，最大线程数难以发挥作用；有界队列让容量与饱和显式可见；SynchronousQueue 不保存排队任务，侧重直接交接。项目检索池和模型流池的区别，正是这套机制的具体化。[ThreadPoolExecutor 规则](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/concurrent/ThreadPoolExecutor.html)

常见拒绝策略：Abort 抛异常，CallerRuns 让调用者执行，Discard 丢当前任务，DiscardOldest 移除排队最旧任务后尝试接收。后两者若直接用于用户问答，会带来难解释的丢任务，不能只当“调优选项”。

**线程越多越好吗？** CPU 密集任务受核数限制；I/O 密集任务可用更多并发覆盖等待，但还受连接池、外部限额、内存和上下文切换约束。模型服务只允许有限并发时，加一千线程不会增加模型容量，可能只增加排队和超时。

## 40.7 提交的任务抛异常，我怎么知道

先区分异常类型：Throwable 下有 Error 和 Exception；Exception 中 RuntimeException 及其子类是非受检异常，其余受检异常一般需要捕获或声明。Error 常表示更严重的运行环境问题，不宜不加区分地吞掉。异常分类与“在哪个线程发生”又是两条维度。

调用线程的 try/catch，不能自动捕获未来另一个线程才抛出的异常。

- `execute` 提交的 Runnable 若异常逃逸，可由相应线程的未捕获异常处理设施观察，仍应有业务日志与关联编号。
- `submit` 常把失败包装进 Future；不读取 Future，也不安排观测，异常就可能对业务调用方“悄无声息”。
- CompletableFuture 用 `whenComplete`、`handle`、`exceptionally` 或 get/join 观察终态。恢复成空结果时要保留故障信息，不能让“失败为空”与“确实无资料”无法区分。

**回到项目：** 检索通道在任务体里捕获异常，超时分支也转成空结果并记录日志；Agent 主流订阅有 onError，后台记忆提取也有错误回调。可以沿这些入口解释异常怎样被看见，而不是说“全局异常处理器会兜住所有线程”。

## 40.8 ThreadLocal 为什么会串数据或留住内存

ThreadLocal 把数据关联到线程，不是关联到抽象业务请求。线程池的线程寿命远长于一次问答：本次请求结束不清理，下次复用线程就可能读到旧用户；value 引用的对象还可能一直被保留。

正确思路是明确设置与清理生命周期，并在跨线程处决定显式传参还是受支持的上下文传播。TTL 包装帮助传递和恢复上下文，但并不能让所有第三方调度器自动服从同一传播规则。Agent 入口直接传 userId/sessionId，就是一个可解释的边界。

## 40.9 JVM 与 OOM，准备到能定位本项目的程度

堆主要容纳对象；线程栈保存调用帧和局部状态；元空间保存类元数据；直接内存、线程本身等还会消耗堆外资源。因此“内存溢出就调大堆”不完整。

以项目为例：回答缓冲区和大量未结束任务可能使堆增长；无限排队保存 Runnable 及其捕获对象也会留住会话；线程过多可能耗尽本地线程资源。即便业务消息已经写入 PostgreSQL，JVM 中仍被引用的对象也不会因此自动释放。

GC 判断可达性，而不是看对象有没有业务价值。长生命周期缓存持有已结束 RunHandle，就可能让其输出缓冲区继续存活。诊断设计应先看错误类型、堆/堆外/线程指标、GC 日志和线程栈，再必要时分析 heap dump 的大对象与引用链；dump 可能含问题、答案和身份数据，不能随意上传。这些是排查方法，不是本项目已发生的线上事故。

类加载主线是加载、链接（验证/准备/解析）、初始化。父加载器委派有助于统一基础类身份；类身份不仅由全限定名决定，也和定义它的加载器有关。Spring 创建 Bean 是对已经加载的类进行实例化与装配，不等于 Spring 自己重新实现 JVM 类加载。

项目基线为 Java 17，可从 record、文本块等源码用法说明新语法价值；不要把 Java 21 才正式交付的虚拟线程说成本项目使用的并发方案。

## 40.10 一条可反复练习的追问链

“为什么用单例 Service？”→“每轮状态放哪里？”→“为什么还需要锁？”→“volatile 为什么不够？”→“CAS 成功后落库失败怎么办？”→“任务异常怎么发现？”→“任务没有清理会造成什么内存问题？”

每次回答都先说概念，再回到 RunHandle、EventBridge 或线程池中的一个具体例子。重点面经记录：305、457、657、783～789、1263、1441、1443。[来源及项目对照](../appendices/backend-source-and-interview-map.md)

[上一章](39-backend-streaming-in-project.md) · [下一章：Spring 与 MyBatis 基础](41-backend-spring-mybatis-interview.md) · [返回首页](../README.md)
