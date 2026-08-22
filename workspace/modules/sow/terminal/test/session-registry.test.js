"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const { SessionRegistry } = require("../session/session-registry");

const reg = () => new SessionRegistry();

test("register requires a node binding (no naked sessions)", () => {
  assert.throws(() => reg().register("s1", {}), /no node binding/);
});

test("register then legal lifecycle SPAWNING -> RUNNING -> EXITED", () => {
  const r = reg();
  const s = r.register("s1", { nodeId: "n1", pid: 100 }, "t0");
  assert.strictEqual(s.state, "SPAWNING");
  r.transition("s1", "RUNNING", "t1");
  r.transition("s1", "EXITED", "t2", { exitCode: 0 });
  assert.strictEqual(r.get("s1").state, "EXITED");
  assert.ok(r.isTerminal("s1"));
});

test("duplicate register is refused", () => {
  const r = reg();
  r.register("s1", { nodeId: "n1" });
  assert.throws(() => r.register("s1", { nodeId: "n1" }), /duplicate session/);
});

test("illegal transition raises rather than silently correcting", () => {
  const r = reg();
  r.register("s1", { nodeId: "n1" });
  r.transition("s1", "RUNNING");
  r.transition("s1", "EXITED");
  assert.throws(() => r.transition("s1", "RUNNING"), /illegal transition EXITED -> RUNNING/);
});

test("REFUSED is reachable from SPAWNING and is terminal", () => {
  const r = reg();
  r.register("s1", { nodeId: "n1" });
  r.transition("s1", "REFUSED", null, { reason: "not admitted" });
  assert.strictEqual(r.get("s1").state, "REFUSED");
  assert.throws(() => r.transition("s1", "RUNNING"), /illegal transition/);
});

test("detach/reattach returns byte-exact scrollback, PTY state untouched", () => {
  const r = reg();
  r.register("s1", { nodeId: "n1" });
  r.transition("s1", "RUNNING");
  r.feed("s1", "line-1\n");
  r.feed("s1", Buffer.from("line-2\n"));
  assert.strictEqual(r.detach("s1"), "RUNNING");
  assert.strictEqual(r.get("s1").attached, false);
  const replay = r.reattach("s1");
  assert.strictEqual(replay.toString("utf8"), "line-1\nline-2\n");
  assert.strictEqual(r.get("s1").attached, true);
  assert.strictEqual(r.get("s1").state, "RUNNING"); // reattach never restarts the PTY
});

test("event log is append-only, ordered, and records every transition", () => {
  const r = reg();
  r.register("s1", { nodeId: "n1", pid: 5 }, "t0");
  r.transition("s1", "RUNNING", "t1");
  r.transition("s1", "KILLED", "t2");
  const log = r.eventLog();
  assert.deepStrictEqual(log.map((e) => e.seq), [0, 1, 2]);
  assert.deepStrictEqual(log.map((e) => e.to), ["SPAWNING", "RUNNING", "KILLED"]);
  // returned log is a copy: mutating it does not affect the registry's record
  log.push({ seq: 99 });
  assert.strictEqual(r.eventLog().length, 3);
});

test("alive() and teardownOrder() reflect only live sessions", () => {
  const r = reg();
  r.register("a", { nodeId: "n" }); r.transition("a", "RUNNING");
  r.register("b", { nodeId: "n" }); r.transition("b", "RUNNING"); r.transition("b", "EXITED");
  r.register("c", { nodeId: "n" }); // SPAWNING counts as alive
  assert.deepStrictEqual(r.alive().map((s) => s.id).sort(), ["a", "c"]);
  assert.deepStrictEqual(r.teardownOrder().sort(), ["a", "c"]);
});

test("a TERMINAL session can be forgotten so its pane id is reusable; a live one cannot", () => {
  const r = new SessionRegistry();
  r.register("pane-1", { nodeId: "n" }, "t0");
  r.transition("pane-1", "RUNNING", "t1", {});
  assert.throws(() => r.forget("pane-1"), /refusing to forget a live session/);
  r.transition("pane-1", "EXITED", "t2", {});
  r.forget("pane-1");
  assert.equal(r.has("pane-1"), false);
  // the append-only lifecycle log keeps the session that ended (invariant 12)
  const log = r.eventLog();
  assert.ok(log.some((e) => e.id === "pane-1" && e.to === "EXITED"));
  // the id is reusable for the relaunched session
  r.register("pane-1", { nodeId: "n" }, "t3");
  assert.equal(r.has("pane-1"), true);
});
