import { describe, expect, it } from "vitest";
import { countdownTo, gameState, hasScoreboard } from "./liveState";
import type { Live } from "./types";

const START = "2026-10-11T20:00:00Z";

function live(status: Live["status"]): Live {
  return {
    status,
    period: null,
    clock: null,
    detail: null,
    home_score: null,
    away_score: null,
    home_record: null,
    away_record: null,
    venue: null,
    broadcast: null,
    possession_side: null,
    down_distance: null,
    last_play: null,
    linescore: null,
    updated_at: new Date().toISOString(),
  };
}

describe("gameState", () => {
  it("is live when the status is in_progress", () => {
    const now = new Date("2026-10-11T20:30:00Z");
    expect(gameState({ scheduled_start: START, live: live("in_progress") }, now)).toBe("live");
  });

  it("is live during halftime", () => {
    const now = new Date("2026-10-11T20:30:00Z");
    expect(gameState({ scheduled_start: START, live: live("halftime") }, now)).toBe("live");
  });

  it("is final when the status is final", () => {
    const now = new Date("2026-10-11T22:30:00Z");
    expect(gameState({ scheduled_start: START, live: live("final") }, now)).toBe("final");
  });

  it("is started when past kickoff with no live status", () => {
    const now = new Date("2026-10-11T20:30:00Z");
    expect(gameState({ scheduled_start: START, live: null }, now)).toBe("started");
    expect(gameState({ scheduled_start: START, live: live("scheduled") }, now)).toBe("started");
  });

  it("is scheduled when before kickoff", () => {
    const now = new Date("2026-10-11T19:30:00Z");
    expect(gameState({ scheduled_start: START, live: null }, now)).toBe("scheduled");
    expect(gameState({ scheduled_start: START, live: live("scheduled") }, now)).toBe("scheduled");
  });
});

describe("countdownTo", () => {
  it("formats hours and minutes", () => {
    const now = new Date("2026-10-11T17:46:00Z");
    expect(countdownTo(START, now)).toBe("starts in 2h 14m");
  });

  it("drops minutes when zero", () => {
    const now = new Date("2026-10-11T18:00:00Z");
    expect(countdownTo(START, now)).toBe("starts in 2h");
  });

  it("formats minutes under an hour", () => {
    const now = new Date("2026-10-11T19:24:00Z");
    expect(countdownTo(START, now)).toBe("starts in 36m");
  });

  it("formats seconds under a minute", () => {
    const now = new Date("2026-10-11T19:59:18Z");
    expect(countdownTo(START, now)).toBe("starts in 42s");
  });

  it("formats days and hours from a day out", () => {
    const now = new Date("2026-10-09T15:46:00Z");
    expect(countdownTo(START, now)).toBe("starts in 2d 4h");
  });

  it("drops hours when a whole number of days out", () => {
    const now = new Date("2026-10-08T20:00:00Z");
    expect(countdownTo(START, now)).toBe("starts in 3d");
  });

  it("returns an empty string once kickoff has passed", () => {
    const now = new Date("2026-10-11T20:01:00Z");
    expect(countdownTo(START, now)).toBe("");
  });
});

describe("hasScoreboard", () => {
  it("shows a game that has not started even with no live state", () => {
    const now = new Date("2026-10-09T20:00:00Z");
    expect(hasScoreboard({ scheduled_start: START, live: null }, now)).toBe(true);
  });

  it("hides a past game that ESPN never wrote a row for", () => {
    const now = new Date("2026-10-12T20:00:00Z");
    expect(hasScoreboard({ scheduled_start: START, live: null }, now)).toBe(false);
  });

  it("shows any game with live state", () => {
    const now = new Date("2026-10-12T20:00:00Z");
    expect(hasScoreboard({ scheduled_start: START, live: live("final") }, now)).toBe(true);
  });
});
