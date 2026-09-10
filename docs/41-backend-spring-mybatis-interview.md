# 第 41 章：Spring、事务代理与 MyBatis，怎样接住连续追问

> 第二部分 · 基础追问。重点对应依赖注入、Bean 单例、AOP、事务自调用和 SQL 注入。

## 41.1 Spring 和 Spring Boot 有什么区别

**短答：** Spring 提供 IoC、AOP、事务和 Web 等基础能力；Spring Boot 在这些能力上提供约定、自动配置、依赖组织和启动方式，减少手动装配。Boot 不是另一个替代 Spring 的容器。

自动配置不是“猜测并替你解决一切”：它根据类路径、已有 Bean、配置项等条件装配对象。项目的 Agent 条件注解、pg 向量实现开关，就是条件装配思路在业务能力上的运用。配置数据库地址也不会自动替你设计表结构、建立所有索引或优化 SQL。

若问 starter 和 Maven BOM：starter 主要组织一组常用依赖；BOM 主要管理依赖版本一致性。根 POM 导入 Boot BOM，不表示所有技术都作为运行模块启用。这样就把之前“Maven 在项目里干什么”的问题接回了运行架构。

## 41.2 IoC 和 DI 到底改变了什么

原来 Service 自己 new Mapper 和 Redis 客户端，就同时承担业务与依赖创建，替换、测试和配置都容易纠缠。IoC 把对象创建和组装交给容器，DI 是把依赖交给对象的具体方式。

构造器注入让“没有这些依赖就不能正常创建服务”显式化，适合必需依赖和 final 字段。字段注入写得短，但对象依赖不在构造器表达，也不便直接构造测试对象。多个同类型 Bean 时需要明确选择规则，如 Qualifier、Primary 等，不能以为类型相同就一定知道选谁。

**项目追问：为什么有 ObjectProvider？** 会话服务清理状态时需要 Agent Provider，而 Provider 构建工具目录又会关联会话服务。当前会话服务用 `ObjectProvider<ReActAgentProvider>` 延迟获取，在真正清理时再取，避免立即构造整条循环依赖链。它解决此处获取时机问题，不意味着任意循环依赖都应该靠延迟访问掩盖。

## 41.3 Bean 生命周期和单例应该怎么讲

抓住主线即可：注册 Bean 定义 → 按需要实例化 → 注入依赖 → 初始化处理 → 提供给调用方 → 容器关闭时执行销毁回调。BeanPostProcessor 等扩展参与初始化前后，也可能提供代理对象；不必把所有扩展接口背成一长串。

项目 `StreamTaskManager` 在 `@PostConstruct` 订阅取消 Topic，在 `@PreDestroy` 移除监听器。这就是初始化和销毁与真实资源绑定的例子，不是纯概念题。

