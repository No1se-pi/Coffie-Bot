import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createIdempotencyKey } from "../api/client";

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
