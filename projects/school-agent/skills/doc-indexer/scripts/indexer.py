"""
doc-indexer: ODT/PDF 공문서 파싱 + ChromaDB 벡터 인덱싱
사용법:
  python indexer.py --once   # 폴더 내 기존 파일 전체 인덱싱
  python indexer.py          # 실시간 폴더 감시 모드
"""

import os
import sys
import time
import hashlib
import argparse
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from odf.opendocument import load as load_odt
from odf.text import P as OdfP
from odf.table import Table, TableRow, TableCell
from odf import teletype
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

load_dotenv()

# ── 설정 ────────────────────────────────────────────────────────────
WATCH_FOLDER = Path(os.getenv("WATCH_FOLDER", "./docs-inbox"))
CHROMA_PATH  = os.getenv("CHROMA_PATH", "./chroma-db")
EMBED_MODEL  = os.getenv("EMBED_MODEL", "jhgan/ko-sroberta-multitask")
CHUNK_SIZE   = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP= int(os.getenv("CHUNK_OVERLAP", "50"))
COLLECTION   = "school_docs"

# ── ChromaDB 초기화 ─────────────────────────────────────────────────
print(f"[init] 임베딩 모델 로딩: {EMBED_MODEL}")
embed_fn = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
client   = chromadb.PersistentClient(path=CHROMA_PATH)
col      = client.get_or_create_collection(COLLECTION, embedding_function=embed_fn)
print(f"[init] ChromaDB 준비 완료 (컬렉션: {COLLECTION})")


# ── ODT 파싱 ────────────────────────────────────────────────────────
def parse_odt(path: Path) -> str:
    """ODT 파일에서 텍스트(단락 + 표)를 추출합니다."""
    try:
        doc   = load_odt(str(path))
        parts = []

        # 단락 텍스트
        for elem in doc.text.childNodes:
            text = teletype.extractText(elem).strip()
            if text:
                parts.append(text)

        # 표 데이터
        for table in doc.spreadsheet.childNodes if hasattr(doc, 'spreadsheet') else []:
            pass  # ODT 표는 doc.text 안에 있음

        # 표를 명시적으로 탐색
        def extract_tables(node):
            if node.qname and node.qname[1] == 'table':
                rows = []
                for row in node.childNodes:
                    if hasattr(row, 'qname') and row.qname[1] == 'table-row':
                        cells = []
                        for cell in row.childNodes:
                            if hasattr(cell, 'qname') and cell.qname[1] == 'table-cell':
                                cells.append(teletype.extractText(cell).strip())
                        if any(cells):
                            rows.append(" | ".join(cells))
                if rows:
                    parts.append("\n".join(rows))
            for child in getattr(node, 'childNodes', []):
                extract_tables(child)

        extract_tables(doc.text)
        return "\n".join(parts)

    except Exception as e:
        print(f"  [경고] ODT 파싱 실패: {path.name} — {e}")
        return ""


def parse_pdf(path: Path) -> str:
    """PDF 파일에서 텍스트를 추출합니다."""
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(path))
    except ImportError:
        print("  [경고] pdfminer.six 미설치. PDF 지원 불가.")
        return ""
    except Exception as e:
        print(f"  [경고] PDF 파싱 실패: {path.name} — {e}")
        return ""


# ── 텍스트 청킹 ─────────────────────────────────────────────────────
def chunk_text(text: str) -> list[str]:
    """텍스트를 CHUNK_SIZE 단위로 나누고 CHUNK_OVERLAP만큼 겹칩니다."""
    chunks = []
    start  = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c.strip() for c in chunks if c.strip()]


# ── 파일 ID 생성 ─────────────────────────────────────────────────────
def file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# ── 인덱싱 ───────────────────────────────────────────────────────────
def index_file(path: Path) -> bool:
    """파일을 파싱하여 ChromaDB에 저장. 이미 인덱싱된 파일은 건너뜁니다."""
    suffix = path.suffix.lower()
    if suffix not in (".odt", ".pdf"):
        return False

    fhash = file_hash(path)

    # 중복 체크: 같은 해시 이미 저장된 경우 스킵
    existing = col.get(where={"file_hash": fhash}, limit=1)
    if existing["ids"]:
        print(f"  [스킵] 이미 인덱싱됨: {path.name}")
        return False

    print(f"  [파싱] {path.name} ...")
    if suffix == ".odt":
        text = parse_odt(path)
    else:
        text = parse_pdf(path)

    if not text.strip():
        print(f"  [경고] 텍스트 비어있음: {path.name}")
        return False

    chunks = chunk_text(text)
    now    = datetime.now().isoformat()

    ids       = [f"{fhash}_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "file_name": path.name,
            "file_path": str(path.resolve()),
            "file_hash": fhash,
            "file_type": suffix,
            "chunk_idx": i,
            "indexed_at": now,
        }
        for i in range(len(chunks))
    ]

    col.add(ids=ids, documents=chunks, metadatas=metadatas)
    print(f"  ✅ {path.name} — {len(chunks)}개 청크 저장 완료")
    return True


def index_folder(folder: Path):
    """폴더 안의 모든 ODT/PDF 파일을 인덱싱합니다."""
    files = list(folder.rglob("*.odt")) + list(folder.rglob("*.pdf"))
    if not files:
        print(f"[!] 처리할 파일 없음: {folder}")
        return
    print(f"[scan] {len(files)}개 파일 발견 → 인덱싱 시작")
    for f in files:
        index_file(f)
    total = col.count()
    print(f"\n[완료] 전체 저장된 청크 수: {total}")


# ── 실시간 감시 ──────────────────────────────────────────────────────
class DocHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            path = Path(event.src_path)
            if path.suffix.lower() in (".odt", ".pdf"):
                print(f"\n[감지] 새 파일: {path.name}")
                time.sleep(0.5)  # 파일 쓰기 완료 대기
                index_file(path)

    def on_moved(self, event):
        """파일이 복사·이동될 때도 처리"""
        if not event.is_directory:
            path = Path(event.dest_path)
            if path.suffix.lower() in (".odt", ".pdf"):
                print(f"\n[이동 감지] {path.name}")
                time.sleep(0.5)
                index_file(path)


# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="공문서 인덱서")
    parser.add_argument("--once", action="store_true", help="기존 파일만 1회 인덱싱 후 종료")
    args = parser.parse_args()

    WATCH_FOLDER.mkdir(parents=True, exist_ok=True)
    print(f"[설정] 감시 폴더: {WATCH_FOLDER.resolve()}")
    print(f"[설정] ChromaDB:  {CHROMA_PATH}")

    # 기존 파일 인덱싱
    index_folder(WATCH_FOLDER)

    if args.once:
        print("[완료] --once 모드 종료")
        return

    # 실시간 감시
    observer = Observer()
    observer.schedule(DocHandler(), str(WATCH_FOLDER), recursive=True)
    observer.start()
    print(f"\n[감시 중] {WATCH_FOLDER.resolve()} — 종료하려면 Ctrl+C")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    print("[종료] 인덱서 종료됨")


if __name__ == "__main__":
    main()
