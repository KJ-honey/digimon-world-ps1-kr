# DG 실제 게임 검증 기록

2026-09-27, `dg-runtime-001`. Mednafen 1.32.1 / emucap df23142와 프로젝트 JP BIOS 사용.
이 기록은 두 재삽입 경로의 실행 확인이며 전체 게임 회귀 통과가 아니다.

## 시험 이미지와 경로

초기 `work/build/dg-qa/dg-dev.iso`(`c6e08024…5a81cd4`)를 콜드 부팅하고 이름 입력,
도입부, 마을 자유 이동까지 정상 입력으로 진행했다. `0042e0`의 수정 바이트가
MAPHEAD RAM에 로드됐으나 원래 QA 두 문장의 자연 도달 경로는 확인하지 못했다.
상점 개방 조건은 [공략](https://gamefaqs.gamespot.com/ps/913684-digimon-world/faqs/8333)을
탐색 단서로만 확인했으며 이 일본어 리비전의 실행 증거로 채택하지 않았다.

반복 가능한 도입부·씨앗몬 대사를 실제로 확인한 후 별도 합성 QA를 만들었다.
승인된 번역 수정이 아니다. `dg_export.py`로 `dg-text-0059c0`, `dg-text-064958`을
내보내 첫 문장의 `「내`를 `「가`, 둘째의 `「아`를 `「가`로 한 번씩 바꾸고 빌드했다.

```sh
python3 tools/dg_export.py --id dg-text-0059c0 --id dg-text-064958 --output work/dg/runtime-edits.json
# 위 두 글자만 편집. 제어 코드와 길이는 유지.
python3 tools/dg_build.py --edits work/dg/runtime-edits.json --output work/build/dg-runtime-qa --alignment-repair
```

산출물 SHA-256: `e324d7d642827f21403a0aff4b9f1f2ea0f2c6c8f97038ecb3681199f88db91b`.
변경 sector는 LBA 142273, 142463, 142610, 148103이다. raw sector offset은 각각
334626096, 335072976, 335418720, 348338256이며 파일 offset과 구분한다.
빌드의 전체 이미지 diff·파일시스템 불변·재추출·EDC/ECC 검사도 통과했다.

## 관찰 결과

| 대상 | 논리 payload offset | RAM payload | 소비 후 RAM 포인터 | 결과 |
| --- | --- | --- | --- | --- |
| `0059c0`, script 0 | DG `0x59C2`, MAPHEAD `0x51C2` | `0x8015E946` | `0x8015E9B8` | 수정 글자·줄바꿈 표시, 다음 질문 진행 |
| `064958`, script 149 | DG `0x6495A` | `0x801620DE` | `0x80162106` | 수정 글자 표시, 다음 설명 및 자유 이동 복귀 |

첫 경로는 새 이미지 콜드 부팅 → 새 게임 → 메모리카드를 사용하지 않음 → 첫 할배몬
대사다. MAPHEAD 23,094 bytes 전체가 디스크와 RAM에서 일치했다.

둘째 경로는 기존 QA에서 만든 `town-square-before.mcs`(script 148)를 재사용했다.
두 이미지의 EXE·SHOP_REL은 byte-identical이고 파일·VM 구조는 동일하다.
북쪽 마을로 정상 이동해 script 149를 새 디스크에서 다시 로드하고, 고기밭 북쪽의
씨앗몬에게 circle로 말을 걸었다. 로드 후 DG `[0x64000,0x65800)` 6,144 bytes 전체가
RAM `0x80161784`부터 일치했다. 따라서 예전 상태에 남은 대사의 표시를 새 재삽입 증거로
오인하지 않았다. 이 상태의 MAPHEAD는 이전 이미지 값이므로 첫 경로 증거에 사용하지 않는다.
직접 RAM 쓰기·코드 패치·강제 함수 호출은 하지 않았다.

수정 glyph의 읽기 PC `0x800F4434`, `0x800F4B80`과 script PC 저장소
`0x8013E144`에 대한 writer `0x800F4ABC`를 브레이크포인트 이벤트로 기록했다.
두 writer 값이 위 종료 포인터와 정확히 일치하며 이벤트 drop은 0이다.
bulk load의 RAM write breakpoint는 이벤트를 반환하지 않았다. 이를 미로드로 해석하지
않고 로드 전후 바이트 및 전체 버퍼 비교를 근거로 사용했다.

증거 디렉터리: `work/runtime/dg-verification/`.

- `verification.json`: 이미지·경로·범위·증거 해시.
- `maphead-edited.png`, `maphead-next.png`, `maphead-events.json`, `maphead-edited.mcs`.
- `dg149-edited.png`, `dg149-next.png`, `dg149-events.json`, `dg149-edited.mcs`.
- `dg149-reward.png`, `dg149-free-movement.png`, `dg149-finished.mcs`.
- 각 장면의 동명 디렉터리에 RAM/GPU/SPU와 레지스터 덤프.

## 미해결로 남긴 실제 번역 문제

고기 3개 획득 안내 `dg-text-064c22`가 `출꺼３곧쉘괜춰깝경!`로 표시됐다.
DG payload `0x64C24`, RAM `0x801623A8`이며 일본어는 `肉を３つ手に入れた！`다.
종료쌍 포함 28 bytes가 일본어 원본·한국어 원본·두 QA 이미지에서 완전히 같다.
한국어 글꼴로 치환된 코드에 일본어 원문 바이트가 남은 미번역 사례다.

이전 QA 이미지를 다시 실행하고 그 이미지에서 만든 `meat-before-talk.mcs`를 로드해
첫 대사부터 circle 입력으로 같은 보상 안내를 재현했다. `reward-control.png`,
`reward-control-events.json`, `reward-control.mcs`에 대조 증거를 남겼다.
이번 두 글자 재삽입이 만든 손상이 아니다. 자연스러운 번역·제어 위치·길이 변경 검토는
별도 미해결 작업이며 짧은 어휘로 억지로 맞춰 수정하지 않았다.

원래 QA 두 대사의 화면, 나머지 native 호출 경로, 전체 게임, 메모리카드 저장/재로드,
폰트 확장·조합형 입력은 이번 통과 범위에 포함하지 않는다.
사용자가 검증이 충분하다고 요청한 시점에 추가 실행을 중단했다.
