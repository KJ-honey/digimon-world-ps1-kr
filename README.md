# 디지몬 월드 한국어패치 업그레이드

사용자가 과거 제작한 `Digimon World (patched).iso`에서 패치 자원을 복원하고,
폰트 확장, 주인공·디지몬 이름의 조합형 한글 입력, 번역 개선을 진행하는 프로젝트입니다.

현재는 **기존 패치 복원 및 엔진 조사 단계**입니다. 문자열 정렬 문제의 개발용 수정 ISO를 만들었으며,
폰트 확장·조합형 이름 입력·번역 개선을 완료한 업그레이드판은 아직 없습니다.
현재 결론·위험·다음 작업은 [docs/current.md](docs/current.md)가 관리합니다.

## 복원 결과 보기

- [원문과 한국어 비트맵 대조 페이지](work/recovered/review.html): 대사 후보 검색, 원본 바이트 확인, 전체 글꼴 보기.
- [파일별 변경 목록](work/survey/files.csv), [전체 조사 결과](work/survey/report.json).
- [폰트·대사 복원 결과](work/recovered/summary.json).
- [기존 패치 재현 검증](work/recovery/verification.json).
- [개발용 수정판 실행 검증](work/runtime/alignment-verification.json): 한글 메뉴와 두 이름 입력·재표시.

대조 페이지의 한국어는 ISO에서 추출한 글꼴로 그립니다. OCR 오인식이 번역에 섞이지 않도록
OCR 제안과 확정된 문자표를 구분합니다. 문장 경계는 아직 VM 전체 해석으로 검증하지 않은 후보입니다.

## 글리프 픽셀 대조와 직접 검수

제공된 [굴림 2.21 소스](https://github.com/googlefonts/gulim/tree/main/sources)의
12px 내장 비트맵을 12×11 게임 글리프와 비교합니다. 폰트 파일은 `work/reference/`에 두고
Git에 포함하지 않습니다. 새 환경에서는 먼저 다음 명령으로 받습니다.

```sh
git clone --depth 1 https://github.com/googlefonts/gulim.git work/reference/gulim
git -C work/reference/gulim checkout 012723a8d5b6a6dc920330f26d165422c3014fd6
python3 tools/match_gulim.py
python3 tools/glyph_review.py --open
```

변경 글리프 919개 중 910개가 픽셀 완전 일치합니다. 불일치 9개 중 3개는 가장
가까운 굴림 글자와 1픽셀 차이여서 기본 검수 목록에 나옵니다. 후보를 고르거나 한 글자를
직접 입력한 뒤 **문자 저장**을 누릅니다. 나머지 6개는 굴림 한글과 60픽셀 이상 달라
별도 목록에 두고 근거 없는 후보를 숨겼습니다.
기존 수동 검수 결과는 삭제하지 않고 별도 표시합니다. 수동 결과와 픽셀 대조 결과가 충돌하면
자동 일치 결과를 우선 보여줍니다. 검수 파일 `work/review/glyph-review.json`은 Git에서 제외되므로
별도 백업을 권장합니다. 아직 제품 빌드 입력에는 연결하지 않았습니다.

## 재현

프로젝트 루트에 사용자 소유의 두 ISO를 둡니다. 입력 SHA-256은 `tools/survey.py`에 고정되어 있으며
다른 리비전이나 수정된 입력은 거부합니다. ISO와 BIOS, 추출한 게임 자원은 Git에서 제외합니다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-analysis.txt
.venv/bin/python tools/survey.py
.venv/bin/python tools/recover_assets.py
```

선택적으로 로컬 Tesseract의 `kor` 언어 데이터로 미검수 글자 제안을 생성합니다.

```sh
.venv/bin/python tools/recover_assets.py --ocr
```

기존 패치판을 재현하는 로컬 복구 패치는 xdelta3가 필요합니다. 기존 출력은 덮어쓰지 않으므로
재실행할 때 `--out work/recovery-check2`처럼 새 디렉터리를 지정합니다.

```sh
.venv/bin/python tools/recover_baseline.py
```

이 명령은 일본어 ISO → 복구 xdelta → 재구성 ISO의 전체 해시 일치를 검사합니다.
복구 파일은 영상 등의 기존 변경까지 보존하는 로컬 백업이며 배포용 업그레이드 패치가 아닙니다.

## 작업 구분

| 위치 | 역할 |
| --- | --- |
| `tools/` | 조사·복원 도구와 개발용 이미지 빌드 |
| `docs/` | 현재 엔진 조사 결론, 제품 목표, 미해결 조건 |
| `work/` | 재생성 가능한 추출 자원, 분석 결과, 로컬 복구 ISO·패치 |
| `bios/` | 사용자가 제공한 BIOS; 로컬 전용 |

개발용 문자열 정렬 수정판은 다음 명령으로 재현합니다. 별도 출력 ISO만 생성합니다.

```sh
.venv/bin/python tools/build.py
```

`work/build/alignment-dev/`에 ISO·CUE·쓰기를 검증한 보고서가 생성됩니다.
기존 출력은 덮어쓰지 않으며 `--output`으로 새 경로를 지정할 수 있습니다.
정확한 입력·기존 명령 바이트·sector EDC/ECC·전체 출력 diff를 검사합니다.
