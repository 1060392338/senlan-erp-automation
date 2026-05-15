"""
DrawingRegistry — 图纸登记簿

每次 Vision 分析完成后，把结构化的特征文本存入知识库向量索引。
下次相似零件进来 → 语义检索命中 → 复用上次工艺路线。

图纸图像不进向量库，只有 Vision 提取后的特征描述文本进。
"""

from langchain.schema import Document
from services.kb_service import KBService
from typing import Optional


class DrawingRegistry:
    def __init__(self, kb: KBService):
        self._kb = kb

    def register(self, prod_no: str, features: dict):
        """
        Vision 分析完成后调用。

        features 结构:
        {
            "name": "Cutting blade",
            "material": "K490 Vanadis 8",
            "hardness": "58-63",
            "shape": "square",
            "coating": "TiN",
            "qty": 2,
            "features": [
                {"type": "精孔", "spec": "∅2.0+0.01", "qty": 8},
                {"type": "螺纹", "spec": "M10x1"},
                {"type": "利角", "note": "严禁倒角"}
            ]
        }
        """
        feature_text = self._build_search_text(features)
        doc = Document(
            page_content=feature_text,
            metadata={
                "type": "drawing_feature",
                "prod_no": prod_no,
                "material": features.get("material", ""),
                "shape": features.get("shape", ""),
                "hardness": features.get("hardness", ""),
                "part_name": features.get("name", ""),
                "process_used": features.get("process_plan_id", ""),
            },
        )
        self._kb.add_document(doc)

    def find_similar(
        self, query_features: dict, top_k: int = 3
    ) -> list[Document]:
        """
        根据当前 Vision 读出的特征，检索之前做过的相似零件。
        用在 template_match 节点。
        """
        query_text = self._build_search_text(query_features)
        return self._kb.retrieve(query_text, k=top_k)

    @staticmethod
    def _build_search_text(features: dict) -> str:
        """结构化特征 → 检索文本"""
        parts = [
            f"零件名称: {features.get('name', '')}",
            f"材料: {features.get('material', '')} {features.get('hardness', '')}HRC",
            f"外形: {features.get('shape', '')}",
            f"表面处理: {features.get('coating', '')}",
            f"数量: {features.get('qty', '')}件",
        ]
        for f in features.get("features", []):
            spec = f.get("spec", "")
            tol = f.get("tolerance", "")
            rough = f.get("roughness", "")
            parts.append(
                f"特征: {f['type']} {spec} 公差{tol} 粗糙度Ra{rough}"
            )
        return "\n".join(parts)
