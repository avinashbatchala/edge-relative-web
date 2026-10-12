import { test } from "node:test";
import assert from "node:assert/strict";
import { requestExport } from "./download.ts";

test("CSV uses a pinned run and encoded symbol and preserves blob bytes", async () => {
  let requested = "";
  const result = await requestExport("csv", "M&M", "run-1", async (url) => {
    requested = String(url);
    return new Response("\uFEFFsymbol,rrs\r\nM&M,1.2\r\n", {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="M_M-run-1.csv"',
      },
    });
  });
  assert.equal(requested, "/api/v1/exports/M%26M.csv?run_id=run-1");
  assert.equal(result.filename, "M_M-run-1.csv");
  assert.match(await result.blob.text(), /M&M,1.2/);
});
test("backend errors are surfaced rather than downloaded or navigating away", async () => {
  await assert.rejects(
    () =>
      requestExport(
        "csv",
        "TCS",
        "old",
        async () =>
          new Response(
            JSON.stringify({ detail: "Refresh the chart and retry" }),
            { status: 409, headers: { "Content-Type": "application/json" } },
          ),
      ),
    /Refresh the chart/,
  );
  await assert.rejects(
    () =>
      requestExport(
        "csv",
        "TCS",
        undefined,
        async () =>
          new Response(
            JSON.stringify({ error: { message: "Fetch history first" } }),
            { status: 404, headers: { "Content-Type": "application/json" } },
          ),
      ),
    /Fetch history first/,
  );
});
test("HTML and JSON success responses are rejected as invalid downloads", async () => {
  await assert.rejects(
    () =>
      requestExport(
        "csv",
        "TCS",
        undefined,
        async () =>
          new Response("<html>App</html>", {
            headers: { "Content-Type": "text/html" },
          }),
      ),
    /CSV/,
  );
});
test("run ZIP uses the complete-run endpoint and sanitizes the filename", async () => {
  let url = "";
  const result = await requestExport("zip", "TCS", "run-2", async (input) => {
    url = String(input);
    return new Response(new Uint8Array([80, 75, 3, 4]), {
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": 'attachment; filename="../../run.zip"',
      },
    });
  });
  assert.equal(url, "/api/v1/exports/run.zip?run_id=run-2");
  assert.equal(result.filename, "run.zip");
  assert.equal(result.blob.size, 4);
});

test("browser download clicks an attachment and releases its temporary resources", async () => {
  const { downloadExport } = await import("./download.ts");
  const originalFetch = globalThis.fetch;
  const documentDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    "document",
  );
  const windowDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    "window",
  );
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const events: string[] = [];
  const anchor = {
    href: "",
    download: "",
    hidden: false,
    click: () => events.push("click"),
    remove: () => events.push("remove"),
  };
  try {
    globalThis.fetch = async () =>
      new Response("symbol,rrs\nTCS,1\n", {
        headers: {
          "Content-Type": "text/csv",
          "Content-Disposition": 'attachment; filename="TCS.csv"',
        },
      });
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: {
        createElement: () => anchor,
        body: { append: () => events.push("append") },
      },
    });
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        setTimeout: (callback: () => void) => {
          events.push("defer");
          callback();
        },
      },
    });
    URL.createObjectURL = () => {
      events.push("create");
      return "blob:download";
    };
    URL.revokeObjectURL = (url) => {
      assert.equal(url, "blob:download");
      events.push("revoke");
    };
    assert.equal(await downloadExport("csv", "TCS", "run-1"), "TCS.csv");
    assert.equal(anchor.href, "blob:download");
    assert.equal(anchor.download, "TCS.csv");
    assert.deepEqual(events, [
      "create",
      "append",
      "click",
      "remove",
      "defer",
      "revoke",
    ]);
  } finally {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
    if (documentDescriptor)
      Object.defineProperty(globalThis, "document", documentDescriptor);
    else Reflect.deleteProperty(globalThis, "document");
    if (windowDescriptor)
      Object.defineProperty(globalThis, "window", windowDescriptor);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
