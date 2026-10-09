"""
RAG 服务 — 项目核心

用 LangGraph 编排完整的 RAG 管线：
  用户问题 → 查询改写 → 混合检索 → 生成回答 → 置信度评估

特性：
- 混合检索：Qdrant 一次查询做 dense（语义）+ sparse（BM25 关键词）双路召回，
  服务端 RRF 融合，再交给 CrossEncoder 精排
- 多轮对话：自动指代消解 + add_messages 自动追加 + AsyncPostgresSaver 持久化
- 流式输出：SSE 格式，逐阶段返回进度（来源 → 回答 → 置信度 → 完成）
"""
import json
import uuid
from typing import TypedDict, Annotated, Any, AsyncGenerator, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.config import get_stream_writer
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from core.config import settings
from models.chat import ChatResponse, SourceInfo


# ==================== 状态定义 ====================

class RAGState(TypedDict):
    """LangGraph 状态，定义所有节点间传递的字段"""
    query: str
    messages: Annotated[list, add_messages]  # add_messages 自动追加，无需手动维护
    summary: str                               # 历史消息摘要（消息过多时自动压缩）
    summarized_count: int                      # 已压缩的消息条数（增量式摘要用）
    documents: list[Document]
    context: str
    answer: str
    sources: list[dict[str, Any]]
    confidence: float
    chitchat: bool                             # 改写节点判定为闲聊（当场答完，不进检索）


# ==================== 提示词模板 ====================

RAG_SYSTEM_PROMPT = """你是一个专业的问答助手。请基于提供的上下文信息回答用户的问题。

重要规则：
1. 只使用提供的上下文信息来回答问题
2. 如果上下文中没有相关信息，请告诉用户"知识库中暂无相关内容，建议上传相关文档或换个问题试试"
3. 回答要准确、简洁、有条理
4. 如果有历史摘要，其记录了更早的对话信息，但近期对话的优先级更高（用户可能在纠正之前的信息）
5. 上下文每段以 [来源] 开头，表示该段内容出自哪个文件
6. 如果用户没有指明对象（例如问"保修期外怎么维修"却没说是哪个产品），回答开头先说明你依据的是哪份文档
上下文信息：
{context}
{summary}"""

# 检索为空时的提示词
#
# 单独一个节点、单独一段提示词，关键是这里【没有"回答用户的问题"这条指令】——
# 模型不处在"可以回答"的位置上。靠提示词禁止它用自身知识作答只是第二道保险，
# 第一道是它压根没被要求回答。
NO_ANSWER_SYSTEM_PROMPT = """你是一个知识库问答助手。用户提出了一个问题，检索没有在知识库中找到相关资料。

请简要说明这一点，并告诉用户可以补充什么信息、或怎么换个问法。
不要用你自己的知识回答这个问题——即使用户问的是你熟悉的常识，也要如实说明知识库里没有相关资料。
回答要简洁，两三句话即可。

如果有历史摘要，其记录了更早的对话信息，但近期对话的优先级更高
{summary}"""

# 下面 JSON 示例里的花括号要写成双写（{{ }}）——这段提示词走 ChatPromptTemplate，
# 单写的 { 会被模板引擎当成要填的变量。改这段时别忘了。
REWRITE_SYSTEM_PROMPT = """你是一个查询优化专家。判断用户输入属于哪种情况，只输出 JSON。

情况 A —— 用户在问需要查阅知识库的具体问题：
  把改写后的查询放在 query 字段，is_chitchat 为 false。

情况 B —— 用户在闲聊（问候、寒暄、与知识库内容无关的对话）：
  直接给一个得体的回复放在 reply 字段，is_chitchat 为 true。

判断要保守：只要问题涉及具体信息、事实、专有名词、编号、政策、数据、流程，
一律按情况 A 处理。只有明显是问候或闲聊时才走情况 B。

情况 A 的改写规则：
1. 口语化或模糊措辞 → 替换为精确、正式的表达
2. 考虑同义词和近义词的多样性，如果用户用词不够精准，尝试用更通用的术语替换
3. 多轮对话时，结合历史进行指代消解
4. 改写后必须保持自然语言句式，禁止堆砌关键词
5. 改写只做指代消解和用词优化：不做内容加工

输出格式（只输出 JSON，不要任何解释或代码块标记）：
{{"is_chitchat": false, "query": "改写后的查询"}}
{{"is_chitchat": true, "reply": "回复内容"}}"""

