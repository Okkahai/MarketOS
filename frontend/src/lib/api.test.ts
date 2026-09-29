import { afterEach, describe, expect, it, vi } from "vitest";
import { getJson } from "./api";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

afterEach(() => vi.unstubAllEnvs());

describe("getJson", () => {
  it("returns data on 2xx", async () => {
    const result = await getJson<{ status: string }>("/health/live", {
      fetchImpl: async () => json(200, { status: "ok" }),
    });
    expect(result).toEqual({ ok: true, data: { status: "ok" }, httpStatus: 200 });
  });

  it("reads the body of an accepted non-2xx status such as readiness 503", async () => {
    const result = await getJson("/health/ready", {
      acceptStatuses: [503],
      fetchImpl: async () => json(503, { status: "degraded", checks: {} }),
    });
    expect(result.ok).toBe(true);
    expect(result.httpStatus).toBe(503);
  });

  it("reports other HTTP errors instead of returning data", async () => {
    const result = await getJson("/x", { fetchImpl: async () => json(500, { detail: "boom" }) });
    expect(result).toEqual({ ok: false, error: "API returned HTTP 500", httpStatus: 500 });
  });

  it("reports an unreachable API without inventing data", async () => {
    const result = await getJson("/x", {
      fetchImpl: async () => {
        throw new TypeError("fetch failed");
      },
    });
    expect(result).toEqual({ ok: false, error: "API unreachable (TypeError)", httpStatus: null });
  });

  it("uses API_INTERNAL_URL without a trailing slash", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000/");
    const seen: string[] = [];
    await getJson("/health/live", {
      fetchImpl: async (url) => {
        seen.push(url);
        return json(200, {});
      },
    });
    expect(seen).toEqual(["http://api:8000/health/live"]);
  });
});
