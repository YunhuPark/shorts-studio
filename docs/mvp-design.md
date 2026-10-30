# AI 쇼츠 제작 서비스 MVP 설계

작성일 2026-10-29. 지금까지 만든 프로토타입(대본 JSON → Gemini 이미지 → Azure 음성 → ffmpeg/Pillow 렌더)을 다중 사용자 웹 서비스로 옮기는 설계다. 비용·라이선스 수치는 `open-source-decisions.md`와 앞서 확인한 공식 페이지(2026-10-29 기준)를 따르며, "미확인"은 구현 전에 확인해야 한다.

## 1. 범위

**MVP에 넣는 것**
1. 주제를 입력하면 대본과 컷 구성(스토리보드) 생성
2. **스토리보드 검토 화면**: 대사 수정, 컷 삭제·순서 변경, 컷별 이미지 다시 생성
3. 등장인물 외형 고정(기준 이미지) + 컷 이미지 생성
4. 목소리 선택(후보 샘플 듣기) + 대사 음성 생성
5. 렌더(카메라 이동, 색보정, 자막, 배경음악, 효과음) → 미리보기 → mp4 다운로드
6. 회원가입/로그인, 크레딧 구매와 차감
7. AI 생성물 표시(영상 안 표식 + 메타데이터)와 YouTube 공개 표시 안내
8. 비용 상한, 이용 제한, 입력 검수

**MVP에서 빼는 것**: 인물이 실제로 움직이는 영상(이미지→영상), 자체 음성 모델 운영, 업로드 자동화, 목소리 복제, 팀 기능, 모바일 앱.

## 2. 사용자 흐름
```
주제 입력 ─► 스토리보드 생성 ─► [검토·수정] ─► 생성(이미지·음성) ─► [컷별 다시 생성] ─► 렌더 ─► 미리보기 ─► 다운로드
              (크레딧 예약)       무료 수정         진행률 표시          추가 크레딧           (크레딧 확정)
```
사람이 개입하는 지점을 4곳 둔다(스토리보드, 목소리, 컷 재생성, 최종 미리보기). 프로토타입에서 문제(로고 노출, 얼굴 변화, 자막 끊김, 목소리 이질감)를 모두 사람이 발견했기 때문이다.

## 3. 시스템 구성
```
[브라우저: Next.js]
      │  REST + 진행 상황 구독
      ▼
[API: FastAPI]──────────────► [Supabase: Auth · Postgres · Storage]
      │ 잡 생성                          ▲
      ▼                                 │ 읽기/쓰기
[작업 테이블(Postgres)] ◄──── [워커 프로세스 N개]
                                   ├─ plan_script  → LLM
                                   ├─ gen_image    → ImageProvider (Gemini API 등)
                                   ├─ gen_voice    → VoiceProvider (Azure / ElevenLabs)
                                   ├─ render       → ffmpeg + Pillow (현 build_v2.py 이식)
                                   └─ qa           → 규칙 검사 + (선택) 비전 모델 검사
[결제: Toss Payments] ──► 웹훅 ──► API ──► 크레딧 원장
```
- 렌더는 CPU 작업이다. 이 PC에서 21컷에 약 5분이 걸렸으니, 워커 한 대당 동시 1~2작업으로 시작한다.
- 이미지와 음성 호출은 네트워크 대기가 대부분이라 워커 수를 늘려 병렬화한다.

## 4. 부품 인터페이스 (교체 가능하게)
```python
class ImageProvider:   generate(prompt, refs: list[Asset], size) -> Asset
class VoiceProvider:   list_voices() ; synthesize(text, voice_id, params) -> Asset ; preview(voice_id)
class ScriptProvider:  plan(brief, character_bible) -> Storyboard
class Renderer:        render(storyboard, assets, options) -> Asset
```
- 프로토타입 대응: `cuts_v2.json` = Storyboard, `build_v2.py` = Renderer, `tts()` = VoiceProvider(Azure), Gemini 앱 자동화 = **서비스에서는 제거하고 ImageProvider(API)로 대체**.
- 인물 일관성은 "첫 기준 이미지를 모든 후속 요청에 참조로 넘기는" 방식으로 처리한다. 프로토타입에서 같은 대화에서 이전 이미지를 참조하자 얼굴이 맞았다. **Phase 0에서 시험해 확인했다**(아래 "Phase 0 결과"): 기준 이미지를 요청에 첨부하면 얼굴, 안경, 모자, 옷이 컷을 건너 유지된다.

