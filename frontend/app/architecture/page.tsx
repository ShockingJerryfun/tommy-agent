import Link from "next/link";
import type { ReactNode } from "react";
import {
  ArrowLeft,
  BrainCircuit,
  Cable,
  CheckCircle2,
  Database,
  GitBranch,
  Layers3,
  LockKeyhole,
  MessageSquareText,
  Network,
  Route,
  Server,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
} from "lucide-react";

const layers = [
  {
    title: "前端体验层",
    subtitle: "用户工作台",
    tone: "from-sky-500/18 to-cyan-400/8",
    icon: MessageSquareText,
    modules: [
      "Agent Shell：会话、运行态、设置和检查面板的组合边界。",
      "Message Stream：消息、推理片段、工具结果和错误恢复。",
      "Composer & Settings：输入、附件、头像、语言和架构入口。",
    ],
  },
  {
    title: "Next.js 边界层",
    subtitle: "路由与代理",
    tone: "from-indigo-500/16 to-blue-400/8",
    icon: Route,
    modules: [
      "App Router：工作台、分享页、架构页等产品页面。",
      "Agent API Proxy：隔离浏览器地址和后端服务端口。",
      "E2E Adapter：为前端测试提供可替换后端边界。",
    ],
  },
  {
    title: "后端 API 层",
    subtitle: "FastAPI 服务",
    tone: "from-emerald-500/16 to-teal-400/8",
    icon: Server,
    modules: [
      "Server App：生命周期、路由挂载、健康检查和后台维护。",
      "API Handlers：会话、消息、运行、附件、知识、审批和提示词。",
      "Schemas：前后端契约，避免内部对象直接泄漏。",
    ],
  },
  {
    title: "运行时编排层",
    subtitle: "Run lifecycle",
    tone: "from-violet-500/16 to-fuchsia-400/8",
    icon: GitBranch,
    modules: [
      "Run Manager：创建运行、推进状态、取消、重试和写回。",
      "Event Service：把图事件和工具事件整理为 UI 时间线。",
      "Run Inputs：整理历史、附件、前端设置和上下文输入。",
    ],
  },
  {
    title: "智能能力层",
    subtitle: "LangGraph, tools, memory context",
    tone: "from-amber-500/18 to-orange-400/8",
    icon: BrainCircuit,
    modules: [
      "LangGraph Graph：节点、路由、预算、审批和循环控制。",
      "Prompt Context：系统提示、用户背景、计划、记忆和工具约束。",
      "Tool Runtime & Subagents：工具目录、权限边界和子代理协作。",
    ],
  },
  {
    title: "存储与知识层",
    subtitle: "PostgreSQL persistence",
    tone: "from-rose-500/14 to-pink-400/8",
    icon: Database,
    modules: [
      "Store Facade：对运行时暴露少量稳定端口。",
      "Repositories：sessions、messages、runs、prompts、memories、metrics。",
      "Schema Registry：把结构演进产品化，而不是保留 migration 痕迹。",
    ],
  },
] as const;

const flows = [
  {
    title: "C4 分层",
    icon: Layers3,
    steps: "先看容器边界，再 zoom 到组件与动态链路，避免一张图混用太多抽象层级。",
  },
  {
    title: "动态视图",
    icon: Cable,
    steps: "用带标签的单向箭头表达请求、事件、上下文、存储和审批流向。",
  },
  {
    title: "LangGraph 视图",
    icon: BrainCircuit,
    steps: "单独展示 START、pre_run、planner、agent、action、critic、verification、END 的流转。",
  },
  {
    title: "安全视图",
    icon: ShieldCheck,
    steps: "把工具权限、人工审批、执行器、工作区和审计结果从主图中拆出来。",
  },
] as const;

const externalSystems = [
  {
    name: "Model Providers",
    body: "DeepSeek、OpenRouter 或 OpenAI 兼容接口提供模型能力。",
    icon: Sparkles,
  },
  {
    name: "Local Workspace",
    body: "文件系统、shell、项目目录和附件存储构成可执行环境。",
    icon: TerminalSquare,
  },
  {
    name: "MCP & Web",
    body: "通过工具模块接入外部服务、网页检索和协作能力。",
    icon: Network,
  },
  {
    name: "Quality Loop",
    body: "观测、回放、评测和维护任务持续检查运行质量。",
    icon: CheckCircle2,
  },
] as const;

