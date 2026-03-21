from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from docx import Document

from backend.core.config import PROJECT_ROOT


class StageDocumentService:
    def __init__(self) -> None:
        self.base_dir = PROJECT_ROOT / "data" / "stage_docs"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def build_stage_document(
        self,
        session_id: str,
        project_title: str,
        stage_index: int,
        stage_label: str,
        answers: list[str],
        latest_input: str | None,
        summary: str,
        feedback: str,
        guidance: str,
        draft: str,
    ) -> dict[str, Any]:
        file_name = self._file_name(
            session_id=session_id,
            stage_index=stage_index,
            stage_label=stage_label,
            suffix="generated",
        )
        file_path = self.base_dir / file_name

        document = Document()
        document.add_heading(project_title, level=1)
        document.add_paragraph(f"阶段 {stage_index}: {stage_label}")
        document.add_paragraph(f"生成时间: {self._timestamp()}")

        document.add_heading("用户回答", level=2)
        if answers:
            for index, answer in enumerate(answers, start=1):
                document.add_paragraph(f"问题 {index}: {answer or '未填写'}")
        else:
            document.add_paragraph("本阶段未收到结构化回答。")
        if latest_input and latest_input.strip():
            document.add_paragraph(f"补充说明: {latest_input.strip()}")

        document.add_heading("AI阶段总结", level=2)
        document.add_paragraph(summary)

        document.add_heading("AI反馈", level=2)
        document.add_paragraph(feedback)

        document.add_heading("下一步建议", level=2)
        document.add_paragraph(guidance)

        document.add_heading("可继续修改的阶段草稿", level=2)
        document.add_paragraph(draft)

        document.save(file_path)
        preview_text = self.extract_text(file_path)
        return {
            "stage_index": stage_index,
            "stage_label": stage_label,
            "file_name": file_name,
            "generated_path": str(file_path),
            "latest_path": str(file_path),
            "generated_text": preview_text,
            "latest_text": preview_text,
            "preview_text": preview_text,
            "is_modified": False,
            "modification_summary": None,
            "source": "generated",
            "updated_at": self._timestamp(),
        }

    def save_uploaded_revision(
        self,
        session_id: str,
        stage_index: int,
        stage_label: str,
        file_bytes: bytes,
    ) -> dict[str, Any]:
        file_name = self._file_name(
            session_id=session_id,
            stage_index=stage_index,
            stage_label=stage_label,
            suffix="revised",
        )
        file_path = self.base_dir / file_name
        file_path.write_bytes(file_bytes)

        preview_text = self.extract_text(file_path)
        return {
            "latest_path": str(file_path),
            "latest_text": preview_text,
            "preview_text": preview_text,
            "source": "uploaded",
            "updated_at": self._timestamp(),
        }

    def save_text_revision(
        self,
        session_id: str,
        stage_index: int,
        stage_label: str,
        content: str,
    ) -> dict[str, Any]:
        file_name = self._file_name(
            session_id=session_id,
            stage_index=stage_index,
            stage_label=stage_label,
            suffix="edited",
        )
        file_path = self.base_dir / file_name

        document = Document()
        for block in self._split_blocks(content):
            document.add_paragraph(block)

        document.save(file_path)
        preview_text = self.extract_text(file_path)
        return {
            "latest_path": str(file_path),
            "latest_text": preview_text,
            "preview_text": preview_text,
            "source": "edited",
            "updated_at": self._timestamp(),
        }

    def extract_text(self, file_path: str | Path) -> str:
        path = Path(file_path)
        try:
            document = Document(path)
        except (BadZipFile, KeyError, ValueError) as exc:
            raise ValueError("无法读取该 docx 文件，请重新上传标准的 Word 文档。") from exc

        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return "\n".join(paragraphs).strip()

    def download_path(self, metadata: dict[str, Any]) -> Path:
        return Path(str(metadata["latest_path"]))

    def _file_name(
        self,
        session_id: str,
        stage_index: int,
        stage_label: str,
        suffix: str,
    ) -> str:
        safe_label = "".join(char if char.isalnum() else "_" for char in stage_label).strip("_")
        safe_label = safe_label or f"stage_{stage_index}"
        return f"{session_id}_stage_{stage_index:02d}_{safe_label}_{suffix}.docx"

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _split_blocks(self, content: str) -> list[str]:
        return [block.strip() for block in content.splitlines() if block.strip()]
