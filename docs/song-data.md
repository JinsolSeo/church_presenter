# 곡 JSON 형식

찬양 탭은 한 곡을 하나의 UTF-8 JSON 파일로 관리합니다. 저장소의
[`sample_assets/songs`](../sample_assets/songs) 폴더에 실행 가능한 예시 4곡이 있습니다.

```json
{
  "schema_version": 1,
  "document_type": "church_presenter_song",
  "title": "은혜의 아침",
  "sections": [
    {
      "id": "verse_1",
      "type": "verse",
      "label": "Verse 1",
      "lines": ["첫째 줄", "둘째 줄"]
    },
    {
      "id": "chorus",
      "type": "chorus",
      "label": "Chorus",
      "lines": ["후렴 첫째 줄", "후렴 둘째 줄"]
    },
    {
      "id": "bridge",
      "type": "bridge",
      "label": "Bridge",
      "lines": ["브리지 첫째 줄", "브리지 둘째 줄"]
    }
  ],
  "default_sequence": ["verse_1", "chorus", "bridge", "chorus"]
}
```

## 필드 규칙

- `title`: UI에 표시할 곡 제목이자 기본 곡 식별자입니다. `곡 만들기`로 저장하면
  파일 이름도 `{title}.json`이 됩니다.
- `id`: 기존 외부 곡 파일과의 호환을 위한 선택 필드입니다. 생략하면 `title`을 곡
  식별자로 사용합니다.
- `artist`: 기존 외부 곡 파일에서 사용할 수 있는 선택 필드입니다. `곡 만들기`에서는
  입력하거나 저장하지 않습니다.
- `sections`: 한 번만 정의하는 가사 섹션 목록입니다.
- 섹션 `type`: `verse`, `chorus`, `bridge` 중 하나입니다.
- 섹션 `id`: 한 곡 안에서 유일해야 합니다. Verse가 여러 개면 `verse_1`, `verse_2`처럼
  구분합니다.
- `lines`: 한 항목이 자막 원본 한 줄입니다. 빈 줄은 허용하지 않습니다.
- `default_sequence`: UI에서 모든 섹션을 선택하고 `추가`할 때 사용할 섹션 ID
  순서입니다. `곡 만들기`에서는 화면의 섹션 순서로 자동 생성됩니다. 외부에서 JSON을
  작성할 때는 같은 Chorus ID를 여러 번 넣어 반복을 표현할 수도 있습니다.

찬양 콘티 JSON은 이 곡 파일을 참조할 뿐 가사를 복사하지 않습니다. 따라서 콘티를 다른
컴퓨터로 옮길 때는 참조된 곡 JSON도 상대 폴더 구조와 함께 복사해야 합니다.
