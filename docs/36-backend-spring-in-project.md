# 第 36 章：Spring Boot 怎样把项目组装成服务

> 第一部分 · 项目应用。面经入口：Spring Boot 项目亮点、依赖注入、Bean 单例、AOP。

配套问答：[登录后为什么还要带 token](45-agent-request-study-qa.md#identity) · [Maven 与 Spring Boot 从构建到运行](45-agent-request-study-qa.md#boot-maven)。

## 36.1 Maven、Spring Boot、AgentScope 各管哪一段

从拿到源码到处理一次提问，中间有三个不同的问题。

Maven 回答：“编译时需要哪些代码和库，先构建哪个模块，怎样打包？”根 POM 声明 Java 17、统一依赖版本和七个模块。`dependencyManagement` 负责管理版本，并不表示每个模块自动引入表里所有依赖；子模块自己的 `dependencies` 决定实际引用。模块组织与运行时进程数量也不是一回事，七个 Maven 模块不能说成七个微服务。

Spring Boot 回答：“程序启动时创建哪些服务对象，它们之间怎么连接，怎样接收 HTTP 请求？”主应用入口是 `RagentApplication.main`，它调用 `SpringApplication.run`。主应用通过模块依赖获得业务代码，组件扫描发现服务，自动配置结合依赖和配置准备基础设施。

AgentScope 回答：“接到本轮输入以后，怎样反复调用模型、执行工具、处理事件与框架状态？”它由 Spring 管理的配置类和 Provider 组装，但模型不负责替 Spring 建立数据库连接或 HTTP 路由。

可以把它们连成一句话：**Maven 把零件准备好，Spring 把零件接成服务，AgentScope 在服务里执行 Agent 循环。**

## 36.2 一个 Service 到底是怎么获得依赖的

`AgentChatServiceImpl` 需要会话服务、Agent Provider、任务管理器和运行闸门。这些依赖是 `final` 字段，Lombok 的 `@RequiredArgsConstructor` 生成包含它们的构造器。Spring 创建 Service 时，找到容器中匹配的对象，调用这个构造器。

也就是说，业务代码调用 `conversationService.addUserMessage` 之前，没有在每次请求里手动创建数据库 Mapper、Redis 客户端和所有 Service。这些长期服务对象已经在容器中准备好，按依赖关系协作。

这里要区分三个角色：

- `@Service`、`@Component`：标记可被扫描和管理的项目对象。
- `@Configuration` 中的 `@Bean`：显式编写如何创建一个对象，特别适合外部库对象。
- 构造器注入：把已经管理的对象交给需要它的类，而不是到处写静态全局变量。

本项目中，`AgentEngineConfiguration.agentChatModel` 从 Agent 配置和供应商配置拼出模型客户端；`agentStateStore` 把 Mapper 交给 `PgAgentStateStore`。后者没有靠自己扫描成为组件，而是被 `@Bean` 方法创建。这就是同一工程里两种注册方式的具体例子。

## 36.3 接口有了，为什么不一定会生效

`@ConditionalOnAgentEngine` 是对条件注解的封装：当 `ragent.engine.type=agent` 时装配相关类。随仓库配置选择 Agent，因此对应 Controller、服务和配置参与组装。

理解条件装配时，按这个顺序判断：配置最终是什么 → 条件是否满足 → Bean 是否创建 → 请求是否经过它。只看到一个实现类，不能断言请求一定走它。

例如向量后端使用 `rag.vector.type=pg`。关键词与图谱不仅有后端类型，还有检索通道开关；后端客户端存在与“此次查询启用该通道”不是同一个决定。算法章节已经讲检索原理，本章关心的是 Spring 如何把选择落成对象关系。

这些配置一般在启动装配时决定结构，不是“每次用户提问都重新启动 Spring”。而 Agent 人设与工具目录则有自己的更新机制：Provider 会比较当前人设和目录指纹，在需要时懒重建 Agent。这是业务缓存策略，不是 Spring 容器整体重建。

## 36.4 单例为什么不会把所有用户的问题搅在一起

默认单例意味着同一个容器、同一个 Bean 定义共享一个实例，并不意味着这个实例天然线程安全。[Spring 官方作用域说明](https://docs.spring.io/spring-framework/reference/core/beans/factory-scopes.html)

项目采用两层状态安排：

| 长期共享对象 | 每轮单独创建的对象 |
|---|---|
| Controller、Service、Mapper、Redis 客户端、Provider | `SseEmitter`、`AgentRunHandle`、`AgentStreamEventBridge` |
| 管理依赖和协调入口 | 保存该轮输出、状态与取消设施 |

假设林辰和周敏同时请求，共享 Service 可以同时进入两次 `streamChat`，但两次调用各有自己的局部变量、taskId、Emitter 和输出缓冲区。危险的写法是给共享 Service 增加 `currentUserId`、`currentAnswer` 字段，再不断覆盖；项目的本轮数据不是这样保存的。

不过不能简化为“所有状态对象都每轮新建”。`ReActAgentProvider` 确实复用 Agent 实例，框架状态通过用户和会话键区分；Provider 自身用 `volatile cached` 发布缓存对象，用同步块避免竞争重建。它把 Agent 与创建该 Agent 时的目录快照成对返回，防止拿到新目录却使用旧实例。第 40 章再解释这里的可见性和互斥。

## 36.5 Mapper 接口没有实现类，为什么还能访问数据库

启动类的 `@MapperScan` 明确包含 Agent、知识库、用户等 Mapper 包。MyBatis 为接口生成代理；调用代理方法时，它定位 SQL，绑定参数，使用数据库连接执行，再把结果映射回来。

所以链路是：

```text
AgentConversationServiceImpl
  → AgentMessageMapper 代理
  → 生成或选择 SQL、绑定参数
  → JDBC 连接
  → PostgreSQL
  → 行数据映射为 AgentMessageDO
```

MyBatis-Plus 在此基础上提供 `BaseMapper` 的通用增删改查和 Lambda 条件构造。它减少重复 SQL，不负责把任意查询自动变成高性能查询。项目还配置了 PostgreSQL 分页插件，但只有真正使用分页查询的地方才会分页，普通 `selectList` 不会自动截成一页。

## 36.6 用户身份怎样从请求传到后台工作

用户上下文拦截器从 Sa-Token 登录态取用户编号，再经 `UserMapper` 查询用户信息，构造 `LoginUser` 放进 `UserContext`。它在 `afterCompletion` 中调用 `clear`。`UserContext` 内部使用 `TransmittableThreadLocal`，目的是让线程上下文具备受支持的跨线程池传递能力。

这里有两个容易混淆的点。

第一，ThreadLocal 不是“整个请求永远能读到的全局变量”。线程池会复用线程；异步任务可能切到其他线程。项目多个线程池用 `TtlExecutors` 包装，而 Agent 入口还显式捕获 `userId`，放入运行上下文并传给事件桥。显式携带身份比假设任何异步回调都有原线程上下文更清楚。

第二，源码中的清理回调不等于已经证明每一种 Servlet 异步调度都会在原线程及时清理。SSE 涉及初次处理与后续异步派发，需区分它们的生命周期。面试先解释当前身份流向；若追问严格的异步清理方案，可以提出在对应异步生命周期做清理与复核，而不要声称“用了 TTL 就绝不串号”。

身份确认后还需要资源授权。查询会话时加 `conversationId + userId`，停止时校验任务属主，是不同于“已经登录”的第二道判断。用户知道别人的会话编号，不等于应该能读写它。

## 36.7 面试追问链

**问：为什么选择 Spring Boot？**

“项目主要是 Java 服务，Spring Boot 把 Web 接口、依赖注入、数据访问和横切能力接到同一个应用里；AgentScope 专注 Agent 循环。我可以在同进程中复用既有知识检索和用户服务，不必因为引入 Agent 再拆一套服务。”这是从结构得到的工程解释，不冒充作者未公开的选型原话。

**追问：单例 Service 线程安全吗？**

“单例只决定实例数。依赖字段多为共享服务引用，本轮输出放在独立 RunHandle/EventBridge。确有共享可变状态的 Provider，用 volatile 和 synchronized 协调。”

**再追问：Mapper 为什么能注入？**

“MapperScan 注册代理，MyBatis 代理解释方法对应的 SQL，并调用 JDBC；MyBatis-Plus 为常见 CRUD 提供生成能力。”

本章面经落点：记录 208、307、1444、1445；具体来源见[附录](../appendices/backend-source-and-interview-map.md)。源码入口：根 POM、`RagentApplication`、`AgentEngineConfiguration`、`ReActAgentProvider`、`UserContextInterceptor`、`DataBaseConfiguration`。

[上一章](35-backend-request-map.md) · [下一章：数据库怎样保存会话与知识](37-backend-persistence-in-project.md) · [返回首页](../README.md)