export default function ArchitecturePage() {
  return (
    <main className="min-h-screen overflow-x-hidden bg-[rgb(var(--background-soft))] px-4 py-5 text-slate-900 dark:bg-slate-950 dark:text-slate-100 sm:px-6 lg:px-8">
      <div className="mx-auto flex w-full max-w-[92rem] flex-col gap-5">
        <header className="admin-toolbar flex flex-col gap-4 px-5 py-5 sm:flex-row sm:items-center sm:justify-between lg:px-7">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
              Tommy Architecture
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 dark:text-white sm:text-4xl">
              Tommy 系统设计图
            </h1>
            <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-600 dark:text-slate-300">
              这版图稿按“总览、图执行、数据事件、安全审批”拆成多张视图。每张图只回答一个架构问题，
              用有方向、有标签的连线说明模块如何协作，而不进入函数实现细节。
            </p>
          </div>
          <Link
            href="/"
            className="ios-glass-pill soft-focus-ring liquid-hover inline-flex min-h-11 items-center justify-center gap-2 px-4 text-sm font-semibold text-slate-700 dark:text-slate-200"
          >
            <ArrowLeft className="h-4 w-4" />
            返回工作台
          </Link>
        </header>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="space-y-4">
            <DiagramPanel
              eyebrow="C4 Container + Dynamic View"
              title="系统容器与交互总览"
              note="回答：用户请求如何从前端进入后端，如何被运行时、LangGraph、工具、存储和外部系统共同完成。"
            >
              <ContainerInteractionDiagram />
            </DiagramPanel>

            <DiagramPanel
              eyebrow="LangGraph Runtime View"
              title="LangGraph 流程可视图"
              note="回答：一次 Agent run 在图节点中如何前进、何时调用工具、何时等待审批、何时进入质量检查。"
            >
              <LangGraphFlowDiagram />
            </DiagramPanel>

            <div className="grid gap-4 2xl:grid-cols-2">
              <DiagramPanel
                eyebrow="Data + Event View"
                title="数据与事件流"
                note="回答：消息、附件、上下文、运行事件、指标和记忆分别在哪里产生、流转和持久化。"
              >
                <DataEventDiagram />
              </DiagramPanel>

              <DiagramPanel
                eyebrow="Security View"
                title="工具审批与安全边界"
                note="回答：高风险工具调用如何被策略拦截、人工批准、执行和审计。"
              >
                <ToolApprovalDiagram />
              </DiagramPanel>
            </div>

            <ModuleSummaryGrid />
          </div>

          <aside className="space-y-4">
            <section className="liquid-glass-strong rounded-[2rem] p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                Diagram Strategy
              </p>
              <h2 className="mt-1 text-lg font-semibold tracking-tight">
                阅读顺序
              </h2>
              <div className="mt-4 space-y-3">
                {flows.map((flow) => (
                  <FlowItem key={flow.title} flow={flow} />
                ))}
              </div>
            </section>

            <section className="liquid-glass-strong rounded-[2rem] p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                External Boundary
              </p>
              <h2 className="mt-1 text-lg font-semibold tracking-tight">
                外部依赖
              </h2>
              <div className="mt-4 grid gap-3">
                {externalSystems.map((system) => (
                  <ExternalSystem key={system.name} system={system} />
                ))}
              </div>
            </section>
          </aside>
        </section>
      </div>
    </main>
  );
}

function DiagramPanel({
  eyebrow,
  title,
  note,
  children,
}: {
  eyebrow: string;
  title: string;
  note: string;
  children: ReactNode;
}) {
  return (
    <section className="liquid-glass-strong rounded-[2rem] p-4 sm:p-5 lg:p-6">
      <div className="mb-5 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {eyebrow}
          </p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight">{title}</h2>
        </div>
        <p className="max-w-xl text-xs leading-5 text-slate-500 dark:text-slate-400">
          {note}
        </p>
      </div>
      {children}
    </section>
  );
}

function DiagramShell({
  label,
  viewBox,
  minWidth,
  children,
}: {
  label: string;
  viewBox: string;
  minWidth: string;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded-[1.7rem] bg-white/55 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.75),0_18px_52px_rgba(15,23,42,0.08)] backdrop-blur-xl dark:bg-white/[0.055] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_18px_52px_rgba(0,0,0,0.3)]">
      <svg
        role="img"
        aria-label={label}
        viewBox={viewBox}
        className={`${minWidth} text-slate-900 dark:text-slate-100`}
      >
        <DiagramDefs />
        {children}
      </svg>
    </div>
  );
}