SUMMARIZE_SYSTEM_PROMPT = """你是一个对话摘要专家。请将以下对话历史压缩为一段简洁的摘要，保留关键信息（用户姓名、偏好、重要结论等）。只返回摘要文本，不要添加解释。"""


def _loads_json(text: str) -> dict:
    """解析模型返回的 JSON，容忍被 ``` 代码块包起来（JSON Mode 下一般不会，但便宜）"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(t)

EVAL_SYSTEM_PROMPT = """评估以下回答的置信度（0-1），参考标准：
  1.0 — 完全基于上下文，准确、完整
  0.8 — 基于上下文，基本准确，略有遗漏
  0.6 — 部分基于上下文，存在推断或不够完整
  0.4 — 与上下文关联弱
  0.2 — 几乎无关或编造
只返回一个数字。"""


# ==================== RAG 服务类 ====================

class RAGService:
    """
    RAG 管线总控

    混合检索原理：
      dense（语义匹配）  — 同义词、近义表达也能命中，但可能漏掉精确关键词
      sparse（BM25）     — 精确匹配术语、人名、编号等，但不懂同义词
      两路在 Qdrant 服务端用 RRF 融合，互补短板
    """

    def __init__(self, vector_store, llm, json_llm,
                 checkpointer: AsyncPostgresSaver, embeddings):
        self.vector_store = vector_store    # Qdrant 混合检索实例（dense + sparse）
        self.llm = llm                      # Qwen LLM
        self.json_llm = json_llm            # JSON Mode：改写节点的双形态输出
        self.checkpointer = checkpointer    # AsyncPostgresSaver（自动持久化对话状态）
        self.embeddings = embeddings        # AliyunEmbeddings

        # 组装提示词模板

        # RAG 问答：文档上下文 + 历史对话
        self.rag_prompt = ChatPromptTemplate.from_messages([
            ("system", RAG_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{query}"),
        ])
        # 改写 / 闲聊分流（双形态 JSON）
        self.rewrite_prompt = ChatPromptTemplate.from_messages([
            ("system", REWRITE_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "用户输入：{query}"),
        ])
        # 检索为空时的弃答
        self.no_answer_prompt = ChatPromptTemplate.from_messages([
            ("system", NO_ANSWER_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{query}"),
        ])
        # 置信度评估
        self.eval_prompt = ChatPromptTemplate.from_messages([    
            ("system", EVAL_SYSTEM_PROMPT),
            ("human", "上下文：{context}\n\n问题：{query}\n\n回答：{answer}\n\n置信度（0-1）："),
        ])
        # 历史摘要
        self.summarize_prompt = ChatPromptTemplate.from_messages([  
            ("system", SUMMARIZE_SYSTEM_PROMPT),
            ("human", "对话历史：\n{messages}"),
        ])

        # 编译 LangGraph 管线（带 AsyncPostgresSaver 自动持久化）
        self.graph = self._build_graph()

    # ==================== 重排序 ====================

    def _rerank(self, query: str, docs: list[Document]) -> list[Document]:
        """Cross-Encoder 重排序：联合编码精排，比向量相似度更准"""
        if len(docs) <= 1:
            return docs

        # 模型只加载一次，缓存在实例上
        if not hasattr(self, "_reranker"):
            self._reranker = CrossEncoder(
                "BAAI/bge-reranker-base",
                model_kwargs={"torch_dtype": "auto"},
            )

        pairs = [(query, doc.page_content) for doc in docs]
        scores = self._reranker.predict(pairs)
        ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        return [doc for doc, s in ranked if s >= 0.3]

    # ==================== 构建 LangGraph ====================

    def _build_graph(self):
        """构建 RAG 管线，add_messages 自动管理对话历史

        改写和检索之后各有一个条件分流：
        - 改写节点：明显闲聊 → 当场答完直接结束（省掉检索和生成）
        - 检索节点：精排后一条不剩 → 走弃答节点，不进生成节点
        """
        builder = StateGraph(RAGState)

        builder.add_node("summarize", self._node_summarize)
        builder.add_node("rewrite_query", self._node_rewrite_query)
        builder.add_node("retrieve_documents", self._node_retrieve_documents)
        builder.add_node("generate_answer", self._node_generate_answer)
        builder.add_node("no_answer", self._node_no_answer)
        builder.add_node("evaluate_confidence", self._node_evaluate_confidence)

        builder.add_edge(START, "summarize")
        builder.add_edge("summarize", "rewrite_query")

        builder.add_conditional_edges(
            "rewrite_query",
            self._route_after_rewrite,
            {"retrieve_documents": "retrieve_documents", "end": END},
        )
        builder.add_conditional_edges(
            "retrieve_documents",
            self._route_after_retrieve,
            {"generate_answer": "generate_answer", "no_answer": "no_answer"},
        )

        builder.add_edge("generate_answer", "evaluate_confidence")
        builder.add_edge("evaluate_confidence", END)
        builder.add_edge("no_answer", END)

        return builder.compile(checkpointer=self.checkpointer)

    # ==================== 5 个节点函数 ====================

    async def _node_summarize(self, state: RAGState) -> dict:
        """节点0：历史消息过多时自动压缩旧消息为摘要（async — LLM 调用不占线程池位）"""
        msgs = state["messages"][:-1]     # 排除当前用户问题（还没被回答，不是完整轮次）
        window = 8                        # 未压缩消息达 8 条（4 完整轮次）时触发
        keep = 4                          # 压缩后保留最近 4 条
        done = state.get("summarized_count", 0)   # 已压缩的消息条数
        fresh = len(msgs) - done                  # 未压缩的消息数
        if fresh < window:                        # 未压缩还不够多，跳过
            return {}

        compress = fresh - keep                   # 压缩掉超出保留量的部分
        batch = msgs[done:done + compress]
        text = "\n".join([f"[{m.type}] {m.content}" for m in batch])
        prev = state.get("summary", "").replace("\n历史摘要：", "").strip()
        prompt_text = f"已有摘要：{prev}\n\n新增对话：\n{text}\n\n请整合为一段摘要。" if prev else f"对话历史：\n{text}"

        try:
            chain = self.summarize_prompt | self.llm | StrOutputParser()
            result = await chain.ainvoke({"messages": prompt_text})
        except Exception as e:
            # 摘要失败降级：跳过本轮压缩，后续轮次再触发，管线不崩
            print(f"⚠️ 摘要节点异常: {type(e).__name__}: {e}")
            return {}
        done += compress
        return {"summary": f"\n历史摘要：{result}\n", "summarized_count": done}

    async def _node_rewrite_query(self, state: RAGState) -> dict:
        """节点1：改写查询，或判定为闲聊就地答完

        一次调用干两件事，靠 JSON 的 is_chitchat 区分。闲聊在这里就终结了——不检索、
        不生成，省掉两次调用。判断必须保守（规则见 REWRITE_SYSTEM_PROMPT）：真问题被
        误判成闲聊的话会跳过检索，又变成用模型自身知识作答，等于把刚修好的问题换个门放回来。

        解析失败一律降级成"用原问题检索"——改写是优化项，原问题也能查。
        """
        prev = state["messages"][:-1]              # 排除当前问题（由 add_messages 自动追加）
        writer = get_stream_writer()
        writer({"event": "progress", "data": "正在分析问题"})
        done = state.get("summarized_count", 0)    # 已压缩多少条
        fresh = prev[done:]                        # 所有未压缩消息（≤ 8 条，summarize 节点保证）

        try:
            chain = self.rewrite_prompt | self.json_llm | StrOutputParser()
            raw = await chain.ainvoke({
                "query": state["query"],
                "chat_history": fresh,
            })
            data = _loads_json(raw)
        except Exception as e:
            print(f"⚠️ 查询改写节点异常（降级为原问题检索）: {type(e).__name__}: {e}")
            return {}

        if data.get("is_chitchat"):
            reply = str(data.get("reply") or "").strip()
            if not reply:
                return {}
            writer(reply)
            # 必须同时写 answer 和 messages：短路路径也要留下一条 AI 消息，否则消息不成对，
            # 下一轮的 messages[:-1] 和摘要的 window=8/keep=4 都会错位
            return {
                "chitchat": True,
                "answer": reply,
                "messages": [AIMessage(content=reply)],
            }

        rewritten = str(data.get("query") or "").strip()
        # 防御：空返回直接降级为原问题
        if not rewritten:
            return {}
        return {"query": rewritten}

    def _route_after_rewrite(self, state: RAGState) -> Literal["retrieve_documents", "end"]:
        """闲聊已在改写节点答完，直接结束；其余进检索"""
        return "end" if state.get("chitchat") else "retrieve_documents"

    def _node_retrieve_documents(self, state: RAGState) -> dict:
        """节点2：混合检索 — Qdrant 一次查询完成双路召回 + 服务端 RRF 融合，再精排

        融合分是排名分（1/(k+rank) 量级）而不是相似度，量纲上没有意义，
        所以不设阈值筛相关性；"检索到的内容相不相关"完全交给重排器判断
        （见 _rerank 里的 >= 0.3）。空库和无命中因此是同一个结果。
        """
        query = state["query"]
        writer = get_stream_writer()
        writer({"event": "progress", "data": "正在检索文档"})

        docs = self.vector_store.similarity_search(query, k=settings.TOP_K)

        # 重排序：Cross-Encoder 联合编码精排，低于阈值的一律丢弃
        docs = self._rerank(query, docs)

        # 构建上下文 和 来源
        context_parts = []
        sources = []
        seen_docs = set()    # 来源文件用集合去重
        for doc in docs:
            context_parts.append(doc.page_content)
            doc_id = doc.metadata.get("doc_id", doc.metadata.get("source", "unknown"))
            if doc_id not in seen_docs:
                seen_docs.add(doc_id)
                sources.append({
                    "index": len(sources) + 1,
                    "source": doc.metadata.get("source", "unknown"),
                    "content_preview": doc.page_content[:100] + "...",
                })

        # 即使没检索到也要发一次空的 sources：否则前端分不清"没找到"和"还没开始检索"
        writer({"event": "sources", "data": sources})

        return {
            "documents": docs,
            "context": "\n\n".join(context_parts),
            "sources": sources,
        }

    def _route_after_retrieve(self, state: RAGState) -> Literal["generate_answer", "no_answer"]:
        """精排后一条都没剩下 → 弃答，不进生成节点"""
        return "generate_answer" if state.get("documents") else "no_answer"

    async def _node_generate_answer(self, state: RAGState) -> dict:
        """节点3：基于检索到的文档生成回答，返回 messages 由 add_messages 自动追加
        （async — 流式生成是本管线最长的 LLM 等待，异步化后不再占用线程池位）

        走到这里一定有文档：检索为空由 retrieve 后的条件边分流到 no_answer 节点。
        """
        # messages[:-1] 排除当前问题（由 {query} 单独传入），避免重复
        prev = state["messages"][:-1]
        done = state.get("summarized_count", 0)    # 已压缩多少条
        fresh = prev[done:]                        # 所有未压缩消息（≤ 8 条）
        prompt_val = self.rag_prompt.invoke({
            "query": state["query"],
            "context": state["context"],
            "chat_history": fresh,
            "summary": state.get("summary", ""),
        })

        # 逐 token 流式生成，writer 将每个 token 推送到 chat_stream
        writer = get_stream_writer()
        # 把检索到的篇数直接写进文案：前端不用自己拼，也避免两处状态互相覆盖
        # 文案不带省略号 —— 动态省略号由前端画（引擎写了会变成双份）
        writer({"event": "progress", "data": f"正在参考 {len(state.get('sources', []))} 篇文档生成回答"})
        full_answer = ""
        try:
            async for chunk in self.llm.astream(prompt_val):
                token = chunk.content
                if not token:
                    continue
                full_answer += token
                writer(token)
        except Exception as e:
            print(f"⚠️ generate_answer 异常: {type(e).__name__}: {e}")
            full_answer = "抱歉，回答生成失败（可能是内容审核拦截），请稍后重试或换个问法。"
            writer(full_answer)
        if not full_answer:
            # 流正常结束但无内容（空流，模型偶发行为）：补兜底，避免空消息入库
            print("⚠️ generate_answer 空流：LLM 未产生任何内容")
            full_answer = "抱歉，回答生成失败（模型未返回内容），请稍后重试或换个问法。"
            writer(full_answer)

        # add_messages 自动追加到 messages，response_metadata 存入来源供 get_history 使用
        return {
            "answer": full_answer,
            "messages": [AIMessage(
                content=full_answer,
                response_metadata={"sources": state.get("sources", [])},
            )],
        }

    async def _node_no_answer(self, state: RAGState) -> dict:
        """节点3b：检索为空时的弃答

        单独一个节点、单独一段提示词——提示词里【没有"回答用户的问题"这条指令】，
        模型不处在"可以回答"的位置上。靠提示词禁止它用自身知识作答只是第二道保险，
        第一道是它压根没被要求回答。这一点比只改提示词的结构性更强。

        与 generate_answer 一样逐 token 流式输出，前端体验一致。
        """
        prev = state["messages"][:-1]
        done = state.get("summarized_count", 0)
        prompt_val = self.no_answer_prompt.invoke({
            "query": state["query"],
            "chat_history": prev[done:],
            "summary": state.get("summary", ""),
        })

        writer = get_stream_writer()
        writer({"event": "progress", "data": "未找到相关文档"})
        full_answer = ""
        try:
            async for chunk in self.llm.astream(prompt_val):
                token = chunk.content
                if not token:
                    continue
                full_answer += token
                writer(token)
        except Exception as e:
            print(f"⚠️ 弃答节点异常: {type(e).__name__}: {e}")
        if not full_answer:
            # 兜底文案本身也不含任何知识性内容，不可能编造
            full_answer = "知识库中没有找到相关内容，建议换个问法或补充相关文档。"
            writer(full_answer)

        return {
            "answer": full_answer,
            "messages": [AIMessage(content=full_answer)],
        }

    async def _node_evaluate_confidence(self, state: RAGState) -> dict:
        """节点4：置信度评估——无文档时跳过（async — LLM 调用不占线程池位）"""
        context = state.get("context", "")
        if not context:
            # 没有文档时直接跳过评估，不发进度（瞬时返回，提示了反而闪一下）
            return {"confidence": 0.0}

        # 回答出完到 done 之间有一段评估耗时：不提示的话看起来像卡住了
        get_stream_writer()({"event": "progress", "data": "正在评估回答置信度"})

        chain = self.eval_prompt | self.llm | StrOutputParser()
        try:
            score = float((await chain.ainvoke({
                "context": context,
                "query": state["query"],
                "answer": state["answer"],
            })).strip())
            score = min(max(score, 0.0), 1.0)
        except (ValueError, AttributeError):
            score = 0.5
        return {"confidence": score}

    # ==================== 公开接口 ====================

    async def get_history(self, thread_id: str) -> list[dict[str, Any]]:
        """从 checkpoints 中读取对话消息，转为前端可用的 dict，附带来源信息"""
        config = {"configurable": {"thread_id": thread_id}}
        state = await self.graph.aget_state(config)
        if state and state.values:
            messages = state.values.get("messages", [])
            result = []
            for m in messages:
                entry = {
                    "role": "user" if isinstance(m, HumanMessage) else "assistant",
                    "content": m.content,
                }
                if isinstance(m, AIMessage):
                    entry["sources"] = m.response_metadata.get("sources", [])
                result.append(entry)
            return result
        return []

    async def chat(self, query: str, conversation_id: str | None = None,
                   temperature: float = 0.1, top_k: int = 5) -> ChatResponse:
        """
        非流式 RAG 查询

        完整执行 5 节点管线，返回最终结果。
        AsyncPostgresSaver 自动保存对话状态，下次用同 conversation_id 即可多轮对话。
        """
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        config = {"configurable": {"thread_id": conversation_id}}
        # add_messages 自动将 HumanMessage 追加到 messages 列表
        result = await self.graph.ainvoke(
            {"query": query, "messages": [HumanMessage(content=query)]}, config
        )

        sources = [SourceInfo(**s) for s in result.get("sources", [])]
        return ChatResponse(
            conversation_id=conversation_id,
            answer=result["answer"],
            sources=sources,
            confidence=result.get("confidence", 0.0),
            rewritten_query=(
                result["query"] if result["query"] != query else None
            ),
            rag_used=len(sources) > 0,
        )

    async def chat_stream(self, query: str, conversation_id: str | None = None,
                          temperature: float = 0.1, top_k: int = 5) -> AsyncGenerator[str, None]:
        """
        流式 RAG 查询（token 级），返回 SSE 事件流

        事件类型：
          event: sources     → 检索到的文档来源
          data: {"token":"x"} → 逐 token 输出（LLM 实时生成）
          event: done        → 对话完成（含 confidence + conversation_id）
        """
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        config = {"configurable": {"thread_id": conversation_id}}
        input_data = {"query": query, "messages": [HumanMessage(content=query)]}

        sources = []
        async for chunk in self.graph.astream(input_data, config, stream_mode="custom"):
            if isinstance(chunk, dict) and chunk.get("event") == "sources":
                sources = chunk["data"]
                yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"
            elif isinstance(chunk, dict) and chunk.get("event") == "progress":
                yield f"event: progress\ndata: {json.dumps({'status': chunk['data']}, ensure_ascii=False)}\n\n"
            elif isinstance(chunk, str):
                yield f"data: {json.dumps({'token': chunk})}\n\n"

        # 流结束后取最终状态
        state = await self.graph.aget_state(config)
        confidence = 0.0
        if state and state.values:
            confidence = state.values.get("confidence", 0.0)

        yield f"event: done\ndata: {json.dumps({'conversation_id': conversation_id, 'confidence': confidence, 'rag_used': len(sources) > 0}, ensure_ascii=False)}\n\n"
