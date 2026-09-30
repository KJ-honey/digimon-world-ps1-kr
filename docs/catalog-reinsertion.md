# 대사 외 문자열 재삽입 (`catalog-insert-001`)

2026-09-28. `catalog_insert.py`로 지명 70, 아이템명 128, 아이템 설명 128,
디지몬 이름 180개를 원본에 묶인 편집 manifest로 내보내고 `dg_expand.py`에서
대사·확장 폰트·이름 입력과 함께 빌드한다. 번역 문구나 승인 상태를 자동 변경하지 않는다.
아직 개발용이며 이름 레코드 자체의 확장과 전체 UI 회귀는 미완료다.

```sh
# 현재 작성한 명칭/설명 문구를 내보낸다. held 항목이 있으면 오류다.
python3 tools/catalog_insert.py --output work/catalog/my-edits.json
# 아직 작성하지 않은 항목을 명시적으로 내보내려면 --id를 반복한다.
# 예: --id location_name-043 --id item_name-000
# manifest에서는 text만 편집한다. 원문 bytes/ID/hash는 보존한다.

python3 tools/dg_expand.py \
  --edits work/line-width-252/selected-final/edits.json \
  --catalog-edits work/catalog/my-edits.json \
  --expand-font --name-entry --output work/build/my-catalog
python3 tools/catalog_cpu_verify.py work/build/my-catalog
python3 tools/dg_bank_verify.py --build work/build/my-catalog
python3 tools/dg_pixel_verify.py work/build/my-catalog
```

`--catalog-edits`는 `--expand-font`를 요구한다. `--name-entry`는 기존 두벌식 입력을
유지하는 옵션이다. 카탈로그만 시험하려면 DG manifest의 `edits`를 빈 배열로 지정해도 된다.
빌드는 양쪽 원본 ISO에서 catalog baseline을 재생성하여 해시·원문 bytes·소비자를 검증한다.
누락 문자, 잘못된 토큰, 보호 글리프 삭제, 중복 ID, 오래된 기준, 폭/필드 초과는 오류다.
자동 축약·공백 삭제·누락·대체·실패 항목 자동 제외는 하지 않는다.

## 길이와 저장 정책

| 종류 | 정책 | 현재 경계 |
| --- | --- | --- |
| 지명 | DG 초기 directory 예약 영역의 상주 byte-NUL 문자열 | 개별 원래 길이와 무관, 252px 이하. 설명 descriptor와 합계 2 KiB 이내 |
| 아이템 설명 | 항목별 독립 CD record, 해당 포인터만 갱신 | 원래 문자열 길이와 무관. 한 행 252px 이내 |
| 아이템·디지몬명 | 원래 레코드의 이름 필드 안에서 성장/축소 | NUL 포함 20 bytes, 현재 2-byte 단위 최대 9개 |

**이름 필드 20 bytes를 넘는 재배치는 아직 지원하지 않는다.** 이 경계를 넘어 쓰면
아이템/디지몬 수치 필드를 훼손한다. DG의 기존 사용자 지정 10글자 동적 예산은
20-byte 이름 필드 확장의 증거가 아니다. 10글자 이름은 NUL까지 21 bytes여서 거부한다.
기존보다 긴 이름은 필드 안에서 지원하되, 원문 길이 제한을 없앴다는 것과 레코드 제한을
없앴다는 것을 구분한다. 후속에는 모든 복사 버퍼·UI/overlay 소비자와 참조를 조사해야 한다.

포인터 항목은 같은 원문 주소를 공유해도 새 포인터와 저장 영역을 개별 배정한다.
원래 문자열은 바꾸지 않으므로 다른 별칭과 내부 참조를 훼손하지 않는다. 원래 공유 문자열을
재활용 가능한 빈 공간으로 간주하지 않는다. 인라인 이름은 새 NUL 뒤의 잔여 bytes도 보존한다.

252px는 확인된 렌더러의 최대 행 용량이며 모든 지명/인벤토리 창의 실제 가용 폭이 아니다.
창별 배치·잘림·지우기와 재표시는 실제 게임 검증 대상이다.

## 반각 공백과 코드 경로