## 5. 잡 상태와 흐름
- 프로젝트 상태: `draft → planning → storyboard_ready → generating → generated → rendering → review → done | failed`
- 잡 종류: `plan_script`, `gen_image(shot)`, `gen_voice(shot)`, `render`, `qa`
- 의존성: `render`는 모든 컷의 이미지와 음성이 `ready`일 때만 시작. 컷 재생성은 해당 컷의 `gen_*`만 다시 돌리고 `render`를 재실행.
- 재시도: 외부 호출은 최대 2회, 실패하면 크레딧 환불과 사용자 알림. 같은 입력의 음성은 해시로 캐시(프로토타입의 TTS 캐시와 동일).

## 6. 데이터 모델 (핵심 테이블)
| 테이블 | 주요 열 |
|---|---|
| users | id, email, plan, created_at (Supabase Auth 연동) |
| projects | id, user_id, brief, state, aspect, created_at |
| storyboards | id, project_id, version, character_bible(json), style(json) |
| shots | id, storyboard_id, n, text, who, camera, highlight(json), scene_prompt, image_asset_id, voice_asset_id, status |
| voices | id, provider, voice_id, params(json), label |
| assets | id, kind(image/voice/video/music), storage_key, sha256, bytes, provider, created_at |
| jobs | id, project_id, type, state, attempts, est_cost_cents, actual_cost_cents, error |
| credit_ledger | id, user_id, delta, reason, job_id, created_at |
| renders | id, project_id, asset_id, duration, ai_label(json), created_at |

## 7. API (요약)
- `POST /projects` 주제로 생성 → 스토리보드 잡 시작
- `GET /projects/{id}` 상태, 스토리보드, 컷 목록
- `PATCH /shots/{id}` 대사·카메라·강조어 수정 (무료)
- `POST /shots/{id}/regenerate` 이미지 또는 음성 재생성 (크레딧)
- `GET /voices`, `POST /voices/{id}/preview`
- `POST /projects/{id}/render`
- `GET /projects/{id}/download` (서명된 임시 링크)
- `POST /billing/toss/confirm`, 웹훅 수신
- 진행 상황은 `GET /projects/{id}/events`(서버 전송 이벤트) 또는 짧은 폴링으로 시작.

## 8. 크레딧과 비용 가드
- 크레딧은 **예약 → 확정/환불** 방식이다. 프로젝트 시작 시 예상 비용(컷 수 × 이미지 단가 + 음성 글자 수 + 재시도 여유)만큼 예약하고, 완료 후 실제 비용으로 확정하며 차액은 환불.
- 앞서 확인한 단가(이미지 1K: $0.0336~$0.134, 영상 1편당 변동비 대략 $1.5~$5.5)를 설정 파일로 두고, 가격은 설정값으로 바꿀 수 있게 한다.
- 안전장치: 프로젝트당 이미지 호출 상한(예: 컷 수의 2배), 사용자당 일일 한도, 월 예산 초과 시 신규 작업 중단 스위치.
- 무료 체험은 Gemini API 이미지에 무료 티어가 없으므로 **1편, 워터마크, 낮은 컷 수**로 제한해 원가를 통제한다.

