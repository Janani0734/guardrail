import http from "k6/http";
import { check } from "k6";

const RUN = Date.now();

export const options = { vus: 20, duration: "60s" };

export default function () {
  const res = http.post(
    "http://localhost:8000/v1/actions/evaluate",
    JSON.stringify({
      agent_id: "support-agent-01",
      action_id: `act_${RUN}_${__VU}_${__ITER}`,
      tool: "read_logs",
      environment: "staging",
      arguments: { service: "api" },
      estimated_cost: 1,
    }),
    {
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "grk_demo_support_agent_01_local_only_0001",
      },
    }
  );
  check(res, { "status 200": (r) => r.status === 200 });
}