function DiagramDefs() {
  return (
    <defs>
      <linearGradient id="panel" x1="0" x2="1" y1="0" y2="1">
        <stop offset="0%" stopColor="rgba(255,255,255,0.94)" />
        <stop offset="100%" stopColor="rgba(241,245,249,0.72)" />
      </linearGradient>
      <linearGradient id="blue" x1="0" x2="1" y1="0" y2="1">
        <stop offset="0%" stopColor="#dbeafe" />
        <stop offset="100%" stopColor="#e0f2fe" />
      </linearGradient>
      <linearGradient id="green" x1="0" x2="1" y1="0" y2="1">
        <stop offset="0%" stopColor="#dcfce7" />
        <stop offset="100%" stopColor="#ccfbf1" />
      </linearGradient>
      <linearGradient id="violet" x1="0" x2="1" y1="0" y2="1">
        <stop offset="0%" stopColor="#ede9fe" />
        <stop offset="100%" stopColor="#fae8ff" />
      </linearGradient>
      <linearGradient id="amber" x1="0" x2="1" y1="0" y2="1">
        <stop offset="0%" stopColor="#fef3c7" />
        <stop offset="100%" stopColor="#ffedd5" />
      </linearGradient>
      <linearGradient id="rose" x1="0" x2="1" y1="0" y2="1">
        <stop offset="0%" stopColor="#ffe4e6" />
        <stop offset="100%" stopColor="#fce7f3" />
      </linearGradient>
      <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">
        <feDropShadow dx="0" dy="14" stdDeviation="16" floodColor="#0f172a" floodOpacity="0.13" />
      </filter>
      <marker id="arrowMain" markerHeight="10" markerWidth="10" orient="auto" refX="8" refY="5">
        <path d="M0,0 L10,5 L0,10 Z" fill="#334155" />
      </marker>
      <marker id="arrowSoft" markerHeight="10" markerWidth="10" orient="auto" refX="8" refY="5">
        <path d="M0,0 L10,5 L0,10 Z" fill="#64748b" />
      </marker>
      <style>
        {`
          .node-title { font: 700 18px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #0f172a; }
          .node-label { font: 700 12px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #64748b; letter-spacing: .08em; }
          .node-copy { font: 500 13px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #475569; }
          .lane-label { font: 700 13px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #334155; }
          .flow-label { font: 700 12px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #1e293b; }
          .small-copy { font: 600 11px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #64748b; }
        `}
      </style>
    </defs>
  );
}

function NodeBox({
  x,
  y,
  width,
  height,
  fill,
  label,
  title,
  lines,
}: {
  x: number;
  y: number;
  width: number;
  height: number;
  fill: string;
  label: string;
  title: string;
  lines: string[];
}) {
  return (
    <g filter="url(#shadow)">
      <rect x={x} y={y} width={width} height={height} rx="26" fill={fill} />
      <text x={x + 24} y={y + 34} className="node-label">
        {label}
      </text>
      <text x={x + 24} y={y + 62} className="node-title">
        {title}
      </text>
      {lines.map((line, index) => (
        <text key={line} x={x + 24} y={y + 88 + index * 22} className="node-copy">
          {line}
        </text>
      ))}
    </g>
  );
}

function FlowPath({
  d,
  label,
  x,
  y,
  dashed = false,
  main = false,
}: {
  d: string;
  label: string;
  x: number;
  y: number;
  dashed?: boolean;
  main?: boolean;
}) {
  return (
    <g>
      <path
        d={d}
        stroke={main ? "#334155" : "#64748b"}
        strokeWidth={main ? 3.5 : 2.5}
        fill="none"
        strokeDasharray={dashed ? "8 8" : undefined}
        markerEnd={main ? "url(#arrowMain)" : "url(#arrowSoft)"}
      />
      <text x={x} y={y} className="flow-label">
        {label}
      </text>
    </g>
  );
}

