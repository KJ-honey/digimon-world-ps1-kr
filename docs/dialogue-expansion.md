# DG 대사 바이트 확장 — 별도 대사 bank

2026-09-28, `dg-expand-001`. 기존 번역을 바꾸지 않는 개발용 구현이다.
`dg_export.py`의 기존 manifest를 그대로 입력하며, 원문 payload 길이와 번역 길이가
달라도 빌드한다. 미확인 후보를 실행 대사로 승격하지 않는다.

## 사용법

```sh
python3 tools/dg_export.py --id dg-text-0059c0 --output work/dg/my-edits.json
# text만 편집한다. 원문 bytes/hash와 ID는 유지한다.
python3 tools/dg_expand.py --edits work/dg/my-edits.json --output work/build/my-expanded
# 기존 2,350자 폰트 공급기를 함께 적용할 때: --expand-font
python3 tools/dg_bank_verify.py --build work/build/my-expanded
```

출력은 `dg-expanded.iso`, `dg-expanded.cue`, `build.json`이다. 기존 정렬 수정은
항상 포함한다. 원본 ISO, 메인 워크트리, 번역 파일은 수정하지 않는다. 기존
`dg_build.py`는 그대로 사용할 수 있다. 이 도구의 결과는 배포 완료본이 아니다.

문장을 자동 축약하거나 공백을 지우거나 채우지 않는다. 검수 문자표의 공백은
U+3000이다. 없는 글자·모호한 중복 코드·제어/인자/미확정 기호의 변경은 오류다.
제어의 **순서와 값**은 보존하되 일반 글자 수가 달라져 제어의 byte 위치가 이동하는
것은 허용한다. 따라서 원래 줄 수는 유지한다. 한 줄의 실제 소비 버퍼는 64 bytes이므로
줄바꿈 2 bytes와 제어·동적 삽입의 최악 길이를 포함하여 검사한다. 이것은 저장 슬롯
제한과 별개인 RAM 경계이며, 화면 폭이 맞는다는 증거는 아니다.

## 기존 위치를 유지하는 이유

일반 DG loader `800F0988`은 DG u32 경계의 차이를 `800EC21C`에 전달한다.
일반 script RAM은 `80161784..80163783`의 8 KiB이고, 바로 다음
`80163784..80163A1F`는 VM 상태, `80163A20`부터는 text 출력 버퍼다.
단순히 할당 크기를 늘리면 이 상태를 덮어쓴다. 모든 native/opaque 참조도 아직
해석되지 않았으므로 스크립트 안의 명령을 밀어내는 재배치는 채택하지 않았다.

원문 위치의 payload 첫 4 bytes만 `15 D7` + little-endian u16 record index로
바꾼다. 가장 짧은 빈 대사도 `0D00 0000` 4 bytes이므로 descriptor를 수용한다.
나머지 원문 bytes, 모든 명령·분기·섹션·선택지 table의 script-relative offset은
그대로 둔다. script 0의 descriptor는 실제 로드 원본인 MAPHEAD에도 쓴다.

`800F4200` 진입을 wrapper로 연결한다. 원래 포인터가 DG RAM 범위의 짝수 주소이고
marker가 일치할 때만 새 대사를 읽는다. 원본 DG에는 marker가 한 번도 없음을
빌드가 검사한다. 원본 함수를 실행한 뒤 원래 대사의 끝으로 VM PC를 되돌린다.
원본 소비자의 **다음 opcode가 1A인가** 검사도 보존한다: 원래 다음 opcode를
임시 record의 확장 terminator 바로 뒤에 복사한 뒤 원본 소비자를 호출한다.
수정하지 않은 대사는 원래 함수로 전달한다.

이름·아이템 등 동적 대사와 native 호출도 공통 소비자를 통과하는 경로가 있다.
`800FD584 → 800F4D5C → 800F4200` 및 `800FEE6C → 800F4D5C`를 확인했다.
이는 모든 overlay/native 표시 경로의 조사 완료를 의미하지 않는다.

## 디스크 → RAM 배치

