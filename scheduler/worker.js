// GitHub Actions 예약 대행 (Cloudflare Worker, 2026-09-01)
//
// 왜 필요한가: GitHub 의 schedule 이 이 저장소에서 신뢰할 수 없다.
// 매시 예약인데 8/27~9/1 닷새간 하루 1~6회만 떴고, 발동 분도 제멋대로였다.
// 공식 문서가 "부하가 높으면 대기 작업 일부가 버려질 수 있다"고 인정한 동작이다.
// 반면 workflow_dispatch 는 언제나 즉시 실행된다 → 밖에서 정확한 시각에 깨운다.
//
// 필요한 비밀값 (Worker Settings > Variables and Secrets):
//   GH_TOKEN  — 세분화 PAT. futurist38/nwp-verify 한 곳, Actions = Read and write 만.
//   TEST_KEY  — (선택) 브라우저로 수동 시험할 때 쓸 임의 문자열. 없으면 시험 경로 비활성.
//
// 만료 주의: PAT 는 최대 1년. 만료되면 이 Worker 는 계속 돌지만 GitHub 가 401 로 거절해
// 사이트가 조용히 멈춘다. 갱신일은 구글 캘린더에 등록해 두었다.

const REPO = "futurist38/nwp-verify";

// cron 식 → 깨울 워크플로. wrangler.toml 의 crons 와 문자열이 정확히 같아야 한다.
const JOBS = {
  "25 * * * *": "obs-hourly.yml", // 매시 :25 — ASOS 는 정시 +2분이 보통, 드물게 +42분
  "10 21 * * *": "daily.yml",     // 06:10 KST (전일 12z 런)
  "40 1 * * *": "daily.yml",      // 10:40 KST (당일 00z 런)
};

async function dispatch(wf, env) {
  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${wf}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nwp-verify-scheduler",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    },
  );
  // 204 가 정상. 401 = 토큰 만료/오타, 403 = 권한 부족(Actions 쓰기 확인), 404 = 저장소·파일명.
  const detail = res.status === 204 ? "" : ` ${await res.text()}`;
  console.log(`[dispatch] ${wf} -> ${res.status}${detail}`);
  return res.status;
}

export default {
  async scheduled(event, env, ctx) {
    const wf = JOBS[event.cron];
    if (!wf) return console.log(`[skip] 등록되지 않은 cron: ${event.cron}`);
    ctx.waitUntil(dispatch(wf, env));
  },

  async fetch(req, env) {
    const key = new URL(req.url).searchParams.get("key");
    const wf = new URL(req.url).searchParams.get("wf");
    // 시험 경로는 TEST_KEY 를 설정한 경우에만 열린다 (열어두면 그 자체가 남용 통로)
    if (!wf || !env.TEST_KEY || key !== env.TEST_KEY) {
      return new Response("nwp-verify scheduler alive\n");
    }
    if (!Object.values(JOBS).includes(wf)) {
      return new Response("unknown workflow\n", { status: 400 });
    }
    return new Response(`${wf} -> ${await dispatch(wf, env)}\n`);
  },
};
