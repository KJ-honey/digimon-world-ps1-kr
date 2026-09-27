# 디지몬 월드 한국어패치 업그레이드

사용자가 과거 제작한 `Digimon World (patched).iso`에서 패치 자원을 복원하고,
폰트 확장, 주인공·디지몬 이름의 조합형 한글 입력, 번역 개선을 진행하는 프로젝트입니다.

기존 패치 복원, DG 재삽입과 두 경로의 게임 검증, 문자열 정렬 수정 및 **한글 2,350자 확장**을 구현했습니다.
조합형 이름 입력과 전체 번역 개선은 남아 있으며, 전체 업그레이드 배포판은 아직 없습니다.
현재 결론·위험·다음 작업은 [docs/current.md](docs/current.md)가 관리합니다.

## 번역 수정 검수

```sh
python3 tools/translation_review.py serve --open
```

`http://127.0.0.1:8770/`에서 **일본어 원문·기존 번역·새 번역**을 나란히 검수합니다.
수정 문장 필터, 직접 편집, 승인·보류, 메모, 앞뒤 문맥, 저장·이어하기·이력을 지원합니다.
확인된 DG 4,617개 전부의 원문 대조 초안을 작성했고, 4,435개 문구를 수정했습니다. 모두 사용자 검수 전입니다.
`だか` 말투는 천진난만한 느낌으로 반영합니다. 미확인 추출 후보·다른 모듈까지 포함한 게임 전체 번역 완료는 아닙니다.
원문 바이트 길이 제한은 초안에 적용하지 않으며 ISO 반영은 하지 않습니다.
[검수 방법·번역 범위·보존 파일](docs/translation-review.md)을 참고하세요.

## 복원 결과 보기

- [검수 문자표를 적용한 원문·한국어 대조](work/text/review.html): 한국어 검색, 원본 비트맵과 Unicode 비교.
- [문자표](work/text/character-map.json), [Unicode 복원 검증](work/text/summary.json).
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
별도 백업을 권장합니다. 마지막 세 글자는 `뼈·팬·늪`으로 검수되었습니다.

검수 결과를 기존 대사 후보의 Unicode 복원에 적용합니다.

```sh
python3 tools/restore_text.py
python3 -m unittest discover -s tools -p 'test_*.py'
```

`work/text/`에 문자표, 검색 가능한 대조 HTML, 후보 JSONL, 검증 보고서를 만듭니다.
한글 913칸은 912자로 대응되며 중복된 `늪`은 `<88C0:늪>`/`<95E2:늪>`으로 구분합니다.
특수 글리프 17칸과 의미 미확정 제어 후보는 `<XXXX>`로 보존합니다. 문자표는 픽셀 데이터와
분리되어 있어 추후 폰트 타일 재생성에서도 문자 정체성을 유지할 수 있습니다.
검수·추출 입력의 해시별 사본도 `work/text/inputs/`에 보존합니다.

7,857쌍의 후보 payload가 양쪽 원본 DG 바이트와 각각 왕복 일치합니다. VM 명령 경계는
이 초기 검색 단계에서는 미검증이며, 전체 번역량이나 제품 재삽입 가능 범위를 뜻하지 않습니다.
폰트 교체·확장과 제품 빌드 연결은 후속 작업입니다.

## DG 소비자 분석과 재삽입

후속 도구는 실제 MIPS 소비자를 기준으로 텍스트 4,617개의 경계를 확인하고,
길이와 제어 위치를 유지하는 개발용 ISO를 만듭니다. script 0의 실제 로드 원본인
`MAPHEAD.SCN` 사본도 함께 갱신합니다. MAPHEAD/DG 각 한 경로의 실제 화면과 후속 진행도 확인했습니다. 전체 VM 해석·길이 확대는 남아 있습니다.

```sh
python3 tools/dg_analyze.py
python3 tools/dg_export.py --id dg-text-0042e0 --output work/dg/my-edits.json
# manifest의 text를 편집한 뒤 새 출력 경로로 빌드
python3 tools/dg_build.py --edits work/dg/my-edits.json --output work/build/my-dg --alignment-repair
```

명령·원문·한국어·제어 토큰은 `work/dg/analysis/`에 생성됩니다. 없는 글자, 제어 변경,
길이 차이, 미확인 후보는 오류로 중단합니다. 225 영역 전체 DG 왕복과 확인 텍스트 전체
무변경 재삽입 ISO 해시 일치를 확인했습니다. `work/build/dg-qa/`는 합성 시험 문장이 든
QA 전용 산출물이며 번역판이 아닙니다.
[소비자 주소·재현 절차·검증 범위](docs/dg-script.md)를 참고하세요.

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

## 한글 2,350자 확장

기존 한글 912자는 모두 KS X 1001의 2,350자에 포함됩니다. 추가 1,438자를 공급하고,
기존 문자 코드를 보존하는 확장 빌드를 구현했습니다. 2026-09-28 사용자 선택에 따라
기본 한글 폰트는 **Mona12 Text KR, 12px**입니다. 기존 한글 913칸과 추가 1,438칸을
같은 폰트로 생성하며 기호 78칸과 대체 글꼴은 원래 픽셀을 보존합니다.
반복 행 묶음을 공유하여 기존 폰트 영역에 넣으므로 ISO 크기와 상주 RAM은 늘지 않습니다.

```sh
python3 -m pip install -r requirements-font.txt
# LLVM 23.1.2 llvm-mc/llvm-objcopy 필요 (PATH 또는 LLVM_BIN)
# 사용자 제공 Mona12TextKR.ttf를 work/font-compare/에 배치 (해시는 아래 문서 참조)
python3 tools/dg_build.py --expand-font --alignment-repair --output work/build/font-my-build
python3 tools/font_cpu_verify.py work/build/font-my-build
```

`--edits`를 함께 지정하면 확장 문자표로 기존 DG 재삽입을 수행합니다.
[폰트 형식·빌드·검증 범위](docs/font-expansion.md)를 참고하세요.
굴림 원본은 기존 문자표의 정체성 검증에 계속 필요합니다. Mona12 파일은 별도 빌드 입력이며
다른 버전/파일이면 빌드를 중단합니다. 폰트 파일은 Git에 포함하지 않습니다.
조합형 이름 입력은 현재의 KS X 1001 2,350자를 대상으로 구현합니다.
사용자 결정에 따라 현대 한글 11,172자 전체 지원은 필요하지 않으며 완료 조건에 포함하지 않습니다.
