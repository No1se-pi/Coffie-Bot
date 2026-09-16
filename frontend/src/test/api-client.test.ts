import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createIdempotencyKey, requestAllPages } from "../api/client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createIdempotencyKey", () => {
  it("creates an RFC 4122 UUID with the browser cryptographic RNG", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0x11);
        return bytes;
      },
    } as Crypto);

    expect(createIdempotencyKey()).toBe("11111111-1111-4111-9111-111111111111");
  });

  it("fails closed when a secure random source is unavailable", () => {
    vi.stubGlobal("crypto", undefined);

    expect(() => createIdempotencyKey()).toThrow(ApiError);
    try {
      createIdempotencyKey();
    } catch (error) {
      expect(error).toMatchObject({
        code: "secure_random_unavailable",
        status: 0,
      });
    }
  });
});

describe("admin menu pagination", () => {
  it("loads every item page when the menu contains more than 100 positions", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/admin/menu/categories")) {
        return new Response(
          JSON.stringify({
            items: [{ id: "category-1" }],
            page: 1,
            page_size: 100,
            total: 1,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      const page = new URL(url, "https://example.test").searchParams.get(
        "page",
      );
      const items =
        page === "1"
          ? Array.from({ length: 100 }, (_, index) => ({ id: `item-${index}` }))
          : [{ id: "item-100" }];
      return new Response(
        JSON.stringify({
          items,
          page: Number(page),
          page_size: 100,
          total: 101,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await requestAllPages<{ id: string }>("/admin/menu/items");

    expect(result).toHaveLength(101);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
