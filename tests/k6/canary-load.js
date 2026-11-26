import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 15 },
    { duration: "25s", target: 30 },
    { duration: "10s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<500"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://order.macprod.internal";
const HOST_HDR = __ENV.HOST_HEADER || "order.macprod.internal";

export default function () {
  const params = {
    headers: {
      Host: HOST_HDR,
      "Content-Type": "application/json",
    },
  };
  const r1 = http.get(`${BASE_URL}/api/v1/orders`, params);
  check(r1, {
    "GET /orders 200": (r) => r.status === 200,
  });

  if (Math.random() < 0.25) {
    const r2 = http.post(
      `${BASE_URL}/api/v1/orders`,
      JSON.stringify({ item: "k6-item", quantity: 1 }),
      params
    );
    check(r2, {
      "POST /orders 201": (r) => r.status === 201,
    });
  }
  sleep(0.2);
}
