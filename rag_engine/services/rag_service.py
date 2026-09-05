"""
RAG 服务 — 项目核心

用 LangGraph 编排完整的 RAG 管线：
  用户问题 → 查询改写 → 混合检索 → 生成回答 → 置信度评估

特性：
- 混合检索：向量检索（语义）+ BM25（关键词），互补提升召回率
- 多轮对话：自动指代消解 + add_messages 自动追加 + AsyncSqliteSaver 持久化
- 流式输出：SSE 格式，逐阶段返回进度（来源 → 回答 → 置信度 → 完成）
"""
import json
import uuid
from typing import TypedDict, Annotated, Any, AsyncGenerator
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.config import get_stream_writer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document
from langchain_classic.retrievers import EnsembleRetriever
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


# ==================== 提示词模板 ====================

RAG_SYSTEM_PROMPT = """你是一个专业的问答助手。请基于提供的上下文信息回答用户的问题。

重要规则：
1. 只使用提供的上下文信息来回答问题
2. 如果上下文中没有相关信息，请告诉用户"知识库中暂无相关内容，建议上传相关文档或换个问题试试"
3. 回答要准确、简洁、有条理
4. 如果有历史摘要，其记录了更早的对话信息，但近期对话的优先级更高（用户可能在纠正之前的信息）
5. 上下文每段以 [来源] 开头，表示该段内容出自哪个文件
上下文信息：
{context}
{summary}"""

# 无文档时的普通聊天提示词
CHAT_SYSTEM_PROMPT = """你是一个专业的AI助手。请友好、准确地回答用户的问题。
如果问题超出你的知识范围，诚实说明。回答要简洁有条理。

重要规则：
如果有历史摘要，其记录了更早的对话信息，但近期对话的优先级更高（用户可能在纠正之前的信息）
{summary}"""

REWRITE_SYSTEM_PROMPT = """你是一个查询优化专家。请将用户问题改写为更适合知识库检索的查询。

规则：
1. 口语化或模糊措辞 → 替换为精确、正式的表达
2. 考虑同义词和近义词的多样性，如果用户用词不够精准，尝试用更通用的术语替换
3. 多轮对话时，结合历史进行指代消解
4. 改写后必须保持自然语言句式，禁止堆砌关键词
5. 改写只做指代消解和用词优化：不做内容加工。输入不是明确的检索问题时（闲聊、不完整表达、无意图的词汇），原样返回
只返回改写后的查询，不要添加任何解释。"""

