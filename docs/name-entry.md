# 두벌식 조합형 이름 입력

2026-09-28 사용자 선택: 단계별 초성·중성·종성 선택 대신 **두벌식 자판처럼 자모를
연속 입력**한다. 지원 완성 음절은 기존에 확정한 KS X 1001 2,350자다.
이름 길이는 기존 두 이름의 6글자를 유지한다.

## 입력과 저장

- 방향키로 두벌식 화면 자판을 이동하고 ○로 입력한다. L1은 쌍자음/ㅒ/ㅖ 자판 전환,
  ×는 삭제, START는 이름 확정이다.
- 복합 모음과 겹받침을 합성한다. 뒤에 모음이 오면 받침을 다음 초성으로 넘긴다.
  `ㄱㅏㄴㅏ → 가나`, `ㄷㅏㄹㄱㅏ → 달가`, `ㅂㅏㄲㅏ → 바까`를 포함한다.
- 편집 중인 자모는 별도 상태에 둔다. 완성된 지원 음절만 기존 이름 버퍼에 쓴다.
  미완성·지원 범위 밖 음절은 확정할 수 없다. 다른 글자로 대체하거나 생략하지 않는다.
- 삭제는 겹받침 → 단받침 → 복합 모음 → 단모음 → 초성 순으로 조합을 되돌린다.
  조합이 없으면 직전에 확정한 한 글자를 지운다.
- 주인공과 디지몬 모두 기존의 2바이트 코드 × 최대 6글자 + 1바이트 NUL을 사용한다.
  기존 코드의 정체성을 바꾸지 않으며 중복 `늪`은 검수된 첫 코드 `88C0`으로 입력한다.
  자모·조합 상태는 이름 데이터나 세이브에 넣지 않는다.

## 구현과 주소

`tools/name_entry.c`는 freestanding C로 작성한 실제 PS1 MIPS I 편집기다.
`tools/name_entry.py`가 LLVM Clang, LLD ELF로 배치하고 LLVM MIPS I 디코더,
Capstone, 재어셈블 왕복, load/branch delay 검사를 수행한다.
분모는 생성한 코드 전부이며 게임 전체의 ISA/참조 분석 완료를 뜻하지 않는다.
Clang의 나눗셈 0 검사 기본 출력에 MIPS I 밖 `teq`가 나오는 것을 디코더가 검출했다.
분모가 상수인 나눗셈만 사용하고 `-mllvm -mno-check-zero-division`으로 생성한다.
링커 코드 정렬 영역은 명시적으로 NOP(0)로 채운다.

기존 이름 입력에만 속하는 SHOP 루틴 RAM `[800849E0,80086504)`를 대체한다.
SHOP 논리 파일 offset으로는 `[41E0,5D04)`다. overlay base는 `80080800`이다.
변경하지 않은 창 생성자의 두 callback 주소, field callback 주소, 두 초기화 호출을
새 심볼에 연결한다. `80086504`의 원래 밑줄 그리기 경로는 보존한다.
원래 이름 선택 표/문자열은 제품 입력으로 쓰지 않는다.

완성 음절 → 기존/확장 코드 조회표는 2,832바이트다.
11,172개 Unicode 음절 위치의 KS 포함 비트맵(1,397바이트), KS 순서에서 기존 한글인지
표시하는 비트맵(294바이트), 기존 912자의 10비트 glyph index(1,140바이트), guard 1바이트다.
새 글자는 KS 순서에서 기존 글자 수를 빼 기존 확장 폰트 코드 순서로 변환한다.
전체 11,172자 폰트를 추가하는 구조가 아니다.

조회표는 기존 폰트 압축 영역의 남는 부분과 대체 SHOP 영역에 나눈다.
폰트·DG pixel row·이름 표의 주소는 빌드 결과에서 계산하고 중복 쓰기를 거부한다.
51개 호환 자모를 기존 폰트 공급자에 추가하며 완성 음절 2,350자와 기호를 보존한다.
이름 조합 상태는 SHOP에 귀속된다. 새 overlay 파일 길이·LBA·RAM 할당은 필요 없다.

## 재현과 검증

현재 개발 빌드 경로:

```sh
python3 tools/dg_expand.py \
  --edits work/line-width-168/selected-final/edits.json \
  --expand-font --name-entry --output work/build/name-entry
python3 tools/name_cpu_verify.py work/build/name-entry
python3 tools/font_cpu_verify.py work/build/name-entry
python3 tools/dg_bank_verify.py --build work/build/name-entry
python3 tools/dg_pixel_verify.py work/build/name-entry
```

`--name-entry`는 `--expand-font`를 요구한다. 원본 한국어 ISO의 해시와 SHOP 전체 해시를
확인한다. 기존 sector 쓰기 계획에 통합하여 이미지 전체 diff, 변경 파일 재추출,
EDC/ECC를 검증한다. 루트의 ISO·BIOS는 수정하지 않는다.
현재 확인한 도구는 Clang/LLVM MC 23.1.2, LLD 22.1.6, Unicorn 2.1.4다.
LLD는 `LLD` 환경 변수, PATH의 `ld.lld`, 설치된 Rust의 `rust-lld` 순서로 찾는다.

CPU 검증은 최종 ISO에서 EXE와 SHOP을 다시 추출하여 **설치된 MIPS**를 실행한다.
11,172개 조합의 코드 조회, 2,350자 × 6칸 = 14,100개 실제 두벌식 키 입력 경로,
지원하지 않는 8,822개 조합의 확정 거부, 받침 분리, 삭제, 미완성 확정 거부,
최대 길이, 주변 메모리 guard와 스택 복원을 검사한다.
이 검증의 CPU는 GPU와 메모리카드를 구현하지 않는다. 실제 게임·저장 증거는
`docs/current.md`의 해당 리비전 기록과 `work/name-entry/`의 런타임 기록으로 구분한다.