默认 singleton 的范围是每个容器、每个 Bean 定义，不是“全世界只存在一个 Java 对象”。prototype 表示取用时创建不同实例，也不自动让被它访问的共享资源线程安全。判断线程安全仍需检查共享可变状态，而非背作用域名称。[Spring Bean 作用域](https://docs.spring.io/spring-framework/reference/core/beans/factory-scopes.html)

## 41.4 AOP 怎么让注解产生行为

“写了 `@Transactional` 就有事务”中间少了一层：调用方通常拿到代理，代理先执行事务增强，再调用目标方法，最后根据结果提交或回滚。

```text
Controller
  → 会话服务代理：建立事务边界
  → 真正的 delete 方法：执行 SQL
  → 回到代理：决定提交 / 回滚
```

JDK 动态代理围绕接口生成代理；基于类的代理通过子类方式增强，因此 final/private 等方法边界需要注意。Spring AOP 的代理调用与 AspectJ 编织也不是同一种机制。对本项目应以实际代理方式和可被拦截的调用边界回答，不要只看见注解就保证生效。[Spring AOP 代理机制](https://docs.spring.io/spring-framework/reference/core/aop/proxying.html)

## 41.5 最常见的自调用题，按三种情况回答

**情况 A：外部调用有事务的 A，A 调普通 B，B 抛异常。** 如果 B 的数据库操作参与同一事务，异常向外传播且符合回滚规则，会影响外层事务。B 没注解不代表它的 SQL 在事务之外。

**情况 B：外部调用无事务的 A，A 用 this 调有事务注解的 B。** 常规代理模式下，内部调用没有经过代理，B 的注解不会独立启动事务。

**情况 C：外部调用有事务的 A，A 用 this 调有事务注解的 B。** B 的注解没有独立拦截，但 A 已经建立事务，B 的同线程同资源 SQL 通常仍参与 A 的事务。

本项目 `deleteBatch` 调 `delete` 属于第三类。说“自调用事务失效”时必须说明失效的是**内层注解的独立增强**，不能误说“整批 SQL 都没事务”。

## 41.6 异常、传播和异步：事务的三组边界

默认回滚规则通常针对 RuntimeException 和 Error，受配置及注解覆盖影响；项目删除显式设置 `rollbackFor=Exception.class`。如果在业务方法内捕获异常并正常返回，代理可能无法根据异常判断回滚，除非事务已被标记 rollback-only 等。不要一边吞异常一边宣称“有注解一定回滚”。[声明式事务设置](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)

传播行为先重点掌握三种：

| 传播 | 含义 | 典型风险 |
|---|---|---|
| REQUIRED | 有事务就参与，没有就创建 | 内部失败可能影响外层共同事务 |
| REQUIRES_NEW | 新建独立事务，挂起外层事务 | 外层回滚不撤销内层已提交结果，还需额外资源 |
| NESTED | 支持时使用保存点形成嵌套范围 | 取决于事务管理器/资源支持，不等于独立提交 |

这些传播方式的资源和提交边界见 [Spring 事务传播](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html)。

线程绑定的本地事务不会因为你调用了 `supplyAsync` 就自动传播到新线程。模型网络调用、Redis 操作和 SSE 发送也不受 PostgreSQL 回滚控制。把整次十几秒甚至更久的 Agent 调用包进长事务，会长期占用连接或锁，还无法把外部行为一起撤销。

项目把删表放在事务内，把运行清理放在 afterCommit，是在显式分开两个阶段。afterCommit 只保证触发时机，不提供失败重试和跨系统原子性。

## 41.7 MyBatis、MyBatis-Plus、JDBC 是什么关系

JDBC 是 Java 与关系数据库交互的基础接口；MyBatis 在其上管理 SQL 映射、参数绑定和结果映射；MyBatis-Plus 扩展通用 CRUD、条件构造、分页和逻辑删除等能力。

Mapper 返回 DO，Service 组织业务，Controller 对外返回 DTO/VO，是为了区分数据库表示、业务流程和接口契约。不是项目必须为每个类多写几个后缀，而是避免数据库字段变化直接泄露成前端接口变化。

`AgentMessageDO.blocks` 通过 TypeHandler 在 Java 对象与数据库 JSONB 之间转换。JSONB 提供结构化存储，TypeHandler 提供语言层映射；它们不是同一个功能。

## 41.8 #{} 与 ${}，不要只背一句安全与不安全

`#{}` 通常产生预编译参数位置，把值作为数据绑定；`${}` 是 SQL 文本替换，输入可能改变 SQL 结构。查询 userId 应绑定为值，不能拼成引号中的一段 SQL。[MyBatis FAQ](https://github.com/mybatis/mybatis-3/wiki/FAQ)

但参数位置不能直接替代任意表名或排序列。例如动态 ORDER BY 列名，需要服务端白名单选择固定片段，不能让用户传什么就替换什么。

本项目近期历史使用 `.last("limit " + scanWindow(turns))`。`last` 表达原始 SQL 后缀，其安全性来自此处值是内部整数计算，而不是 API 自动把所有字符串转成安全参数。若未来把前端任意排序表达式也传给 last，就改变了安全前提。

## 41.9 缓存、分页和逻辑删除的追问

MyBatis 一级缓存与 SqlSession 生命周期相关；二级缓存需看具体启用与映射配置，不能把它自动等同于全站 Redis 缓存。在 Spring 管理下，是否同一个事务/会话会影响实际复用范围。本项目答题时不把“Mapper 查过一次”说成“之后所有请求都不查数据库”。

分页的核心是数据库只返回需要的范围，而不是先把全表载入内存再截取。插件配置了不等于任意 selectList 自动分页；第 37 章的会话列表就是应区分的例子。

逻辑删除把“删除”变成业务状态。手写 SQL 未必自动附带 MyBatis-Plus 的逻辑删除条件，数据仍占空间，唯一性也需要重新设计。会话的部分唯一索引就是为了让已逻辑删除的旧行不占用有效会话键；框架状态 Mapper 则直接执行物理 DELETE，不能一概说所有表都是软删除。

## 41.10 三分钟演练

先解释 Spring Boot 组装哪些对象；再说明单例中的每轮状态怎么隔离；用删会话说明 AOP 事务；被问自调用时明确外层有没有事务；最后以 AgentStateMapper 的参数绑定和 upsert 收束数据库访问。

面经重点记录：6、307、309、327、1444、1445。[来源及项目对照](../appendices/backend-source-and-interview-map.md)

[上一章](40-backend-java-interview.md) · [下一章：SQL、索引与事务](42-backend-database-interview.md) · [返回首页](../README.md)