function ContainerInteractionDiagram() {
  return (
    <DiagramShell label="Tommy C4 容器交互图" viewBox="0 0 1280 820" minWidth="min-w-[1080px]">
      <rect x="10" y="10" width="1260" height="800" rx="34" fill="url(#panel)" />
      <text x="52" y="62" className="lane-label">C4 容器视图：系统边界、容器职责和动态交互</text>
      <path d="M56 112 H1224" stroke="#cbd5e1" strokeWidth="1" strokeDasharray="7 9" />
      <path d="M56 380 H1224" stroke="#cbd5e1" strokeWidth="1" strokeDasharray="7 9" />
      <path d="M56 625 H1224" stroke="#cbd5e1" strokeWidth="1" strokeDasharray="7 9" />

      <NodeBox x={64} y={135} width={210} height={132} fill="url(#blue)" label="CLIENT" title="前端体验层" lines={["Agent Shell", "消息流 / 设置 / 附件"]} />
      <NodeBox x={352} y={135} width={210} height={132} fill="#ffffff" label="NEXT" title="边界层" lines={["App Router", "Agent API Proxy"]} />
      <NodeBox x={640} y={135} width={230} height={132} fill="url(#green)" label="FASTAPI" title="后端 API 层" lines={["API Handlers", "Schemas / Lifespan"]} />
      <NodeBox x={430} y={410} width={240} height={140} fill="url(#violet)" label="RUNTIME" title="运行时编排层" lines={["Run Manager", "Event Service / Inputs"]} />
      <NodeBox x={784} y={390} width={270} height={168} fill="url(#amber)" label="LANGGRAPH" title="智能能力层" lines={["StateGraph nodes", "Prompt Context", "Tools / Subagents"]} />
      <NodeBox x={70} y={660} width={230} height={118} fill="#ffffff" label="TOOLING" title="工具运行时" lines={["权限策略 / 审批", "shell / file / web / MCP"]} />
      <NodeBox x={420} y={660} width={248} height={118} fill="url(#rose)" label="POSTGRES" title="存储与知识层" lines={["Store Facade", "Repos / Schema Registry"]} />
      <NodeBox x={792} y={660} width={260} height={118} fill="#ffffff" label="EXTERNAL" title="外部依赖" lines={["模型服务", "文件系统 / MCP / Web"]} />

      <FlowPath d="M274 201 C306 201 320 201 352 201" label="页面事件 / 上传 / 设置" x={286} y={185} main />
      <FlowPath d="M562 201 C596 201 608 201 640 201" label="HTTP / SSE 代理" x={580} y={185} main />
      <FlowPath d="M748 267 C748 324 628 360 558 410" label="创建 run" x={644} y={334} main />
      <FlowPath d="M670 480 C710 480 738 474 784 468" label="驱动图执行" x={698} y={458} main />
      <FlowPath d="M1054 470 C1120 426 1138 306 990 250 C952 236 920 224 870 210" label="模型输出 / 工具结果" x={1010} y={304} main />
      <FlowPath d="M800 390 C586 300 346 286 188 267" label="事件流回传" x={414} y={312} dashed />
      <FlowPath d="M790 520 C612 602 432 630 260 660" label="工具请求 / 审批" x={430} y={610} dashed />
      <FlowPath d="M300 720 C344 720 374 720 420 720" label="工具结果归档" x={318} y={704} dashed />
      <FlowPath d="M540 660 C514 610 492 574 474 550" label="历史 / 记忆 / 指标" x={512} y={612} dashed />
      <FlowPath d="M900 558 C906 608 916 632 934 660" label="模型与外部调用" x={928} y={616} dashed />
      <FlowPath d="M792 720 C736 720 720 720 668 720" label="产物 / 指标" x={704} y={704} dashed />
    </DiagramShell>
  );
}

