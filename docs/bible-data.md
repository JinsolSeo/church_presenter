# 성경 데이터

Church Presenter는 실행 중 HTML을 해석하지 않고 사용자가 선택한 정식 JSON을 한 번
읽어 메모리에서 조회합니다. 새번역 본문은 재배포 권한이 확인되지 않았으므로 Git에
포함하지 않으며 다음 로컬 개발 경로도 `.gitignore` 대상입니다.

`src/church_presenter/assets/bibles/new_korean_translation.json`

## 형식

- `schema_version`: 현재 `1`
- `document_type`: `church_presenter_bible`
- `translation`: 번역 ID, 표시 이름, 판본
- `books`: 66권의 고정 순서 목록
- `chapters`: 각 권 안의 장 목록
- `verses`: 절 번호와 본문

원본 전자책에서 두 절 이상이 한 문단으로 합쳐져 분리할 수 없는 여섯 곳은
`number`와 `end_number`로 범위를 보존합니다. 예를 들어 예레미야 17장 2–3절은
하나의 출력 단위입니다. 본문 자체에서 번호가 생략되었다고 명시한 사도행전 24장
7절은 임의로 만들거나 뒤 절 번호를 바꾸지 않습니다.

## 다시 생성하기

사용자가 제공한 Logos 파생 HTML에서 다음 명령으로 동일한 JSON을 생성합니다.

```bash
PYTHONPATH=src python scripts/convert_bible_html.py SOURCE.html \
  src/church_presenter/assets/bibles/new_korean_translation.json
```

변환기는 화면용으로 생성된 `window._books`를 사용하지 않습니다. 실제 HTML DOM의
본문과 연속 문단을 읽고, 구절 제목과 아가의 화자 표시는 제외합니다. 제공된 HTML에
있던 네 개의 잘못된 책 경계는 입력 구조의 정확한 시그니처가 일치할 때만 명시적으로
복구합니다. 구조가 달라지면 잘못된 JSON을 조용히 만들지 않고 변환을 중단합니다.

## 배포 권리

성경 본문은 애플리케이션 코드의 MIT 라이선스와 별개의 자료입니다. 이 저장소를
공개 배포하거나 재배포할 때에는 성경전서 새번역 전자책 본문에 필요한 이용·배포
권한을 저장소 관리자가 확인해야 합니다.
