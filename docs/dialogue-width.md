# 대사 한 줄 168px

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
