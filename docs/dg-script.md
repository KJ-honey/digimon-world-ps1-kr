# DG 명령 경계와 개발용 재삽입

기준일 2026-09-27. 입력 리비전은 `tools/survey.py`의 두 ISO SHA-256으로 고정한다.
이 문서의 DG·EXE offset은 **논리 파일 offset**, `0x800…` 주소는 **RAM address**다.
ISO LBA와 raw sector offset은 빌드 보고서에 따로 기록한다.

## 소비자에서 확인한 구조

| 기능 | RAM address | EXE 논리 offset | 확인 내용 |
| --- | --- | --- | --- |
| 초기 로드 | `800F0010` | `60010` | MAPHEAD를 `80159784`에 로드. DG 디렉터리는 `8015F784`, 일반 DG 버퍼는 `80161784` |
| 스크립트 선택 | `800F0988` | `60988` | ID 0은 MAPHEAD 버퍼 반환. 다른 ID는 DG u32 경계의 차만큼 파일 구간 로드 |
| 섹션 선택 | `800F0A4C` | `60A4C` | base+2부터 `(u16 ID, u16 relative offset)` 탐색. ID `FFFF`가 sentinel. 같은 ID면 첫 항목 선택 |
| VM 디스패치 | `800F0780` | `60780` | opcode는 **1 byte**; 다음 PC를 먼저 +1, opcode 그룹별 핸들러 호출 |
| 10..27 디스패치 | `800EC4AC` | `5C4AC` | RAM `8011B0F8`의 jump table. `1A`는 `800EC734` |
| 1A 처리 | `800EC734` | `5C734` | 다음 byte를 건너뛴 뒤 `800F4200` 호출, textbox 대기 상태로 yield |
| 텍스트 소비 | `800F4424` | `64424` | 첫 byte로 분기. `03`은 총 4 bytes, 나머지 현재 분기는 2 bytes 소비 |
| 텍스트 종료 | `800F4A94` | `64A94` | `0D xx` 처리 뒤 다음 첫 byte가 0이면 종료쌍 2 bytes 소비. 이후 opcode peek |
| 10 선택지 | `800F410C` | `6410C` | u8 개수, 그 개수의 u16 script-relative 대상, embedded `1A00` 건너뛰고 텍스트 소비 |
| 선택 결과 | `800F3C78` | `63C78` | 선택 index×2로 u16 대상 읽고 script base에 더함 |
| 19 조건 VM | `800EF4F0` | `5F4F0` | 별도 조건 byte dispatch. 인자 폭 2/4/6 bytes, 분기 대상 u16, `19 xx`에서 yield |
| native 텍스트 | `800FA3F8` | `6A3F8` | script 0의 섹션 + index×4 +2에서 u16 offset을 읽어 base+offset+2를 반환 |
| 현재 script 테이블 | `80105524` / `80105588` | `75524` / `75588` | 현재 스크립트의 섹션 또는 전달된 테이블을 index×4로 조회. 전체 호출자 조사 미완료 |

EXE에서 파일→RAM 변환은 `RAM = file offset + 0x80090000`이다.
위 VM·텍스트 코드 및 jump table은 일본어/한국어판에서 바이트 동일하다.
`dg_analyze.py`가 범위별 SHA-256 및 Capstone disassembly를
`work/dg/analysis/consumer-evidence.json`, `consumer-*.asm`에 재생성한다.

고정 폭 명령은 `dg_script.WIDTHS`에 있다. byte reader `800F0EDC`, u16 reader
`800F1038`, s16 reader `800F1620`, skip+u16 `800F0E6C`, byte+u16 `800F0EA4`,
skip+2 bytes `800F0FF0`, 2 bytes `800F1078`, 2 shorts `800F1660`,
skip+2 shorts `800F0D10` 및 각 핸들러 호출을 대조했다.
`FB`의 인자는 script/map ID다. 이를 script/section으로 해석했던 초기 모델은
거짓 미해결 참조 251개를 만들었고 `800EC448`의 map loader 호출로 폐기했다.
`FB` 이후 PC는 이어진다. `FE/FF`는 한 byte 소비 후 VM stack을 풀며,
뒤의 00 byte는 다음 opcode로 해석하지 않는다.

## MAPHEAD와 native 참조

양쪽 판 모두 DG `[0x800, 0x6236)`의 23,094 bytes가 MAPHEAD 전체와 정확히 같다.
DG allocation 0의 나머지 할당 tail은 MAPHEAD의 일부가 아니다.
script 0 수정은 **DG 사본과 실제 로드되는 MAPHEAD를 함께 수정**해야 한다.