- U+0020 일반 공백: **`0F 01`, 2 bytes, 실제 6px**.
- U+3000 전각 공백: `81 40`, 2 bytes, 12px.
- 일반 문자열의 끝: **단일 byte NUL**. DG의 `0F00`을 쓰면 `strcpy`/`strlen`이
  공백 중간에서 끊기므로 채택하지 않았다.
- 기존 DG 행 렌더러는 `0F`의 두 번째 byte를 건너뛴다. 이름을 DG에 동적으로 복사해도
  `0F01`은 6px로 작동한다. DG 문구의 원래 공백 인코딩 `0F00`은 그대로다.
- 일반 렌더러 RAM `0x800A5B48..0x800A5BCB`(EXE 논리 `0x15B48..0x15BCB`)를
  132-byte 루프로 교체한다. 일반 글자는 원래 glyph uploader를 계속 사용한다.
  `0F01`부터의 suffix만 EXE 상주 dispatch를 통해 기존의 정확한 픽셀 DG 행 렌더러로 전달한다.
  타이틀의 반각 공백은 DG directory 초기화를 요구하지 않는다. 홀수 주소도 byte
  load로 읽는다. 기존 4명령 alignment repair와 별도 중복 쓰기를 만들지 않는다.
- `0F02 + little-endian u16 record index`는 포인터 항목용 descriptor이며 번역 인코딩에
  허용하지 않는다. 일반 문자열/이름에 descriptor를 복사하는 정책은 채택하지 않았다.

## 매체와 RAM 좌표

| 좌표 | 용도 |
| --- | --- |
| DG 논리 `0xC00` / RAM `0x80160384` | CD record를 읽고 일반 문자열을 표시하는 helper |
| DG 논리 `0x1800..0x1FFF` / RAM `0x80160F84..0x80161783` | 앞쪽 설명 descriptor 배열, 뒤쪽 지명 byte-NUL 문자열. 충돌 시 빌드 실패 |
| `build.json`의 `catalog.bank_file_offset` | DG 대사 bank 뒤에 이어 붙인 카탈로그 record 시작 |
| record 하나 | 2 KiB, byte-NUL 문자열 + 0 padding |

기존 DG directory 초기 읽기는 8 KiB다. 기존 helper sector의 여유 부분과 기존 예약
sector만 사용하고 script RAM 시작·8 KiB script buffer·대사 scratch는 이동하지 않는다.
카탈로그 helper는 별도의 스택 sector를 사용하므로 진행 중인 DG bank scratch를 덮지 않는다.
한 호출의 추가 스택은 CD buffer 2,080 bytes와 DG pixel row/원래 소비자 프레임이다.
지명·설명 표시 전에 DG directory 초기화가 완료되어야 한다.

최종 쓰기는 기존 `image_plan`의 단일 sector 계획으로 합친다. ISO LBA/raw sector offset은
위 논리 파일/RAM 좌표와 별개다. 새 DG extent append, ISO directory/PVD 양쪽 endian 값,
EDC/ECC, 변경하지 않은 모든 sector, 최종 재추출을 검증한다. 전체 506개를 다시 읽어
편집 payload·포인터·descriptor·수치 필드·수정하지 않은 공유 항목을 대조한다.
새 코드에는 LLVM MIPS I 조립/역조립 byte 왕복, Capstone 최종 주소 디코딩,
분기 경계 및 R3000 load/control delay 검사를 적용한다.

## 검증 기록과 미해결

- Python 자동 테스트 84개 통과. 인코딩 실패, 보호 토큰, 공유 포인터 분리, 결정적인 배치,
  원문 바인딩, 원래 길이를 넘는 인라인 성장, 20-byte 초과 거부, 재추출 손상 검출을 포함한다.
- `work/build/catalog-qa-002`: 네 종류 각 1개에 합성 ` 힝`을 덧붙였다. 모두 원래보다
  4 bytes 길다. 현재 대사 4,617개 선택/4,421개 변경, Mona12와 두 이름 입력을 함께 넣었다.
  SHA-256 `9fb2136a3acce0be87449351beaefa0e3aa0d6ea675b37d9cb9c1737161db904`.
- `work/build/catalog-stress-003`: 506개 선택, 합성 변경 505개, 원형 유지 1개.
  504개가 원래보다 길고, 포인터 198개는 모두 45 bytes/252px, 인라인 변경은 19 bytes다.
  SHA-256 `e0ade365fefe8f75f20476763110fa0e52fafcf274c2d1c021fc069899f327d5`.
  번역 검수 파일에는 이 합성 문구를 쓰지 않았다.
