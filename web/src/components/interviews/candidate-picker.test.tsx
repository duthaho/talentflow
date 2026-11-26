// @vitest-environment jsdom
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import type { CandidateCase, InterviewsApi } from "@/lib/interviews/contract";

import { fakeCandidate, fakeInterviewsBackend } from "../../../test/interviews-fake";
import { CandidatePicker, PICKER_LIMIT, SEARCH_DEBOUNCE_MS, type CandidateResults } from "./candidate-picker";

const MANY = Array.from({ length: 250 }, (_, index) => fakeCandidate(`c${index + 1}`, index % 2 ? "interviewing" : "screening"));

function Harness({ api, initial }: { api: InterviewsApi; initial: CandidateResults }) {
  const [selected, setSelected] = useState<CandidateCase | null>(null);
  return <CandidatePicker api={api} initial={initial} selected={selected} onSelect={setSelected} />;
}

function setup(candidates: CandidateCase[], override?: Parameters<typeof fakeInterviewsBackend>[0]["override"]) {
  const backend = fakeInterviewsBackend({ canManage: true, candidates, override });
  const initial = { candidates: candidates.slice(0, PICKER_LIMIT), total: candidates.length };
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  render(<Harness api={backend.api} initial={initial} />);
  return { backend, user, search: screen.getByRole("combobox", { name: "Candidate" }) };
}

function searches(backend: ReturnType<typeof fakeInterviewsBackend>) {
  return backend.requests.map((request) => new URL(request.url).searchParams);
}

function optionNames(): string[] {
  return within(screen.getByRole("listbox", { name: "Candidates" }))
    .queryAllByRole("option")
    .map((option) => option.firstChild!.textContent!);
}

async function debounce() {
  await act(() => vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS));
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => (resolve = done));
  return { promise, resolve };
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe("CandidatePicker", () => {
  it("shows the initial page and says when it is truncated", () => {
    const { backend } = setup(MANY);
    expect(optionNames()).toHaveLength(PICKER_LIMIT);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 20 of 250. Type to search.");
    expect(backend.requests).toHaveLength(0);
  });

  it("sends nothing for fewer than 2 characters", async () => {
    const { backend, user, search } = setup(MANY);
    await user.type(search, " c ");
    await debounce();
    expect(backend.requests).toHaveLength(0);
    expect(optionNames()).toHaveLength(PICKER_LIMIT);
  });

  it("finds a candidate beyond the first page with one request per stage after the debounce", async () => {
    const { backend, user, search } = setup(MANY);
    await user.type(search, "c180");
    expect(screen.getByRole("status")).toHaveTextContent("Searching…");
    expect(backend.requests).toHaveLength(0);

    await debounce();
    expect(searches(backend).map((query) => [query.get("stage"), query.get("q"), query.get("limit")])).toEqual([
      ["screening", "c180", "20"],
      ["interviewing", "c180", "20"],
    ]);
    expect(optionNames()).toEqual(["Grace c180"]);
    expect(screen.getByRole("status")).toHaveTextContent("1 candidate.");
  });

  it("shows the truncation hint for a broad search", async () => {
    const { user, search } = setup(MANY);
    await user.type(search, "c1");
    await debounce();
    expect(optionNames()).toHaveLength(2 * PICKER_LIMIT);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 40 of 111. Type more to narrow the list.");
  });

  it("ignores a slow response for an older term", async () => {
    const slow = deferred();
    const { user, search } = setup(MANY, async (request) => {
      if (new URL(request.url).searchParams.get("q") === "c18") await slow.promise;
      return undefined;
    });
    await user.type(search, "c18");
    await debounce();
    await user.type(search, "0");
    await debounce();
    expect(optionNames()).toEqual(["Grace c180"]);

    slow.resolve();
    await act(() => vi.runAllTimersAsync());
    expect(optionNames()).toEqual(["Grace c180"]);
  });

  it("shows the no-results message", async () => {
    const { user, search } = setup(MANY);
    await user.type(search, "nobody");
    await debounce();
    expect(optionNames()).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("No candidates in Screening or Interviewing match 'nobody'.");
  });

  it("shows a failed search with a working retry", async () => {
    let fail = true;
    const { user, search } = setup(MANY, () =>
      fail ? Response.json({ type: `${PROBLEM_TYPE_BASE}unavailable`, title: "Service unavailable", status: 503 }, { status: 503 }) : undefined,
    );
    await user.type(search, "c42");
    await debounce();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Search failed.");

    fail = false;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await debounce();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(optionNames()).toEqual(["Grace c42"]);
  });

  it("keeps the selection while results change and after clearing the search", async () => {
    const { user, search } = setup(MANY);
    await user.type(search, "c180");
    await debounce();
    await user.click(screen.getByRole("option", { name: /Grace c180/ }));
    expect(screen.getByText("Selected: Grace c180 (c180@x.test)")).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "c42");
    await debounce();
    expect(optionNames()).toEqual(["Grace c42"]);
    expect(screen.getByText("Selected: Grace c180 (c180@x.test)")).toBeInTheDocument();

    await user.clear(search);
    expect(optionNames()).toHaveLength(PICKER_LIMIT);
    expect(screen.getByText("Selected: Grace c180 (c180@x.test)")).toBeInTheDocument();
  });

  it("supports arrow keys, Enter and Escape", async () => {
    const { user, search } = setup(MANY.slice(0, 3));
    await user.click(search);
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(search).toHaveAttribute("aria-activedescendant", expect.stringContaining("c2"));
    await user.keyboard("{Enter}");
    expect(screen.getByRole("option", { name: /Grace c2/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Selected: Grace c2 (c2@x.test)")).toBeInTheDocument();

    await user.type(search, "zz");
    await user.keyboard("{Escape}");
    expect(search).toHaveValue("");
  });
});
