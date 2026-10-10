// Talking to the local server. Every request carries the per-run token header.

const TOKEN = document.querySelector('meta[name="ihs-token"]')?.content || "";

export class ApiError extends Error {
  constructor(status, data) {
    super(data?.message || `HTTP ${status}`);
    this.status = status;
    this.data = data || {};
    this.code = this.data.code || "http_error";
  }
}

export async function call(method, path, body) {
  const headers = { "X-IHS-Token": TOKEN };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (error) {
    throw new ApiError(0, { code: "offline", message: "The ios-homescreen server is not reachable. Is it still running?" });
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

export const get = (path) => call("GET", path);
export const post = (path, body = {}) => call("POST", path, body);

export function iconUrl(id) {
  return `/api/icons/${encodeURIComponent(id)}`;
}

// The version changes with the image, so the browser never shows an old one.
export function wallpaperUrl(version) {
  return `/api/wallpaper?v=${encodeURIComponent(version)}`;
}

// Follow a job's events as they happen. `onEvent(event)` for each, resolves with the
// finished job. Falls back to polling if the stream breaks.
export async function followJob(since, onEvent) {
  let seen = since;
  try {
    const response = await fetch(`/api/job/events?since=${seen}`, {
      headers: { "X-IHS-Token": TOKEN },
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok || !response.body) throw new Error("no stream");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        if (!line.trim()) continue;
        const message = JSON.parse(line);
        if (message.done) return message.job;
        seen = message.seq;
        onEvent(message.event);
      }
    }
  } catch (error) {
    // fall through to polling
  }
  for (;;) {
    const { job } = await get(`/api/job?since=${seen}`);
    if (!job) return null;
    for (const event of job.events) onEvent(event);
    seen = job.event_count;
    if (job.state !== "running") return job;
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}