function LangGraphFlowDiagram() {
  const nodes = [
    ["START", 72, 162, "#ffffff"],
    ["pre_run", 220, 162, "url(#green)"],
    ["planner", 378, 162, "url(#blue)"],
    ["agent", 550, 162, "url(#amber)"],
    ["action", 720, 162, "url(#violet)"],
    ["critic", 900, 162, "url(#rose)"],
    ["reflector", 900, 352, "#ffffff"],
    ["verification", 550, 352, "url(#green)"],
    ["END", 220, 352, "#ffffff"],
  ] as const;

  return (
    <DiagramShell label="Tommy LangGraph 流程可视图" viewBox="0 0 1120 560" minWidth="min-w-[980px]">
      <rect x="10" y="10" width="1100" height="540" rx="34" fill="url(#panel)" />
      <text x="48" y="58" className="lane-label">LangGraph run：节点、条件边、循环和中断点</text>
      <text x="48" y="92" className="small-copy">状态对象在节点间传递；边负责决定下一步；审批会让 action 暂停并等待用户确认。</text>

      {nodes.map(([name, x, y, fill]) => (
        <g key={name} filter="url(#shadow)">
          <rect x={x} y={y} width="128" height="78" rx="22" fill={fill} />
          <text x={x + 24} y={y + 34} className="node-title">{name}</text>
          <text x={x + 24} y={y + 58} className="small-copy">
            {name === "agent" ? "LLM + state" : name === "action" ? "tool calls" : name === "critic" ? "quality gate" : "state step"}
          </text>
        </g>
      ))}

      <FlowPath d="M200 201 H220" label="" x={0} y={0} main />
      <FlowPath d="M348 201 H378" label="" x={0} y={0} main />
      <FlowPath d="M506 201 H550" label="" x={0} y={0} main />
      <FlowPath d="M678 201 H720" label="需要工具" x={672} y={188} main />
      <FlowPath d="M848 201 H900" label="无需工具" x={840} y={188} main />
      <FlowPath d="M900 230 C810 300 700 322 614 352" label="完成后验证" x={716} y={306} main />
      <FlowPath d="M550 392 H348" label="通过" x={430} y={378} main />
      <FlowPath d="M220 392 C136 392 110 320 136 240" label="结束响应" x={94} y={320} main />

      <FlowPath d="M784 240 C764 302 698 344 614 370" label="工具结果回写 state" x={638} y={328} dashed />
      <FlowPath d="M720 188 C640 120 548 116 476 162" label="继续思考循环" x={548} y={124} dashed />
      <FlowPath d="M964 240 V352" label="需要反思" x={982} y={296} dashed />
      <FlowPath d="M900 392 C794 438 676 438 614 392" label="修正计划" x={718} y={450} dashed />

      <g filter="url(#shadow)">
        <rect x="72" y="456" width="420" height="56" rx="18" fill="rgba(255,255,255,0.72)" />
        <text x="98" y="490" className="node-copy">checkpoint：每个 super-step 写入可恢复状态</text>
      </g>
      <g filter="url(#shadow)">
        <rect x="548" y="456" width="420" height="56" rx="18" fill="rgba(255,255,255,0.72)" />
        <text x="574" y="490" className="node-copy">stream events：node_start / tool_call / approval_wait / model_output</text>
      </g>
    </DiagramShell>
  );
}

function DataEventDiagram() {
  return (
    <DiagramShell label="Tommy 数据与事件流图" viewBox="0 0 860 620" minWidth="min-w-[760px]">
      <rect x="10" y="10" width="840" height="600" rx="34" fill="url(#panel)" />
      <text x="46" y="58" className="lane-label">数据与事件流：写模型、读上下文、推 UI</text>

      <NodeBox x={58} y={100} width={180} height={118} fill="url(#blue)" label="INPUT" title="用户输入" lines={["message", "attachments"]} />
      <NodeBox x={330} y={92} width={200} height={136} fill="url(#violet)" label="RUN INPUTS" title="输入整理" lines={["history", "frontend settings", "attachment refs"]} />
      <NodeBox x={612} y={100} width={180} height={118} fill="url(#amber)" label="CONTEXT" title="上下文组装" lines={["memory", "plan", "tool policy"]} />
      <NodeBox x={98} y={346} width={190} height={132} fill="#ffffff" label="EVENT BUS" title="事件服务" lines={["SSE stream", "run timeline"]} />
      <NodeBox x={360} y={340} width={190} height={144} fill="url(#rose)" label="STORE" title="持久化模型" lines={["sessions", "messages", "runs", "run_events"]} />
      <NodeBox x={610} y={346} width={190} height={132} fill="url(#green)" label="MEMORY" title="知识与记忆" lines={["memories", "prompts", "metrics"]} />

      <FlowPath d="M238 158 H330" label="payload" x={260} y={144} main />
      <FlowPath d="M530 160 H612" label="context request" x={540} y={146} main />
      <FlowPath d="M702 218 C696 286 640 318 520 340" label="memory hits" x={612} y={290} dashed />
      <FlowPath d="M430 228 C404 278 382 314 362 350" label="run created" x={368} y={286} main />
      <FlowPath d="M330 404 H288" label="事件流回传" x={292} y={392} dashed />
      <FlowPath d="M288 412 H360" label="event persisted" x={300} y={434} dashed />
      <FlowPath d="M550 412 H610" label="memory write" x={552} y={398} dashed />
    </DiagramShell>
  );
}

