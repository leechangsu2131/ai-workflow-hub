"""
search.py: ChromaDB에서 자연어로 공문 검색
사용법:
  python search.py "과학의 달 예산 기안"
  python search.py "작년 현장학습 동의서" --top 3
"""

import os
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

load_dotenv()

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma-db")
EMBED_MODEL = os.getenv("EMBED_MODEL", "jhgan/ko-sroberta-multitask")
COLLECTION  = "school_docs"


def search(query: str, top_k: int = 5):
    print(f"[init] 임베딩 모델 로딩: {EMBED_MODEL}")
    embed_fn = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    client   = chromadb.PersistentClient(path=CHROMA_PATH)

    try:
        col = client.get_collection(COLLECTION, embedding_function=embed_fn)
    except Exception:
        print(f"[오류] 컬렉션 없음. 먼저 indexer.py를 실행하세요.")
        sys.exit(1)

    total = col.count()
    print(f"[검색] 총 {total}개 청크에서 검색: \"{query}\"\n")

    results = col.query(
        query_texts=[query],
        n_results=min(top_k, total),
        include=["documents", "metadatas", "distances"],
    )

    docs      = results["documents"][0]
    metas     = results["metadatas"][0]
    distances = results["distances"][0]

    if not docs:
        print("결과 없음.")
        return

    print("=" * 60)
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
        similarity = round((1 - dist) * 100, 1)
        print(f"[{i}위] 유사도: {similarity}%")
        print(f"  📄 파일: {meta.get('file_name', '?')}")
        print(f"  🗓  인덱싱: {meta.get('indexed_at', '?')[:10]}")
        print(f"  📝 내용 미리보기:")
        preview = doc[:200].replace("\n", " ")
        print(f"    {preview}...")
        print()

    print("=" * 60)
    print(f"총 {len(docs)}개 결과 반환 (상위 {top_k}개 요청)")


def main():
    parser = argparse.ArgumentParser(description="공문 자연어 검색")
    parser.add_argument("query", help="검색할 자연어 쿼리")
    parser.add_argument("--top", type=int, default=5, help="반환할 결과 수 (기본: 5)")
    args = parser.parse_args()

    search(args.query, args.top)


if __name__ == "__main__":
    main()