좌표를 구분한다. 이 절의 DG offset은 **논리 파일 offset**, `801…`는 **RAM**이다.
실제 ISO LBA와 raw sector offset은 별개이며 `build.json`과 sector 계획으로 검증한다.

| 범위 | 용도 |
| --- | --- |
| DG `0000..07FF` | 원본 directory/문자열 보존, 첫 226개 u32에만 `0x1800` 가산 |
| DG `0800..0FFF` → RAM `8015FF84..80160783` | assembler로 생성한 wrapper/trampoline |
| DG `1000..17FF` → RAM `80160784..80160F83` | 한 record용 2 KiB scratch, 초기 0 |
| DG `1800..1FFF` | 초기 0, 사용하지 않음 |
| DG `2000..AA7FF` | 기존 script allocation 전체, 내부 배치 불변 |
| DG `AA800` 이후 | 변경 대사당 한 개의 2 KiB record |

기존 초기화는 directory buffer `8015F784..80161783`에 처음 8 KiB를 읽는다.
원래는 여기서 script 0의 앞부분까지 중복으로 읽었다. directory 참조자는 첫 226개
u32만 사용한다. EXE와 `_REL.BIN`의 해당 GP 상대 참조를 검사했으며 directory 포인터
`gp-6CF4`는 초기화의 쓰기/로드와 `800F09D4` 조회에서만 나왔다. 조사 파일은
`work/dg/bank-reference-audit.json`이다. 이 정적 직접 참조 감사가 임의 계산으로
만든 모든 RAM alias까지 입증하는 것은 아니다.

record는 `<u16 old_length, u16 new_length, "DGB1", payload, padding>`이다.
길이는 terminator를 포함한다. 8-byte header와 다음 opcode 한 byte까지 2 KiB 안에
들어야 한다. bank index는 u16이다. CD I/O는 기존 동기 함수 `800EC21C`를 호출하며
파일 offset과 크기를 모두 2 KiB 단위로 전달한다. 이 함수는 offset/size를 오른쪽으로
11비트 이동하므로 임의 byte offset을 직접 전달하면 안 된다.

