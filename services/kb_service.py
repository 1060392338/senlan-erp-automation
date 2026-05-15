"""
KBService — 知识库服务

混合检索：BM25（精确名词）+ FAISS Embedding（语义查询）
RRF 融合排序，支持动态权重切换。

使用:
    kb = KBService(data_dir="data/documents/")
    docs = kb.retrieve("K490 线速度")
    answer = kb.ask("方件K490有精孔，用什么工艺？")
"""

import logging
from pathlib import Path
from typing import Optional

from langchain.schema import Document
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from langchain.vectorstores import FAISS
from langchain.embeddings import HuggingFaceEmbeddings
from workflows.erp_process.splitter import ManufacturingSplitter

log = logging.getLogger("kb_service")


class KBService:
    def __init__(
        self,
        data_dir: str = "data/documents/",
        index_dir: str = "data/vector_index/",
        embedding_model: str = "BAAI/bge-base-zh-v1.5",
    ):
        self._data_dir = Path(data_dir)
        self._index_dir = Path(index_dir)
        self._splitter = ManufacturingSplitter()

        # Embedding
        self._embedder = HuggingFaceEmbeddings(model_name=embedding_model)
        self._bm25: Optional[BM25Retriever] = None
        self._vector: Optional[FAISS] = None
        self._ensemble: Optional[EnsembleRetriever] = None

        self._build_or_load()

    def _build_or_load(self):
        """加载或构建索引"""
        if self._index_dir.exists() and list(self._index_dir.iterdir()):
            self._load()
        else:
            self._build()

    def _load(self):
        """从磁盘加载并重建双检索器"""
        self._vector = FAISS.load_local(str(self._index_dir), self._embedder)
        docs = self._load_documents()
        chunks = self._splitter.split_documents(docs)
        self._bm25 = BM25Retriever.from_documents(chunks, k=5)
        self._rebuild_ensemble()

    def _build(self):
        """从 data/documents/ 构建索引"""
        docs = self._load_documents()
        chunks = self._splitter.split_documents(docs)
        self._bm25 = BM25Retriever.from_documents(chunks, k=5)
        self._vector = FAISS.from_documents(chunks, self._embedder)
        self._vector.save_local(str(self._index_dir))
        self._rebuild_ensemble()

    def _rebuild_ensemble(self):
        """重建混合检索器（BM25+FAISS 都就绪后调用）"""
        self._ensemble = EnsembleRetriever(
            retrievers=[self._bm25, self._vector.as_retriever(search_kwargs={"k": 5})],
            weights=[0.5, 0.5],
        )

    def _load_documents(self) -> list[Document]:
        docs = []
        for path in self._data_dir.rglob("*.md"):
            content = path.read_text(encoding="utf-8")
            doc = Document(
                page_content=content,
                metadata={"source": path.stem, "file_path": str(path)},
            )
            docs.append(doc)
        return docs

    # ── 公开 API ──

    def retrieve(self, query: str, k: int = 5, filter: Optional[dict] = None) -> list[Document]:
        """混合检索"""
        if self._is_exact_query(query):
            self._ensemble.weights = (0.7, 0.3)
        else:
            self._ensemble.weights = (0.5, 0.5)
        return self._ensemble.get_relevant_documents(query)[:k]

    def add_document(self, doc: Document):
        """增量添加文档到向量库"""
        self._vector.add_documents([doc])
        self._vector.save_local(str(self._index_dir))
        # 注：BM25 需要重建，增量场景下建议定期重建

    def ask(self, query: str) -> str:
        """RAG 问答（复用 ServiceRegistry 中的 LLMClient）"""
        docs = self.retrieve(query)
        context = "\n\n".join(d.page_content for d in docs)
        try:
            from services import ServiceRegistry
            llm = ServiceRegistry.get("llm")
        except KeyError:
            return "[知识库] LLM 服务未注册，无法回答"
        return llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": f"你是森蓝精密的工艺工程师。根据以下知识库内容回答工艺相关问题：\n\n{context}",
                },
                {"role": "user", "content": query},
            ]
        )

    # ── 辅助 ──

    @staticmethod
    def _is_exact_query(query: str) -> bool:
        """检测是否含精确名词（材料牌号/设备型号/公差值）"""
        import re
        patterns = [
            r"\bK490\b", r"\bVanadis\b", r"\bSODICK\b", r"\bTAKISAWA\b",
            r"\bHARDINGE\b", r"\bOKAMOTO\b", r"\bZEISS\b",
            r"\bHRC\b", r"[∅Φ]\d+\.\d+", r"Ra\d+\.\d+",
            r"[FMK]+\d+[.-]\d+", r"M10", r"M8",
        ]
        return any(re.search(p, query) for p in patterns)