## 9. 검수, 안전, 법적 기능
- **AI 표시:** 인공지능기본법은 생성형 AI 서비스 사업자에게 표시 의무를 둔다(보도 기준, 과태료 유예 중). 영상 끝 또는 모서리의 "AI 생성" 표식 옵션과 mp4 메타데이터를 기본으로 켠다. 세부 기준은 과기정통부 가이드라인 원문 확인 필요.
- **YouTube:** 사실적 합성 콘텐츠는 공개 표시가 필요하다고 안내한다. 같은 틀의 대량 영상은 수익 창출이 제한될 수 있다고 보도되었으니(2차 자료) 사용자에게 고지하고 다양성 입력을 유도한다.
- **입력 검수:** 실존 인물, 아동 대상 부적절 콘텐츠, 폭력·혐오 등은 스토리보드 생성 전에 분류해 차단한다. 실존 인물 목소리 복제는 MVP에서 제공하지 않는다.
- **이미지 검수:** 상표·로고가 읽히는지 비전 모델로 검사해 경고(컷 1의 실제 편의점 로고 같은 경우). 기계적 검사는 보조이고 최종 확인은 사용자 미리보기다.
- **자막 규칙 검사:** 끝 마침표 금지, 숫자+단위 분리 금지 같은 규칙은 프로토타입의 `split_phrases`를 그대로 이식해 결정적으로 처리.
- **개인정보와 약관:** 이용약관, 개인정보처리방침, 생성물 권리 귀속, 환불 정책 필요. 법률 검토는 별도.

## 10. 프로토타입 → 서비스 전환 작업표
| 현재 | 서비스에서 | 비고 |
|---|---|---|
| Gemini 앱 브라우저 자동화 | ImageProvider(공식 API) | 약관 위반 위험과 한도 때문에 서비스에서 사용 금지 |
| `C:\Windows\Fonts\malgunbd.ttf` | Pretendard 또는 Noto Sans KR 번들 | 시스템 폰트 재배포 곤란 |
| `Downloads\shorts_v2\cutNN.png` 경로 | 저장소 asset 키 | 경로 하드코딩 제거 |
| 환경변수의 Azure 키 | 서버 시크릿 관리 | 사용자 키는 서버에서만 사용 |
| `imageio-ffmpeg` 번들 바이너리 | 서버에 ffmpeg 설치 | GPL 빌드 여부와 배포 여부 확인 |
| 직접 작곡한 배경음악 | 그대로 사용(제3자 저작권 없음) | 음악 스타일 몇 종 추가 가능 |
| `cuts_v2.json` | `storyboards`/`shots` 테이블 | 스키마는 거의 그대로 |

## 11. 단계 (대략, 인력과 우선순위에 따라 변동)
- **Phase 0 — 핵심 검증:** 프로토타입을 라이브러리+CLI로 정리하고 Provider 인터페이스 도입. **이미지 API의 참조 이미지 일관성**, 서버 렌더 시간, 폰트 교체를 검증.
- **Phase 1 — 서비스 뼈대:** Supabase, API, 작업 테이블 워커, 스토리보드 검토 화면.
- **Phase 2 — 결제와 안전:** 토스페이먼츠, 크레딧 원장, AI 표시, 입력 검수, 이용 한도.
- **Phase 3 — 비공개 베타:** 소수 사용자로 원가·품질·이탈 확인.
- **Phase 4 — 확장:** 실제 움직임 영상(이미지→영상), 자체 음성 모델 평가, 업로드 자동화.

## 12. 열려 있는 결정
1. 대상 사용자와 장르: 지금 파이프라인은 대사 중심 스토리형에 맞춰져 있다. 정보형이나 광고형까지 갈지.
2. 가격: 편당 원가의 몇 배로 팔지, 구독인지 크레딧 팩인지.
3. 목소리 공급자: Azure만으로 갈지 ElevenLabs를 서비스에 쓸 수 있는지(약관·계약 확인).
4. 이미지 공급자: Gemini API만 쓸지, 대체 모델 병행(가격과 일관성 비교 필요).
5. 사업자 등록과 결제 연동 준비.

## Phase 0 결과 (2026-10-30)

