---
name: doc-indexer
description: ODT/PDF 공문서를 파싱하여 ChromaDB에 벡터 인덱싱하고 자연어로 검색하는 스킬
---
# 문서 인덱싱 스킬 (doc-indexer)

이 스킬은 지정 폴더의 ODT/PDF 공문서를 자동으로 읽어 벡터 DB에 저장하고, 자연어 검색을 가능하게 합니다.

## 사용 조건
- 사용자가 "인덱싱해줘", "문서 추가해줘" 또는 새 공문 파일을 감시 폴더에 넣을 때 발동합니다.
- 또는 "작년 과학의 달 예산 찾아줘" 처럼 과거 공문을 검색할 때 발동합니다.

## 동작 절차

### [모드 1] 인덱싱 (새 문서 저장)
1. `WATCH_FOLDER` 환경변수로 지정된 폴더를 감시합니다.
2. ODT 또는 PDF 파일이 감지되면:
   - **ODT**: `odfpy`로 텍스트와 표 데이터 추출
   - **PDF**: `pdfminer.six`로 텍스트 추출
3. 추출된 텍스트를 500자 단위로 청킹(50자 오버랩)
4. `ko-sroberta-multitask` 모델로 한국어 임베딩 생성
5. `ChromaDB`에 저장 (메타데이터: 파일명, 경로, 날짜, 확장자)
6. "✅ [파일명] 인덱싱 완료 (N개 청크)" 출력

### [모드 2] 검색 (자연어 쿼리)
1. 사용자 쿼리를 동일 임베딩 모델로 변환
2. ChromaDB에서 유사도 기준 상위 5개 청크 조회
3. 결과를 파일명·날짜·내용 미리보기로 출력

## 실행 방법

```bash
# 설치
pip install -r requirements.txt

# 환경 설정
cp .env.example .env
# .env 편집: WATCH_FOLDER 경로 설정

# 기존 파일 전체 인덱싱 (1회)
python indexer.py --once

# 실시간 폴더 감시 모드
python indexer.py

# 자연어 검색
python search.py "과학의 달 예산 기안"
```

## 지원 파일 형식

| 형식 | 파서 | 비고 |
|------|------|------|
| `.odt` | `odfpy` | 한국 공문 주 형식 |
| `.pdf` | `pdfminer.six` | 스캔 공문 |
| `.hwpx` | 미지원 (예정) | Phase 2에서 추가 |

## 환경 변수 (.env)

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `WATCH_FOLDER` | 감시할 폴더 경로 | `./docs-inbox` |
| `CHROMA_PATH` | ChromaDB 저장 경로 | `./chroma-db` |
| `EMBED_MODEL` | 임베딩 모델명 | `jhgan/ko-sroberta-multitask` |
| `CHUNK_SIZE` | 청크 크기 (글자 수) | `500` |
| `CHUNK_OVERLAP` | 청크 오버랩 | `50` |