- 두 이미지 각각 **506개 일반 표시 + 308개 실제 DG 테이블 복사/길이 경로**를 MIPS로
  실행했다. VM 인자는 테이블 번호 자체가 아니라 byte 변수 인덱스이므로 실제 변수 reader도
  실행하고 해당 변수값을 fixture로 설정했다. glyph oracle과 모든 4bpp 픽셀을 대조했다.
  연속/앞뒤/전각 혼용 공백, 최대 행, 빈 행, 홀수 문자열 주소, 여러 X 시작점을 검사했다.
- QA 이미지의 4,421개 변경 대사 bank CPU 검증과 2,480개 glyph의 기존 DG pixel 검증 통과.
  비교 oracle도 현재 인라인 이름 bytes를 사용하여 정당한 동적 문구 변경을 오류로 오인하지 않는다.
  CPU 검사에서는 CD/GPU/DrawSync/BIOS 서비스를 stub으로 처리한다. 실제 기기/창 검증은 아니다.
- 기존 `item_name-121`의 `초⟦G:9860⟧꽃　열매`에서 **`9860`은 실제 공급 문자표 밖 코드**다.
  원래 fallback 동작을 별도로 확인했으며 새 glyph가 지원된 것으로 계산하지 않는다.
  미변경 원형 보존은 가능하지만 이 토큰을 포함해 문구를 수정하면 누락 glyph로 빌드를 거부한다.
  stress에서 이 항목 1개를 원형으로 둔 이유다. 임의 한글 대체나 보호 토큰 삭제는 하지 않았다.

실행 증거는 각 빌드의 `catalog/cpu-verification.json`, `bank/cpu-verification.json`,
`pixel-row/cpu-verification.json`과 `work/catalog-insert/`에 있다. 미추출 UI/overlay,
카드·기술·곡·대회명은 계속 미해결이며 전체 게임 재삽입 완료로 보고하지 않는다.


## 2026-09-29 타이틀 공백·지명 잘림 수정

`menu_layout.py`가 타이틀 메뉴 포인터 8개(EXE 논리 `0xAA350..0xAA36F`)의
단어 사이 `8140`을 `0F01`로 바꾼다. 커서 앞 여백 두 칸, NUL, 바이트 길이,
내부 별칭은 보존한다. 타이틀 문구 전체의 번역 편집기 연결은 아직 미해결이다.

기존 지명 포인터를 `0F02 + record index`로 바꾼 뒤, 맵 전환 callback RAM
`0x800E424C`가 BIOS strlen을 호출해 3 bytes로 계산했다. 이후 `floor(3/2)*12`가
12px가 되어 ‘시작의 마을’ 66px 중 첫 글자만 표시했다. glyph upload가 맞아도
마지막 sprite의 폭이 틀릴 수 있으므로 이전 506개 upload 검사는 이 결함을 놓쳤다.

callback의 EXE 논리 `0x54290..0x5430B`는 실제 픽셀 폭을 재고 중심점과 sprite 폭을
함께 맞춘다. 70개 지명에 대해 원래 lookup/callback을 CPU로 실행해 두 값을 대조한다.
지명 표의 다른 참조도 조사하여 RAM `0x800FE288/0x800FE2A4`의 strcpy/strlen과
`0x8010E098/0x8010EE3C/0x8010FCB8`의 저장 라벨 복사를 확인했다. 따라서 폭 metadata만
더하는 중간 실험(`menu-location-fix`)은 채택하지 않았다. 최종안은 지명 포인터를 실제
상주 문자열로 유지한다. 변경된 53개 지명의 원래 strcpy/strlen과 18-byte 저장 라벨
복사 함수를 CPU로 검증한다. 저장 화면의 기존 18-byte 표시 한도 자체를 확장한 것은 아니다.

설명 descriptor와 지명 문자열은 예약 2 KiB의 양 끝에서 배정한다. 현재 115개 설명
460 bytes + 53개 지명(정렬 포함 896 bytes)을 사용한다. 이 합계가 2 KiB를 넘는
합성 최대길이 입력은 이제 빌드 오류다. 예전 stress-003 통과를 새 배치의 증거로 쓰지 않는다.
CPU 검증은 여전히 CD/GPU/BIOS stub을 사용하며 실제 저장·재로드의 증거가 아니다.