`800FA2C0`은 공통 native 대사 섹션 1220..1230을 고른다. 이 고정 리비전에서
각 섹션의 14개 4-byte 항목, 총 154개 참조를 별도 catalog로 보존한다.
각 항목은 `16 00` + u16 상대 offset이다. 일반 VM의 jump와 native index 조회가
같은 바이트를 다르게 사용할 수 있으므로 CFG의 첫 jump만으로 참조 전체를 세면 안 된다.
이 154개는 **모든 native 참조의 완전 목록이 아니다**. 다른 섹션과 overlay 호출자는 남는다.

기존 `dialogue-candidate-00009`, DG header offset `0x4240`은 이번 CFG 및 native
catalog에서 참조가 확인되지 않았다. 따라서 `dg-text-004240`의 재삽입은 거부한다.
문장의 매매 방향이 틀렸다는 원문 대조와 실제 실행 여부를 분리한다. 미참조 관찰만으로
dead data라고 확정하지 않는다. 공통 native catalog는 더 뒤의 텍스트들을 가리킨다.

## 범위와 무변경 왕복

양쪽 판에서 같은 구조를 얻었다.

- 225 할당 영역, 1,559 섹션 참조, 34,189개 명령/복합 명령.
- 텍스트 4,617개. `10`에 포함된 327개 텍스트도 개별 ID를 갖는다.
- 기존 검색과 경계가 대응하는 것은 4,476개, 검색 밖 신규 단위는 141개.
- 기존 7,857개 검색 후보 중 3,381개는 현재 소비 경로 미확인.
  한국어에서는 이 중 3,301개의 payload가 확인된 단위와 같다. 이 중복은
  실행 증거가 아니며 번역량으로 더하지 않는다.
- 예: DG `[6800, 6A5C)`의 604 bytes가 할당 tail `[6A5C, 6CB8)`에 다시 있다.
  tail 안의 문장 패턴을 별도 실행 대사로 세던 검색 방식의 위험을 보여 준다.
- 명시적 분기/섹션 참조의 미해결 대상 0, decoded 명령의 overlap 0.
- script 98/153/179/220의 `6B`에서 4개 경로가 오류로 보고된다. 이 판의 handler
  `800EEB38`은 인자를 소비하지 않는 1-byte no-op이다. 뒤의 `00`은 무효 opcode라
  `800F08A4` → `longjmp(…,2)` → `800F3114`로 script가 끝난다. 이 4곳은 section 11의
  `6B 00 … FF` 레코드 표다(2026-10-22, current.md 참조).
  다른 판 편집기의 `FF`까지 건너뛰는 규칙을 채택하지 않았다.
- relocation에 필요한 외부/동적/내부 참조 전체는 아직 조사 완료가 아니다.

파서는 entry/branch를 따라가며, 모르는 opcode 뒤에서 `1A00`를 검색해 이어가지 않는다.
해석하지 못한 영역은 그대로 보존한다. 헤더·명령·opaque 영역의 전체 byte partition을
JSON 저장/재로딩 후 재조립하여 **각 판의 692,224 bytes 전체**와 비교했다.
이는 opaque 영역 보존을 포함한 225 영역 왕복이지 전체 VM 해석 완료가 아니다.

한국어 확인 텍스트 4,617개의 payload **230,022 bytes**도 Unicode manifest로
내보내 다시 넣었다. `work/build/dg-all-unchanged/dg-dev.iso` 전체 SHA-256은
기존 한국어 ISO와 동일한 `12346b169b67fed618df8262e701781f42db1cdde7c459bb92190a24371f54d9`다.

## 편집과 빌드

```sh
python3 tools/dg_analyze.py
python3 tools/dg_export.py --id dg-text-0042e0 --output work/dg/my-edits.json
# my-edits.json의 text만 편집한다. expected_hex와 입력 hash는 보존한다.
python3 tools/dg_build.py --edits work/dg/my-edits.json --output work/build/my-dg --alignment-repair
```

`work/dg/analysis/texts.jsonl`에서 ID, 명령 위치, 원문 bytes, 한국어, 구조화된
제어 토큰을 확인한다. `--id`는 반복 가능하고, 생략하면 빈 manifest를 만든다.
`--alignment-repair`는 기존 `tools/build.py`의 4명령 정렬 수정을 함께 적용한다.
그 옵션 없이 전 텍스트를 원문 그대로 다시 넣으면 원본 ISO 전체가 일치해야 한다.

현재는 **정확한 길이 유지 정책**만 구현했다. 편집으로 문장을 억지로 줄이거나 공백을
자동 추가하지 않는다. 길이가 바뀌면 공간 확대·참조 갱신 조사가 필요하다는 오류로 중단한다.
이는 최종 번역 분량이나 표현을 제한하기로 한 사용자 결정이 아니다.

