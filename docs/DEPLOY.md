# Google Cloud Run에 데모 배포하기

데모는 컨테이너 하나(UI + API)이고 유료 API를 호출하지 않습니다([README의 Public demo](../README.md)). 사용이 없으면 인스턴스가 0으로
내려가고, 접속하면 다시 뜹니다.

> **검증 상태:** 아래 명령으로 2026-11-16에 실제 배포해 확인했습니다. 프로젝트 `shorts-studio-demo`, 서울 리전,
> 주소 `https://shorts-studio-demo-280103166969.asia-northeast3.run.app`. 브라우저 테스트 8개가 배포본에서 통과했습니다.
> 첫 배포에서는 API가 뜨기 전에 웹 포트가 열려 첫 요청들이 500을 받았습니다. `docker/entrypoint.sh`가 API 응답을 기다린 뒤 웹 포트를
> 열도록 고쳐 재배포했고(revision 00002) 해결됐습니다.

## 0. 준비 (직접)
1. Google 계정으로 [Cloud Console](https://console.cloud.google.com)에 들어가 **프로젝트를 만들고 결제 계정(카드)을 연결**합니다.
   무료 사용량은 있지만 결제 계정 없이는 Cloud Run을 쓸 수 없습니다.
2. **예산 알림부터 만드세요.** 콘솔의 Billing → Budgets & alerts에서 월 예산(예: 5달러)을 만들고 50%·100%에 메일이 오게 합니다.
3. [gcloud CLI](https://cloud.google.com/sdk/docs/install)를 설치하고 로그인합니다.
   ```bash
   gcloud auth login
   gcloud config set project <프로젝트 ID>
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
   ```

## 1. 배포
저장소 폴더에서 실행합니다. `--source .`는 Cloud Build가 `Dockerfile`로 이미지를 빌드해 올리고 바로 배포합니다.
```bash
gcloud run deploy shorts-studio-demo \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --port 3000 \
  --memory 512Mi --cpu 1 \
  --min-instances 0 --max-instances 1 \
  --concurrency 40 --timeout 60 \
  --set-env-vars SHORTS_PROXY_HOPS=1
```
- `--allow-unauthenticated`는 **누구나 접속**하게 만드는 설정입니다. 데모는 키가 없고 읽기 전용이라 의도한 것입니다.
- `--max-instances 1`이 비용의 상한을 걸어 줍니다(동시에 하나만 뜸). 방문자가 몰려도 요금이 무한히 늘지 않습니다.
- 메모리 512Mi면 충분합니다(실측 약 130MiB).
- 리전 `asia-northeast3`은 서울이라 한국 방문자에게 가깝습니다. 무료 사용량 기준은 리전 등급마다 달라서(서울은 도쿄보다 한 등급 낮은 무료량일 수
  있음) [가격표](https://cloud.google.com/run/pricing)를 확인하세요.
- 끝나면 `https://shorts-studio-demo-…run.app` 주소가 출력됩니다.

## 2. 확인
```bash
curl -s https://<서비스 주소>/api/settings        # "demo":true 가 보여야 합니다
```
```bash
cd frontend && DEMO_URL=https://<서비스 주소> npm run test:e2e:demo     # 같은 브라우저 테스트 8개를 배포본에 실행
```

## 3. 방문자 구분(요청 제한) 확인 — 한 번만
데모는 방문자마다 분당 요청 횟수를 제한합니다. Cloud Run이 `X-Forwarded-For`에 방문자 주소를 **어느 위치에** 넣는지 공식 문서로 확인하지
못해, 기본값(`SHORTS_PROXY_HOPS=1`, 오른쪽 끝 항목)이 맞는지 배포 후 확인해야 합니다. 틀려도 **전체 상한**(방문자 합계 분당 600회)이
총량을 막아 주지만, 맞아야 방문자 한 명이 다른 방문자를 막지 않습니다.
1. 집 와이파이에서 변경 요청을 35번 보냅니다(31번째부터 429가 나와야 정상).
   ```bash
   for i in $(seq 1 35); do curl -s -o /dev/null -w "%{http_code} " -X POST -d x https://<서비스 주소>/api/projects/convenience-store/face-check; done; echo
   ```
2. **바로 이어서 휴대폰 데이터(다른 네트워크)로** 같은 방문자 수 호출을 한 번 보냅니다. 200이 나오면 방문자가 구분되는 것입니다. 429가 나오면 모든
   방문자가 한 사람으로 취급되는 것이니 `SHORTS_PROXY_HOPS`를 `2`로 바꿔 다시 배포하고 반복하세요.
   ```bash
   gcloud run services update shorts-studio-demo --region asia-northeast3 --update-env-vars SHORTS_PROXY_HOPS=2
   ```

## 4. 비용과 관리
| 하고 싶은 일 | 명령 |
|---|---|
| 접속을 잠시 막기 | `gcloud run services update shorts-studio-demo --region asia-northeast3 --no-allow-unauthenticated` |
| 다시 열기 | `gcloud run services update shorts-studio-demo --region asia-northeast3 --allow-unauthenticated` |
| 코드를 고친 뒤 갱신 | 1번의 `gcloud run deploy …`를 다시 실행 |
| 완전히 지우기 | `gcloud run services delete shorts-studio-demo --region asia-northeast3` |
- 빌드가 만든 이미지는 Artifact Registry에 쌓입니다(콘솔 Artifact Registry에서 오래된 것을 지우세요). 저장 용량이 늘면 소액이 청구될 수 있습니다.
- 요금이 걱정되면 서비스를 지우거나 위처럼 접속을 막으면 됩니다. 인스턴스가 0이면 CPU·메모리 요금은 나오지 않습니다.

## 4-1. 예산을 넘으면 자동으로 접속 차단
월 예산 알림은 메일만 보냅니다. 예산에 도달하면 **공개 접속을 자동으로 닫는** 장치를 `infra/budget_cutoff/`에 두었습니다.
예산 → Pub/Sub 주제 `budget-alerts` → Cloud Run 함수 `budget-cutoff`가 서비스의 `allUsers` 호출 권한만 뺍니다(서비스는 지우지 않습니다).
- 함수의 계정 `budget-cutoff@<프로젝트>`는 **데모 서비스 하나에 대한 run.admin**과 함수 호출·이벤트 수신 권한만 갖습니다.
- 예산 알림은 **즉시가 아닙니다.** 결제 데이터가 몇 시간 늦게 반영될 수 있어 7,000원을 조금 넘은 뒤에 막힐 수 있습니다.
- 다시 열기: `gcloud run services update shorts-studio-demo --region asia-northeast3 --allow-unauthenticated`
- 판정 로직은 `tests/test_budget_cutoff.py`로 검증합니다(예산 이내·도달·깨진 메시지).

## 5. 나중에 (선택)
- **내 도메인:** Cloud Run의 도메인 매핑이나 Cloudflare 같은 DNS/CDN을 앞에 둘 수 있습니다. 그 경우 `X-Forwarded-For`에 항목이 더 붙으므로
  `SHORTS_PROXY_HOPS`를 다시 맞추고 3번을 반복하세요.
- **공개 전 확인:** 데모의 Gemini 이미지와 Azure 음성의 공개 약관, 그리고 GitHub 이메일 비공개 설정([README](../README.md) 참고).
