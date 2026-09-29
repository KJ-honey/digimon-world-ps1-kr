# 대사 한 줄 252px

2026-09-28 사용자 정정: **21칸 × 12px = 252px**. 이전 14칸/168px 조건은
폐기했다. 아래의 168px 기록은 복구 이력이며 현재 빌드 기준이 아니다.

후속 동적 명칭 폭 보정: `07` 디지몬명과 `09` 아이템명은 NUL 포함 20-byte
인라인 이름 필드에서 오므로 최대 9글자/108px이다. `12` 대회명은 현재
한국어판 포인터 표 46개를 전수 읽어 최대 5글자/60px을 예약한다. `08/11`은
여전히 10글자/120px을 예약한다. 아래의 기존 폭 보고서는 보정 이전 결과다.

현재 번역은 `work/translation/reviews.json`이며 Git에서 추적한다. 168px 조정 직전의
전체 백업으로 4,617개 문구를 복구한 뒤, 252px를 초과하는 219개만 다시 조정했다.
4,398개는 복구본과 완전히 같고, 218개는 줄바꿈·공백 배치만 달라졌다. 신문 1개
(`dg-text-09782e`)는 사용자 승인으로 8줄을 유지하도록 원문과 대조해 축약했다.
처음에는 신문 2개가 추가 행을 필요로 했으나 다른 1개는 제목의 들여쓰기와 본문 배치로
해결해 문구를 보존했다. 가격 선택지 1개는 줄 수·가격·문구를 유지하고 행 끝의 전각
공백 1개씩만 제거했다. 모든 항목의 줄바꿈 이외 보호 토큰열은 복구본과 일치한다.

전체 **4,617개 / 8,696줄 / 최대 252px / 초과 0개**.
기존 6px 공백, 12px 글리프, 이름 6글자, 동적 테이블 명칭 10글자 예산은 유지한다.
원문 경계·제어·인코딩·64-byte 행 버퍼 검사도 유지한다. 문구 승인 상태나 배포 적격성을
새로 부여하지 않았다.

자동 테스트 74개와 전체 8,696줄의 MIPS 좌표 검사를 통과했다. 최종 ISO 내부의
변경 대사 4,421개, 스크립트 연결과 MAPHEAD 사본이 최신 입력과 일치한다.
bank 소비자 CPU 검사 및 21글자/혼합 공백 252px 행의 픽셀 검증도 통과했다.
이름 입력과 폰트가 들어 있는 EXE·SHOP 파일은 이전 이미지와 전체 바이트가 같다.
CPU 검사에서 CD·BIOS·GPU는 대역으로 처리했다. 새 이미지의 실제 게임 실행은 미검증이다.

- Git 복구점 `50d70e3`: 168px 버전과 그 이전의 항목별 수정 이력.
- Git 복구점 `0139d0e`: 168px 조정 전 4,617개 문구 전체 복구(252px 초과 219개 포함).
- 현재 적용 입력: `work/line-width-252/selected-final/edits.json`.
- 최종 통합 이미지: `work/build/name-entry-252/dg-expanded.cue`.
- 복구·전후 문구·계획·검사 기록: `work/line-width-252/`.

```sh
python3 tools/translation_layout.py --output work/line-width-252/audit-new.json
python3 tools/translation_playtest.py --output work/line-width-252/selected-new
python3 tools/dg_expand.py --edits work/line-width-252/selected-new/edits.json --expand-font --name-entry --output work/build/name-entry-252-new
python3 tools/dg_layout_verify.py --output work/line-width-252/cpu-new.json
python3 -m unittest discover -s tools -p 'test_*.py'
```

빌드·내보내기 중 문구나 줄바꿈을 자동 수정하지 않는다. 명시적으로 저장한 수정 계획만 적용한다.

## 이전 168px 작업 기록 (폐기된 폭 기준)


2026-09-28 사용자 지정: 한 줄 14칸(168px). `work/translation/reviews.json`의
현재 DG 번역 4,617개를 전수 검사해 2,253개 항목의 초과 3,090줄을 수정했다.
최종 10,606줄 모두 168px 이하이며, 미추출 모듈/미확인 DG 후보는 이 분모에 포함하지 않는다.

| 요소 | 검사 폭 |
| --- | --- |
| 반각 공백 U+0020 / `0F00` | 6px |
| 전각 공백, 한글, ASCII, 문장부호, 버튼/단위 raw glyph | 12px |
| 색상 `01xx` | 0px |
| 주인공·디지몬 이름 | 최대 6칸 / 72px |
| 종족·아이템·기술·노래·대회명 | 사용자 지정 최대 10칸 / 120px |
| 숫자 삽입 | 기존 소비자의 고정 출력 자릿수 × 12px |

알 수 없는 제어 명령을 폭 0으로 가정하지 않고 거부한다. byte 길이와 표시 폭은 별개다.
64-byte 행 버퍼, 보호 코드·인자, 없는 글자, bank 크기 검사도 계속 적용한다.

일반 대사는 문구를 유지한 줄바꿈을 우선했다. 최대 4줄에 맞지 않는 대사, 선택지,
가격표, 신문/안내문은 개별 대조해 축약했다. 선택지 수와 순서는 보존했고, 장문 안내는
기존 행 수 안에 배치했다. 대회 안내는 빈 행을 활용했다. 가격·수량·이름·색상·버튼은
보존했다. 모든 전후 문구와 원문, 수정 사유는 `work/line-width-168/applied-001/changes.json`,
추가 단어 배치는 `word-break-followup.json`에 있다. 문구 승인을 새로 부여하지 않았다.

`tools/translation_layout.py`는 명시적 수정 계획을 저장하거나 현재 번역을 검사한다.
빌드 도중 자동 축약이나 자동 줄바꿈을 하지 않는다. ID·원본 payload 해시·새 보호열
해시가 맞는 경우에만 새 줄바꿈을 허용하며, 일반 제어 변경 검사는 완화하지 않았다.
`tools/translation_playtest.py`와 `dg_expand.py`가 인코딩 후에도 168px을 검사한다.

```sh
python3 tools/translation_layout.py --output work/line-width-168/audit-new.json
python3 tools/translation_playtest.py --output work/line-width-168/selected-new
python3 tools/dg_layout_verify.py --output work/line-width-168/cpu-new.json
python3 -m unittest discover -s tools -p 'test_*.py'
```

최종 입력: `work/line-width-168/selected-final/edits.json`. 전체 4,617개 선택,
기존 디스크 대비 변경 4,424개/동일 193개, 보류 0개다. 자동 테스트 74개와
원래 MIPS 소비자·행 렌더러의 10,606줄 폭 대조를 통과했다. 후자는 동적 값을 최대 길이
fixture로 치환하고 GPU를 stub 처리한 CPU 검사이며, 실제 게임 화면 증거가 아니다.

이번에는 ISO를 재생성하지 않았다. 기존 `control-restorations-001` 이미지는 이전 번역이다.
새 번역의 실제 게임 표시·페이지 전환·선택지 조작 검증은 새 이미지에서 별도로 해야 한다.