SUMMARIZE_SYSTEM_PROMPT = """你是一个对话摘要专家。请将以下对话历史压缩为一段简洁的摘要，保留关键信息（用户姓名、偏好、重要结论等）。只返回摘要文本，不要添加解释。"""

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
      向量检索（语义匹配） — 同义词、近义表达也能命中，但可能漏掉精确关键词
      BM25（关键词匹配）  — 精确匹配术语、人名、编号等，但不懂同义词
      混合检索取两者交集，互补短板
    """

    def __init__(self, vector_store, llm, checkpointer: AsyncSqliteSaver, embeddings, bm25_cache):
        self.vector_store = vector_store    # ChromaDB 实例
        self.llm = llm                      # Qwen LLM
        self.checkpointer = checkpointer    # AsyncSqliteSaver（自动持久化对话状态）
        self.embeddings = embeddings        # AliyunEmbeddings
        self.bm25_cache = bm25_cache        # BM25 倒排索引共享缓存（文档变更由 document_service 失效）

        # 组装提示词模板

        # RAG 问答：文档上下文 + 历史对话
        self.rag_prompt = ChatPromptTemplate.from_messages([     
            ("system", RAG_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{query}"),
        ])
        # 多轮改写：指代消解
        self.rewrite_prompt = ChatPromptTemplate.from_messages([ 
            ("system", REWRITE_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "原始问题：{query}\n\n请改写为独立完整的查询："),
        ])
        # 普通聊天：无相关上下文时
        self.chat_prompt = ChatPromptTemplate.from_messages([    
            ("system", CHAT_SYSTEM_PROMPT),
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

        # 编译 LangGraph 管线（带 AsyncSqliteSaver 自动持久化）
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
        """构建 5 节点串行 RAG 管线，add_messages 自动管理对话历史"""
        builder = StateGraph(RAGState)

        builder.add_node("summarize", self._node_summarize)
        builder.add_node("rewrite_query", self._node_rewrite_query)
        builder.add_node("retrieve_documents", self._node_retrieve_documents)
        builder.add_node("generate_answer", self._node_generate_answer)
        builder.add_node("evaluate_confidence", self._node_evaluate_confidence)

        builder.add_edge(START, "summarize")
        builder.add_edge("summarize", "rewrite_query")
        builder.add_edge("rewrite_query", "retrieve_documents")
        builder.add_edge("retrieve_documents", "generate_answer")
        builder.add_edge("generate_answer", "evaluate_confidence")
        builder.add_edge("evaluate_confidence", END)

        return builder.compile(checkpointer=self.checkpointer)

    # ==================== 5 个节点函数 ====================

    def _node_summarize(self, state: RAGState) -> dict:
        """节点0：历史消息过多时自动压缩旧消息为摘要"""
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
            result = chain.invoke({"messages": prompt_text})
        except Exception as e:
            # 摘要失败降级：跳过本轮压缩，后续轮次再触发，管线不崩
            print(f"⚠️ 摘要节点异常: {type(e).__name__}: {e}")
            return {}
        done += compress
        return {"summary": f"\n历史摘要：{result}\n", "summarized_count": done}

    def _node_rewrite_query(self, state: RAGState) -> dict:
        """
        节点1：多轮对话时的查询改写（指代消解）
        例如："它有什么特点？" → "LangGraph 有什么特点？"
        messages[:-1] 排除当前问题（由 add_messages 自动追加）
        """
        # messages 最后一条是当前用户消息，排除后只剩历史轮次
        prev = state["messages"][:-1]

        writer = get_stream_writer()
        writer({"event": "progress", "data": "正在分析问题..."})
        done = state.get("summarized_count", 0)    # 已压缩多少条
        fresh = prev[done:]                        # 所有未压缩消息（≤ 8 条，summarize 节点保证）
        try:
            chain = self.rewrite_prompt | self.llm | StrOutputParser()
            rewritten = chain.invoke({
                "query": state["query"],
                "chat_history": fresh,
            })
        except Exception as e:
            # 改写失败降级：用用户原问题直接检索（改写是优化项，原问题也能查）
            print(f"⚠️ 查询改写节点异常: {type(e).__name__}: {e}")
            return {}
        # 防御：flash 模型偶发空返回（含 emoji/来源标注的历史干扰），qwen3-max/35b 无此问题
        if not rewritten.strip():
            return {}
        return {"query": rewritten}

    def _node_retrieve_documents(self, state: RAGState) -> dict:
        """节点2：混合检索 — 向量检索 + BM25 关键词检索

        步骤：
        1. 从 ChromaDB 加载所有文档块（BM25 需要全量文档建立倒排索引）
        2. 向量检索器：语义匹配，找"意思相近"的
        3. BM25 检索器：关键词匹配，找"词一样"的
        4. EnsembleRetriever 用 RRF 算法融合两个排序结果
        """
        query = state["query"]

        # 从共享缓存取 BM25 索引（首次/文档变更后重建一次，避免每次查询全量拉库）
        all_docs, bm25_retriever = self.bm25_cache.ensure()

        if not all_docs:
            return {"context": "", "sources": [], "documents": []}

        # 前置过滤：用向量相似度检查是否有相关文档，同时建 score_map 供后置过滤
        scored = self.vector_store.similarity_search_with_score(query, k=20)
        score_map = {doc.id: s for doc, s in scored if s < 1.5}
        if not score_map:
            return {"context": "", "sources": [], "documents": []}

        writer = get_stream_writer()
        writer({"event": "progress", "data": "正在检索文档..."})

        # 向量检索器（语义匹配）
        vector_retriever = self.vector_store.as_retriever(
            search_kwargs={"k": settings.TOP_K}
        )
        # 混合检索器：RRF 融合，偏向向量（语义 > 关键词）
        ensemble = EnsembleRetriever(
            retrievers=[vector_retriever, bm25_retriever],
            weights=[0.6, 0.4],
            k=settings.TOP_K,
        )
        docs = ensemble.invoke(query)

        # 后置过滤：用 score_map 剔除 BM25 混入的无分文档
        docs = [d for d in docs if d.id in score_map]

        # 重排序：Cross-Encoder 对过滤后的文档精排
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

        # 推送来源到流式输出
        writer = get_stream_writer()
        writer({"event": "sources", "data": sources})

        return {
            "documents": docs,
            "context": "\n\n".join(context_parts),
            "sources": sources,
        }

    def _node_generate_answer(self, state: RAGState) -> dict:
        """节点3：有文档用 RAG 回答，没文档用普通聊天，返回 messages 由 add_messages 自动追加"""
        # messages[:-1] 排除当前问题（由 {query} 单独传入），避免重复
        prev = state["messages"][:-1]
        done = state.get("summarized_count", 0)    # 已压缩多少条
        fresh = prev[done:]                        # 所有未压缩消息（≤ 8 条）
        summary = state.get("summary", "")
        has_context = bool(state.get("context"))
        if has_context:
            prompt_val = self.rag_prompt.invoke({
                "query": state["query"],
                "context": state["context"],
                "chat_history": fresh,
                "summary": summary,
            })
        else:    # 普通聊天
            prompt_val = self.chat_prompt.invoke({
                "query": state["query"],
                "chat_history": fresh,
                "summary": summary,
            })

        # 逐 token 流式生成，writer 将每个 token 推送到 chat_stream
        writer = get_stream_writer()
        writer({"event": "progress", "data": "正在生成回答..."})
        full_answer = ""
        try:
            for chunk in self.llm.stream(prompt_val):
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

    def _node_evaluate_confidence(self, state: RAGState) -> dict:
        """节点4：置信度评估——无文档时跳过"""
        context = state.get("context", "")
        if not context:
            return {"confidence": 0.0}

        chain = self.eval_prompt | self.llm | StrOutputParser()
        try:
            score = float(chain.invoke({
                "context": context,
                "query": state["query"],
                "answer": state["answer"],
            }).strip())
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

    async def delete_history(self, thread_id: str):
        """删除对话的 checkpoint 数据（配合 ConversationService 的元数据删除）"""
        await self.checkpointer.conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,)
        )
        await self.checkpointer.conn.execute(
            "DELETE FROM writes WHERE thread_id = ?", (thread_id,)
        )
        await self.checkpointer.conn.commit()

    async def chat(self, query: str, conversation_id: str | None = None,
                   temperature: float = 0.1, top_k: int = 5) -> ChatResponse:
        """
        非流式 RAG 查询

        完整执行 5 节点管线，返回最终结果。
        AsyncSqliteSaver 自动保存对话状态，下次用同 conversation_id 即可多轮对话。
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