function ToolApprovalDiagram() {
  return (
    <DiagramShell label="Tommy 工具审批与安全图" viewBox="0 0 860 620" minWidth="min-w-[760px]">
      <rect x="10" y="10" width="840" height="600" rx="34" fill="url(#panel)" />
      <text x="46" y="58" className="lane-label">工具审批与安全：策略先行，人工确认，可审计执行</text>

      <NodeBox x={58} y={118} width={188} height={118} fill="url(#amber)" label="LANGGRAPH" title="工具意图" lines={["tool name", "args", "risk context"]} />
      <NodeBox x={336} y={112} width={200} height={132} fill="url(#violet)" label="POLICY" title="权限策略" lines={["allow", "approval required", "deny"]} />
      <NodeBox x={620} y={118} width={180} height={118} fill="url(#blue)" label="HUMAN" title="审批面板" lines={["approve", "reject"]} />
      <NodeBox x={120} y={360} width={190} height={128} fill="url(#green)" label="EXECUTOR" title="执行器" lines={["sandbox boundary", "timeout", "result capture"]} />
      <NodeBox x={390} y={358} width={190} height={132} fill="#ffffff" label="WORKSPACE" title="工作区" lines={["filesystem", "shell", "web / MCP"]} />
      <NodeBox x={646} y={360} width={160} height={128} fill="url(#rose)" label="AUDIT" title="审计写入" lines={["tool_calls", "run_events"]} />

      <FlowPath d="M246 177 H336" label="工具请求" x={268} y={162} main />
      <FlowPath d="M536 160 H620" label="高风险审批" x={546} y={145} main />
      <FlowPath d="M620 208 C486 280 350 312 244 360" label="批准后执行" x={410} y={304} main />
      <FlowPath d="M310 424 H390" label="受控访问" x={326} y={410} main />
      <FlowPath d="M580 424 H646" label="结果记录" x={590} y={410} dashed />
      <FlowPath d="M646 402 C500 292 328 260 220 236" label="可观测事件" x={390} y={260} dashed />
      <FlowPath d="M438 244 C394 300 328 334 246 368" label="低风险直通" x={288} y={324} dashed />
      <text x="618" y="274" className="flow-label">拒绝：回写 state，不执行工具</text>
      <path d="M704 236 C704 266 688 282 650 292" stroke="#ef4444" strokeWidth="2.5" fill="none" strokeDasharray="7 7" markerEnd="url(#arrowSoft)" />
    </DiagramShell>
  );
}

function ModuleSummaryGrid() {
  return (
    <section className="liquid-glass-strong rounded-[2rem] p-4 sm:p-5 lg:p-6">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
        Component Index
      </p>
      <h2 className="mt-1 text-xl font-semibold tracking-tight">
        模块索引
      </h2>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {layers.map((layer) => {
          const Icon = layer.icon;
          return (
            <section
              key={layer.title}
              className="rounded-[1.35rem] bg-white/58 p-4 shadow-sm backdrop-blur dark:bg-white/[0.055]"
            >
              <div className="flex items-center gap-2.5">
                <span className={`flex h-9 w-9 items-center justify-center rounded-2xl bg-gradient-to-br ${layer.tone}`}>
                  <Icon className="h-4 w-4 text-slate-700 dark:text-slate-100" />
                </span>
                <div>
                  <h3 className="text-sm font-semibold">{layer.title}</h3>
                  <p className="text-[11px] font-medium text-slate-400">
                    {layer.subtitle}
                  </p>
                </div>
              </div>
              <ul className="mt-3 space-y-1.5 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {layer.modules.map((module) => (
                  <li key={module}>{module}</li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </section>
  );
}

function FlowItem({ flow }: { flow: (typeof flows)[number] }) {
  const Icon = flow.icon;

  return (
    <div className="rounded-[1.25rem] bg-white/60 p-3.5 shadow-sm dark:bg-white/[0.055]">
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-white/75 shadow-sm dark:bg-white/10">
          <Icon className="h-4 w-4 text-slate-600 dark:text-slate-200" />
        </span>
        <p className="text-sm font-semibold">{flow.title}</p>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
        {flow.steps}
      </p>
    </div>
  );
}

function ExternalSystem({
  system,
}: {
  system: (typeof externalSystems)[number];
}) {
  const Icon = system.icon;

  return (
    <div className="flex gap-3 rounded-[1.25rem] bg-white/60 p-3.5 shadow-sm dark:bg-white/[0.055]">
      <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-white/75 shadow-sm dark:bg-white/10">
        <Icon className="h-4 w-4 text-slate-600 dark:text-slate-200" />
      </span>
      <div className="min-w-0">
        <p className="text-sm font-semibold">{system.name}</p>
        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
          {system.body}
        </p>
      </div>
    </div>
  );
}