**이미지 API 참조 일관성 시험** — `shorts-studio image-consistency`, 모델 `gemini-3.1-flash-image`(Nano Banana 2), 4회 호출
(기준 초상 1 + 컷 5, 16, 21), 비교 시트는 사람이 눈으로 판정.
- 기준 이미지를 같은 요청에 첨부하자 **얼굴 인상, 철테 안경, 회색 플랫캡, 갈색 카디건, 흰 티셔츠가 세 컷 모두 유지됐다.**
  클로즈업(컷 16)이 기준과 가장 비슷했고, 전체샷(컷 5)과 옆모습(컷 21)도 같은 인물로 보였다.
- 해상도는 768×1376으로 Gemini 앱 결과(572×1024)보다 높아, 1080×1920으로 확대할 때 유리하다.
- 한계: 판정은 육안이며 객관 지표(얼굴 임베딩 유사도)는 아직 없다. 인물 둘이 한 화면에 나오는 컷, 극단적 각도,
  컷 수가 많을 때의 누적 변화는 시험하지 않았다. 표본이 3컷뿐이라 일관성이 항상 유지된다고 단정할 수 없다.
- 비용: 요금표 기준 1K 이미지 $0.067 × 4 ≈ $0.27로 추정. 실제 청구액은 확인하지 못했다.
- **요금표 요약의 모델명은 틀렸다.** 요금 페이지 요약에 나온 `gemini-nano-banana-2.1`은 실제 모델 목록에 없다.
  서비스 구현 시 모델 ID와 단가는 `models.list`와 공식 요금 페이지에서 직접 확인한다(요약 도구 결과를 신뢰하지 않는다).
  현재 목록의 이미지 모델: gemini-2.5-flash-image, gemini-3-pro-image, gemini-3.1-flash-image, gemini-3.1-flash-lite-image (및 preview 변형).

**결론:** 참조 이미지 방식은 서비스의 인물 일관성 전략으로 채택 가능하다. 다음 검증은 (1) 두 인물 컷, (2) 20컷 이상 연속 생성,
(3) 얼굴 유사도 자동 측정이다.

## Phase 1a 결과: 로컬 대시보드 (2026-10-30)

FastAPI(`src/shorts_studio/api/`) + Next.js 16(`frontend/`)로 혼자 쓰는 대시보드를 만들었다. 로그인·결제·다중 사용자는 아직 없다.
- **화면:** 프로젝트 목록, 스토리보드 편집(컷 카드: 대사·화자·카메라·강조어·이미지 설명, 자막 미리보기, 이미지 확대),
  목소리 선택(샘플 듣기), 이미지 재생성(비용 확인), 렌더(진행률, 미리보기, 다운로드).
- **검증:** 백엔드 테스트 26개(전체 68개) 통과. 실제 브라우저에서 편집→저장(파일 반영과 .bak), 비용 확인 취소, 목소리 샘플 재생,
  이미지 확대, 렌더 전 과정(26컷, 90.9초)을 확인했다. 화면에서 시작한 렌더는 CLI 렌더와 샘플 프레임 픽셀 차이 0.0000.
- **안전장치:** 키는 API 프로세스 환경변수에서만 읽고 화면에는 참/거짓만 전달, Host 헤더를 localhost로 제한(DNS 리바인딩 방지),
  JSON 요청만 허용(교차 사이트 폼 전송 차단), 비용 발생 작업은 명시적 확인 + 일일 추정 한도, 요청 시점에 비용 예약·실패 시
  환불·같은 컷 중복 요청 차단, 프로젝트 ID와 파일 이름 검증.
- **미검증/한계:** 화면에서 실제 이미지 재생성(유료)은 가짜 공급자로만 테스트했다. 모바일 폭 레이아웃과 보이는 창에서의 성능은
  눈으로 확인하지 않았다. 작업 큐는 프로세스 내 스레드라 서버를 재시작하면 진행 중 작업이 사라진다. 다중 사용자 단계에서는
  DB 기반 큐와 인증이 필요하다.