최종 ISO는 `work/build/full-development/dg-expanded.cue`이며 실제 콜드 부팅의 타이틀,
두 이름 입력, 도입부 이후 ‘시작의 마을’ 전체 표시를 확인했다. 사용자도 정상 표시를
확인했다. `menu-location-runtime.json`과 `work/map-location-final.png`에 증거를 남겼다.


## 기술명·기술세트 도움말 (2026-09-29 후속)

`build_full.py`에 신규 카탈로그 131개를 연결했다. 현재 변경 112개(기술명 102,
도움말 10)를 기존 번역과 함께 삽입한다. 기술명은 resident-technique-pool, 도움말은 independent-CD-record 정책을 쓴다.
이전 ‘기술명 미해결’은 이 범위에서 대체한다. 전체 UI/전투 회귀 완료를 뜻하지 않는다.

기술명 표 EXE 논리 `0xA23D8`, 121칸의 RAM 포인터를 유지/갱신하며 DG 08 복사는
RAM `0x800F4690`부터 실제 strcpy/strlen 소비자를 실행해 모두 검증했다.
이름 자체가 120px를 넘거나 121개 표 대상의 중복 제거 합계가 원래 EXE 기술명 영역
1,928 bytes를 넘으면 오류다. EXE 논리 `0xA0BD4..0xA135B`에 현재 1,588 bytes를
사용한다. 이 영역에 대한 literal pointer 107개는 모두 기술명 표에 있으며, 영역과
원본 소비자 해시·참조 수를 고정한다. DG 초기화 전에도 모든 기술명 C 문자열이 유효하다.
메모리 카드 소비자 RAM `0x8010D1C8`의 121개 lookup도 CPU로 검증한다.
기술명 전용 영역 밖의 공용 문자열과 원본 ISO는 보존한다.

도움말 12개 crop table은 EXE 논리 `0xA019C..0xA01FB`, 별도 제목/버튼/범례
crop immediate는 EXE 논리 `0x33F2C..0x3414F` 소비자에 있다. 생성 시 원래 코드와
표의 SHA-256을 확인한다. CPU로 RAM `0x800C3F2C..0x800C442C`를 실행해
18개 sprite 호출의 source UV·폭·화면 좌표를 확인했다. 문자열 렌더링 637개 픽셀
검사와 함께 검증하며 실제 GPU/게임 화면 증거로 보고하지 않는다.

`technique_help-003`의 글리프 index 8, `technique_help-004`의 index 11은 버튼
아이콘을 덮어 그리는 칸이므로 빌드에서 12px를 확보한다. 이는 단어 사이 공백이
아니며 원고의 반각 공백을 임의 삭제하지 않는다. 나머지 단어 공백은 6px다.
`002/003/004`의 packed 구획은 원래 글리프 수를 요구한다. 향후 조각별 자유 편집은
도구에 구획 경계를 별도로 제공해야 한다. `006/007`의 괄호 경계는 의미 기반으로
다시 계산하여 앞 문구 성장과 띄어쓰기를 지원한다.

`006/007`의 괄호 조각은 화면에서 각각 `008` 뒤에 붙는다. 합산 폭을 기준으로
괄호 X를 앞 문구의 끝에 맞추고, 오른쪽 끝이 146을 넘으면 문구와 아이콘을 함께
6px 단위로 왼쪽 이동한다. 아이콘 왼쪽이 -146보다 작으면 명시적으로 실패한다.
화면 X 명령은 EXE 논리 `0x340FC/0x3413C`(괄호), `0x343B0/0x343F0`(아이콘)이며
원본 명령 word를 검사한다. 앞 문구 위치는 crop table의 index 9/10이다.
CPU 검증은 두 줄의 실제 sprite와 아이콘 호출에서 접합 위치·행·패널 경계를
독립적으로 검사한다. 이전 이미지는 앞 문구 끝 96, 괄호 시작 66으로 이 검사에
실패한다. 현재 문구에서는 앞 문구 -114, 괄호 84, 아이콘 -132, 오른쪽 끝 144다.