DG 전체를 원본 raw track 뒤에 append하고 ISO9660의 해당 file extent/size 및 PVD
volume size 양쪽 endian 값을 함께 바꾼다. 원래 DG extent는 보존한다. 다른 파일과
영상의 LBA는 바꾸지 않는다. 새 sector는 LBA+150의 BCD MSF를 가진 Mode 2 Form 1이며
EDC/P/Q를 생성한다. [sector 형식 참고](https://psx-spx.consoledev.net/cdromformat/).
최종 파일 목록은 DG extent/size 변경만 허용하고, 모든 기존/추가 sector와 최종 길이를
사전 계획에 대조한다. 경로 table은 directory 위치를 바꾸지 않으므로 수정하지 않는다.

## 기계 코드와 ABI

`800F4200`의 원래 `addiu sp,-30; sw ra,1C(sp)` 8 bytes를 exact-match 검사한 뒤
절대 J/NOP로 바꾼다. helper가 인자/return address와 원래 continuation을 자기 스택에
보관하며, trampoline이 덮어쓴 두 명령을 실행하고 `800F4208`로 돌아간다.
원본 함수의 결과 v0, callee-saved registers, stack pointer를 유지한다.

`font_expand.assemble`의 LLVM MIPS I 조립·ELF relocation 거부·독립 Capstone 디코딩·
재조립 byte 일치 검사를 공유한다. helper는 directory read로 공급되며 scratch와 겹치지
않는다. 다른 이미지의 savestate를 넣으면 실행 코드/descriptor가 옛 버전일 수 있으므로
실제 검증은 새 이미지 콜드 부팅에서 시작한다.

## 검증 상태

- 원본 길이/제어 byte 위치 제한을 없애고, 제어 순서·행 버퍼·인코딩 검사를 구현했다.
- 확인된 4,617 단위 각각에 시험 공백 2 bytes를 추가했다. 4,592개가 빌드되었으며
  25개는 아직 최대 길이를 확정하지 않은 동적 table 삽입 때문에 거부했다. 이는
  번역 변경 승인이나 전체 추출 완료 수가 아니다.
- `expanded-stress`의 4,592개 모두 설치된 wrapper와 원본 소비자를 Unicorn에서 실행했다.
  출력 버퍼와 반환 폭은 원본 소비자에 긴 payload를 직접 넣은 결과와 일치했고,
  원래 continuation, callee-saved 상태, scratch 양쪽 guard가 보존됐다.
  다음 opcode를 원본과 동일하게 두었을 때 textbox 상태도 일치했으며, 이 중 연속
  `1A` 대사 606개를 포함한다.
  두 이름은 최대 6글자 fixture다. **CD 읽기와 BIOS strcpy/strlen은 명시적 stub**이므로
  실제 장면·CD streaming·BIOS 실행 검증으로 계산하지 않는다.
- `expanded-qa-02`는 첫 할배몬(114→126 bytes), 씨앗몬(40→42 bytes)의 합성 QA다.
  byte 수는 terminator 포함. 첫 문장의 추가 `가나다라마`는 번역이 아니다.
  SHA-256 `ba238d1f6e18a46b5e25cc187df1867c3d06e0847ecbeb5350912a63fc0e5d23`.
- Mednafen 1.32.1 / emucap df23142에서 콜드 부팅 → 새 게임 → 첫 확장 대사 표시 →
  다음 질문과 선택지 → 두 이름 입력/재표시 → 마을 도입부까지 진행했다.
  MAPHEAD 23,094 bytes, helper 2,048 bytes, 확장 record header/payload가 디스크와 RAM에서
  일치했다. 당시 VM PC 저장소는 프레임 진행 중 초기화되어 0이었으므로 그 RAM 덤프를
  순간 종료 포인터 증거로 사용하지 않는다. 다음 대사 진행과 CPU continuation 검증은 별도다.
- 일반 맵으로 이동하여 script 149를 새 DG에서 로드한 뒤 씨앗몬의 `고기를`을 확인했다.
  6,144-byte script와 bank record가 RAM/디스크 일치했고, wrapper의 exec breakpoint에서
  원래 continuation `80162106`을 포착했다. event drop 0, 다음 설명으로 진행했다.
  화면·RAM·state·관찰 기록: `work/dg/expansion-runtime/verification.json`.
- `expanded-font-qa`의 결합 이미지도 대사 CPU 검증과 2,430칸 glyph/4bpp CPU 검증을
  통과했다. SHA-256 `332e51651958efbb13a02b5ce7279cd4e53a6661bb71a30580d5ebcce34f381f`.
  이 결합 이미지 자체의 실제 게임 화면은 검증하지 않았다.

감사/합성 stress manifest 재생성:

```sh
python3 tools/dg_expand_audit.py --output work/dg/expansion-audit-new
python3 tools/dg_expand.py --edits work/dg/expansion-audit-new/stress-edits.json --output work/build/expansion-stress-new
python3 tools/dg_bank_verify.py --build work/build/expansion-stress-new
```

## 남은 조건

- `07/08/09/11/12`(hex) 동적 table 삽입의 최대 출력 길이가 미확정이다. 현재 해당 25개
  단위는 변경 시 거부한다. `05/06` 이름은 12 bytes, 숫자 controls는 원본 출력 루프의
  digit 수를 예산으로 사용한다. 확인되지 않은 table 길이를 추정하여 통과시키지 않는다.
- 기존 줄/페이지 구조는 보존한다. 자유로운 줄 추가·자동 줄바꿈·선택지 행 증가를
  지원한다고 주장하지 않는다. 표시 폭은 실제 UI 검증 대상이다.
- 변경 대사마다 동기 CD 읽기를 추가한다. 전체 게임의 XA/영상 병행, 전투·native 대사,
  반복 로드/복귀, 대량 번역 적용 시 체감 지연은 회귀 검증이 남아 있다.
- 미검증 검색 후보 3,381개와 `6B`의 미해결 4개 경로는 기존 상태를 유지한다.
- 폰트 확장 동시 적용의 실제 게임 및 메모리카드 저장/재로드의 이번 bank 회귀는 별도다.