빌드는 검수 문자표를 원본 픽셀·검수 기록으로 다시 생성해 manifest hash와 대조한다.
없는 글자, 중복 문자 모호성, 미확정 글리프 변경, raw code로 새 글리프 주입,
제어 코드·인자·종료쌍의 변경/이동, 중복 writer, 길이 차이, 틀린 원본 bytes를 거부한다.
모든 제어의 의미가 확정된 것은 아니므로 현재 정책은 위치까지 보존하는 `forbidden`이다.
배포 허가를 뜻하지 않는다.

논리 파일 쓰기 계획 → sector별 payload 쓰기 → EDC/P/Q 재생성 순서로 실행한다.
원본 sector 무결성, write overlap, 최종 ISO의 모든 sector, 파일시스템 불변,
DG·MAPHEAD 재추출, 재해석 후 명령/분기 구조를 검사한다. 영상 등 다른 sector는 보존한다.
기존 출력은 덮어쓰지 않고 새 디렉터리에 ISO/CUE/build.json/입력 manifest를 남긴다.

## 검증 및 한계

`python3 -m unittest discover -s tools -p 'test_*.py'`로 경계·제어·거부 조건과
sector 경계를 넘는 쓰기 및 overlap 거부를 검사한다. 기존 검수 도구 테스트를 포함해
24개가 통과했다.

선택적 CPU 검증:

```sh
python3 -m pip install -r requirements-dg-verify.txt
python3 tools/dg_cpu_verify.py --build work/build/dg-qa
```

Unicorn 2.1.4에서 **원본 EXE의 `800F4200`**을 실행했다. 호출을 stub으로 대체하거나
소비 코드를 수정하지 않았다. RAM은 시험용 입력·출력 버퍼와 textbox 상태를 초기화했다.
일본어 4,252개 / 한국어 4,254개의 단위에서 실제 script PC가 파서의 end와 일치했다.
이름·아이템 등의 동적 삽입 환경이 필요한 일본어 365개 / 한국어 363개는 이 실행에서
제외했다. 03 인자 내부의 0000, 줄 끝 밖 0000, 여러 줄을 별도 fixture로 검사했다.
Unicorn 결과는 **독립된 CPU 함수 실행 증거**이며 PS1 화면, load delay timing,
실제 장면의 도달성, 저장/재로드 검증이 아니다.

`work/build/dg-qa/`는 DG의 두 단위 `0042e0`, `0068aa`의 첫 한글을 `가`로 바꾸는
**합성 QA fixture**다. 승인된 번역 수정이 아니며 배포하면 안 된다. script 0의 MAPHEAD
사본과 정렬 수정까지 포함해 네 sector만 변경되었다. SHA-256:
`c6e08024242f1930e22b9ca5be0584cc51b15599bd15d3e6972da673e5a81cd4`.
해당 ISO에서 재추출한 두 단위도 원본 CPU 소비 함수에서 정확한 종료 위치에 도달했다.

이 세션의 emucap port 47800은 다른 세션 토큰의 기존 `digimon-alignment-dev`가
점유 중이었다. 그 프로세스에 연결·중단·상태 변경을 하지 않았다.
당시 개발용 ISO의 실제 게임 화면 검증은 없었다. 후속 `dg-runtime-001`에서 기존 QA의
콜드 부팅과 자유 이동, MAPHEAD 수정 바이트 로드를 확인했다. 별도 `dg-runtime-qa`에서는
자연 도달 경로를 확인한 두 문장 `0059c0`/`064958`의 디스크→RAM→소비자→화면 및
다음 대사 진행을 통과했다. 원래 QA 두 문장의 화면 검증으로 일반화하지 않는다.
빌드 보고서의 `gameplay_runtime_verified=false`는 빌드 시점 값이며 실행 결과로 덮어쓰지 않는다.
실행 증거는 `work/runtime/dg-verification/verification.json`과 [실행 기록](dg-runtime.md)에 분리한다.
모든 결과는 개발용이며 폰트 확장·조합형 이름 입력·전체 번역 개선 완료본이 아니다.

## 외부 단서

[SydMontague/DW1-Code](https://github.com/SydMontague/DW1-Code)의 미국판
함수 설명을 탐색 단서로 사용했으며 주소·명령 폭은 일본어 EXE에서 다시 확인했다.
로컬 참조본은 `work/reference/dw1-code/`, commit
`313a90116b8bb9060c382228abf48ecae6c06c67`이다. 외부 구현 코드를 도구에 복사하지 않았다.
기존 스페인어 편집기는 `14`, `6B`, `7B` 등의 처리에서 이 판과 맞지 않아 그대로 채택하지 않았다.
