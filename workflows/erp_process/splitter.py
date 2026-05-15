"""制造文档专用切分器 — 按语义边界切分，不按Token数"""

import re
from langchain.schema import Document
from typing import Generator


class ManufacturingSplitter:
    """按语义边界切分制造类文档"""

    def split_documents(self, docs: list[Document]) -> list[Document]:
        chunks = []
        for doc in docs:
            source = doc.metadata.get("source", "")
            content = doc.page_content
            meta = dict(doc.metadata)
            if "equipment" in source.lower():
                chunks.extend(self._by_equipment(content, meta))
            elif "feature" in source.lower():
                chunks.extend(self._by_feature(content, meta))
            elif "process_template" in source.lower():
                chunks.extend(self._by_process_step(content, meta))
            elif "engineer_rules" in source.lower():
                chunks.append(Document(page_content=content, metadata=meta))
            else:
                chunks.append(Document(page_content=content, metadata=meta))
        return chunks

    def _by_equipment(self, content: str, meta: dict) -> list[Document]:
        blocks = re.split(r"(?=###\s+\w+)", content)
        return [
            Document(page_content=b.strip(), metadata=dict(meta))
            for b in blocks if b.strip()
        ]

    def _by_process_step(self, content: str, meta: dict) -> list[Document]:
        steps = re.split(r"(?=序号\s*\d+\s*│)", content)
        return [
            Document(page_content=s.strip(), metadata=dict(meta))
            for s in steps if s.strip()
        ]

    def _by_feature(self, content: str, meta: dict) -> list[Document]:
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        valid = [l for l in lines if l.startswith("|")]
        if not valid:
            return [Document(page_content=content, metadata=meta)]
        return [
            Document(page_content=l, metadata=dict(meta)) for l in valid
        ]
