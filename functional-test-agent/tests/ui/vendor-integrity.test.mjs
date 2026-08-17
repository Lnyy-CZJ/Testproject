import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const files = {
  "LICENSE": "15cf4aa2e70503ff347700ddd4b19b160dfc1341e33f7a20bb6c34a31b623de0",
  "MindElixir.css": "ed62501332e99a742736e996ddde798f260468f5fde66e569b700ed1a24930fd",
  "MindElixir.iife.js": "e2365d57cc727eab1c30a077886c4940deccb10a447c439ddbfbde4e7795c285",
};

test("Mind Elixir 5.14.0 本地文件保持固定哈希", async () => {
  for (const [name, expected] of Object.entries(files)) {
    const content = await readFile(new URL(`../../services/common/static/vendor/mind-elixir/5.14.0/${name}`, import.meta.url));
    assert.equal(createHash("sha256").update(content).digest("hex"), expected, name);
  }
});
